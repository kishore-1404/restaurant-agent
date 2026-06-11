-- db/migrations_intelligence.sql

-- Helper: PostgreSQL array intersection (not a built-in for TEXT[])
CREATE OR REPLACE FUNCTION array_intersect(a TEXT[], b TEXT[])
RETURNS TEXT[] LANGUAGE sql IMMUTABLE AS $$
    SELECT ARRAY(SELECT unnest(a) INTERSECT SELECT unnest(b))
$$;

-- The pre-dispatch query. Called once per user turn before the LLM runs.
-- Returns the set of distinct intents that match above their thresholds.
-- Safety-critical intents use a lower threshold (0.72 vs 0.80 default).
CREATE OR REPLACE FUNCTION dispatch_intent(
    p_message_embedding vector(768),
    p_safety_threshold  FLOAT DEFAULT 0.72,   -- lower = fire more readily
    p_default_threshold FLOAT DEFAULT 0.82    -- higher = only fire on clear match
) RETURNS TABLE (
    intent_code         VARCHAR,
    tool_name           VARCHAR,
    tool_params_hint    JSONB,
    is_safety_critical  BOOLEAN,
    similarity          FLOAT,
    example_matched     TEXT
) LANGUAGE sql STABLE AS $$
    SELECT DISTINCT ON (d.intent_code)
        d.intent_code,
        d.tool_name,
        d.tool_params_hint,
        d.is_safety_critical,
        (1 - (d.embedding <=> p_message_embedding))::FLOAT AS similarity,
        d.example_query AS example_matched
    FROM intent_definitions d
    WHERE
        -- Safety-critical intents: use the lower threshold
        CASE WHEN d.is_safety_critical
            THEN (1 - (d.embedding <=> p_message_embedding)) > p_safety_threshold
            ELSE (1 - (d.embedding <=> p_message_embedding)) > d.similarity_threshold
        END
    ORDER BY
        d.intent_code,
        d.embedding <=> p_message_embedding   -- closest match per intent
$$;

-- safety_audit
-- Answers: "Is X safe for me?" / "What can I eat?" / "I have a nut allergy"
CREATE OR REPLACE FUNCTION safety_audit(
    p_restaurant_id INT,
    p_allergens      TEXT[] DEFAULT '{}',     -- customer's allergens
    p_dietary        TEXT[] DEFAULT '{}',     -- dietary restrictions
    p_strict         TEXT[] DEFAULT '{}'      -- anaphylactic risk items — BLOCK not warn
) RETURNS JSONB
LANGUAGE plpgsql STABLE SECURITY DEFINER AS $$
DECLARE
    v_safe        JSONB := '[]';
    v_unsafe      JSONB := '[]';
    v_modifiable  JSONB := '[]';
    v_flags       JSONB := '[]';
    v_kitchen_notice TEXT;
    v_safe_count  INT := 0;
    v_unsafe_count INT := 0;
    v_mod_count   INT := 0;
BEGIN
    -- Get kitchen cross-contamination notice from restaurant metadata
    SELECT metadata->>'allergen_kitchen_notice'
    INTO   v_kitchen_notice
    FROM   restaurants
    WHERE  id = p_restaurant_id;

    -- SAFE ITEMS: no allergen overlap, dietary restrictions respected
    SELECT jsonb_agg(
        jsonb_build_object(
            'name',      m.name,
            'price',     m.price,
            'category',  c.name,
            'tags',      m.tags
        ) ORDER BY c.display_order, m.display_order
    )
    INTO v_safe
    FROM menu_items m
    LEFT JOIN menu_categories c ON c.id = m.category_id
    WHERE m.restaurant_id = p_restaurant_id
      AND m.is_available  = true
      AND NOT (m.allergens::text[] && p_allergens)                    -- no allergen overlap
      AND (
          NOT ('vegan'       = ANY(p_dietary)) OR m.tags @> '"vegan"'::jsonb
      )
      AND (
          NOT ('vegetarian'  = ANY(p_dietary)) OR m.tags @> '"vegetarian"'::jsonb
                                               OR m.tags @> '"vegan"'::jsonb
      )
      AND (
          NOT ('gluten-free' = ANY(p_dietary)) OR m.tags @> '"gluten-free"'::jsonb
      );

    GET DIAGNOSTICS v_safe_count = ROW_COUNT;

    -- UNSAFE ITEMS (no modification path)
    WITH unsafe_check AS (
        SELECT m.name, m.price, c.name AS category,
               array_intersect(m.allergens::text[], p_allergens) AS conflicting_allergens,
               -- Check if modification can remove all conflicting allergens
               -- A modification is viable only if all conflicts are in allowed_modifications.remove
               (
                   SELECT bool_and(
                       allergen = ANY(
                           SELECT jsonb_array_elements_text(m.allowed_modifications->'remove')
                       )
                   )
                   FROM unnest(array_intersect(m.allergens::text[], p_allergens)) AS allergen
               ) AS can_be_made_safe
        FROM menu_items m
        LEFT JOIN menu_categories c ON c.id = m.category_id
        WHERE m.restaurant_id = p_restaurant_id
          AND m.is_available  = true
          AND m.allergens::text[] && p_allergens   -- has at least one conflict
    )
    SELECT jsonb_agg(
        jsonb_build_object(
            'name',                u.name,
            'price',               u.price,
            'conflicting_allergens', u.conflicting_allergens,
            'can_be_made_safe',    COALESCE(u.can_be_made_safe, false)
        )
    ),
    count(*) FILTER (WHERE NOT COALESCE(u.can_be_made_safe, false)),
    count(*) FILTER (WHERE COALESCE(u.can_be_made_safe, false))
    INTO v_unsafe, v_unsafe_count, v_mod_count
    FROM unsafe_check u;

    -- MODIFIABLE ITEMS: subset of unsafe that CAN be made safe
    SELECT jsonb_agg(
        jsonb_build_object(
            'name',               elem->>'name',
            'price',              elem->>'price',
            'remove_to_make_safe', (
                SELECT jsonb_agg(allergen)
                FROM jsonb_array_elements_text(elem->'conflicting_allergens') AS allergen
            ),
            'instruction', 'Ask to remove: ' || (
                SELECT string_agg(allergen, ', ')
                FROM jsonb_array_elements_text(elem->'conflicting_allergens') AS allergen
            )
        )
    )
    INTO v_modifiable
    FROM jsonb_array_elements(COALESCE(v_unsafe, '[]')) AS elem
    WHERE (elem->>'can_be_made_safe')::boolean = true;

    -- Filter unsafe to only truly unsafe (not modifiable)
    SELECT jsonb_agg(elem)
    INTO v_unsafe
    FROM jsonb_array_elements(COALESCE(v_unsafe, '[]')) AS elem
    WHERE (elem->>'can_be_made_safe')::boolean = false;

    -- Safety flags
    IF v_kitchen_notice IS NOT NULL THEN
        v_flags := v_flags || jsonb_build_array(v_kitchen_notice);
    END IF;

    IF p_strict IS NOT NULL AND array_length(p_strict, 1) > 0 THEN
        v_flags := v_flags || jsonb_build_array(
            format('Strict allergen risk for: %s — cross-contamination may occur even in safe items.',
                   array_to_string(p_strict, ', '))
        );
    END IF;

    RETURN jsonb_build_object(
        'status',     'ok',
        'data',       jsonb_build_object(
            'verdict',          CASE
                                  WHEN v_safe_count = 0 THEN 'HIGH_RISK'
                                  WHEN v_unsafe_count > 0 THEN 'CAUTION'
                                  ELSE 'SAFE'
                                END,
            'safe_items',       COALESCE(v_safe,        '[]'),
            'unsafe_items',     COALESCE(v_unsafe,       '[]'),
            'modifiable_items', COALESCE(v_modifiable,   '[]'),
            'safe_count',       COALESCE(v_safe_count,   0),
            'unsafe_count',     COALESCE(v_unsafe_count, 0),
            'modifiable_count', COALESCE(v_mod_count,    0)
        ),
        'context',    jsonb_build_object(
            'allergens_checked',    p_allergens,
            'dietary_applied',      p_dietary,
            'strict_allergens',     p_strict,
            'total_items_checked',  (SELECT count(*) FROM menu_items
                                     WHERE restaurant_id = p_restaurant_id AND is_available = true)
        ),
        'safety_flags', COALESCE(v_flags, '[]'),
        'llm_guidance', CASE
            WHEN v_safe_count = 0 THEN
                'State clearly that very few or no items are safe as-is. '
                'Lead with modifiable items as options. Be honest, not apologetic.'
            WHEN v_unsafe_count > 0 THEN
                'Lead with the safe items — state the count confidently. '
                'Mention modifiable items as opportunities. '
                'List unsafe items briefly at the end. '
                'State any safety_flags once, clearly. Do not minimise or bury them.'
            ELSE
                'Confirm the customer can eat freely. '
                'Mention the item count briefly. '
                'State any kitchen notices once.'
        END
    );
END;
$$;

-- get_item_detail
CREATE OR REPLACE FUNCTION get_item_detail(
    p_restaurant_id INT,
    p_item_name     TEXT       -- fuzzy match allowed
) RETURNS JSONB
LANGUAGE plpgsql STABLE SECURITY DEFINER AS $$
DECLARE
    v_item          RECORD;
    v_match_score   FLOAT;
BEGIN
    -- Fuzzy match by name (trigram similarity) — handles typos, partial names
    SELECT m.name, m.price, m.description, m.ingredients, m.allergens, m.tags, 
           m.nutrition_info, m.allowed_modifications, m.is_available,
           c.name AS category_name, similarity(m.name, p_item_name) AS score
    INTO   v_item
    FROM   menu_items m
    LEFT   JOIN menu_categories c ON c.id = m.category_id
    WHERE  m.restaurant_id = p_restaurant_id
      AND  m.is_available  = true
      AND  similarity(m.name, p_item_name) > 0.25
    ORDER  BY similarity(m.name, p_item_name) DESC
    LIMIT  1;

    IF NOT FOUND THEN
        RETURN jsonb_build_object(
            'status', 'no_results',
            'data',   '{}',
            'safety_flags', '[]'
        );
    END IF;

    -- Build safe response: no internal IDs, no DB metadata
    RETURN jsonb_build_object(
        'status', 'ok',
        'data', jsonb_build_object(
            'name',           v_item.name,
            'category',       v_item.category_name,
            'price',          v_item.price,
            'description',    v_item.description,
            'ingredients',    v_item.ingredients,
            'allergens',      v_item.allergens,
            'tags',           v_item.tags,
            'nutrition',      v_item.nutrition_info,  -- {calories, protein_g, carbs_g, fat_g, sodium_mg}
            'modifications',  jsonb_build_object(
                'can_remove',  v_item.allowed_modifications->'remove',
                'can_swap',    v_item.allowed_modifications->'swap',
                'can_add',     v_item.allowed_modifications->'add'
            ),
            'is_available',   v_item.is_available,
            'match_confidence', CASE
                WHEN v_item.score > 0.9 THEN 'exact'
                WHEN v_item.score > 0.6 THEN 'high'
                ELSE 'fuzzy'
            END
        ),
        'context', jsonb_build_object(
            'searched_for', p_item_name,
            'matched_to',   v_item.name
        ),
        'safety_flags', CASE
            WHEN array_length(v_item.allergens::text[], 1) > 0
            THEN jsonb_build_array(
                format('Contains: %s', array_to_string(v_item.allergens, ', '))
            )
            ELSE '[]'
        END
    );
END;
$$;

-- explore_semantic
CREATE OR REPLACE FUNCTION explore_semantic(
    p_restaurant_id  INT,
    p_query_embedding vector(768),
    p_allergens       TEXT[]  DEFAULT '{}',
    p_dietary         TEXT[]  DEFAULT '{}',
    p_max_price       NUMERIC DEFAULT NULL,
    p_max_calories    INT     DEFAULT NULL,
    p_category        TEXT    DEFAULT NULL,
    p_sort            TEXT    DEFAULT 'semantic',   -- 'semantic' | 'price_asc' | 'calories_asc'
    p_limit           INT     DEFAULT 5
) RETURNS JSONB
LANGUAGE sql STABLE SECURITY DEFINER AS $$
WITH filtered AS (
    SELECT
        m.name,
        m.price,
        m.description,
        m.tags,
        c.name                                            AS category,
        (m.nutrition_info->>'calories')::int              AS calories,
        (m.nutrition_info->>'protein_g')::float           AS protein,
        1 - (m.embedding <=> p_query_embedding)           AS semantic_score,
        -- Brief match explanation based on tags
        CASE
            WHEN m.tags @> '"spicy"'::jsonb        THEN 'has heat'
            WHEN m.tags @> '"gluten-free"'::jsonb  THEN 'gluten-free'
            WHEN m.tags @> '"vegan"'::jsonb        THEN 'vegan'
            WHEN m.tags @> '"vegetarian"'::jsonb   THEN 'vegetarian'
            WHEN m.tags @> '"bestseller"'::jsonb   THEN 'customer favourite'
            ELSE NULL
        END                                               AS tag_note
    FROM   menu_items m
    LEFT JOIN menu_categories c ON c.id = m.category_id
    WHERE  m.restaurant_id = p_restaurant_id
      AND  m.is_available  = true
      AND  m.embedding     IS NOT NULL              -- only items with embeddings
      AND  NOT (m.allergens::text[] && p_allergens)         -- safe for customer
      AND  (
              NOT ('vegan'       = ANY(p_dietary)) OR m.tags @> '"vegan"'::jsonb
          )
      AND  (
              NOT ('vegetarian'  = ANY(p_dietary)) OR m.tags @> '"vegetarian"'::jsonb
                                                   OR m.tags @> '"vegan"'::jsonb
          )
      AND  (p_max_price    IS NULL OR m.price  <= p_max_price)
      AND  (p_max_calories IS NULL OR (m.nutrition_info->>'calories')::int <= p_max_calories)
      AND  (p_category     IS NULL OR c.name ILIKE p_category)
),
ranked AS (
    SELECT *,
        ROW_NUMBER() OVER (
            ORDER BY CASE p_sort
                WHEN 'price_asc'    THEN price::float
                WHEN 'calories_asc' THEN calories::float
                ELSE -semantic_score
            END
        ) AS rank
    FROM filtered
    WHERE semantic_score > 0.55    -- minimum relevance threshold
)
SELECT
    CASE WHEN count(*) = 0 THEN
        jsonb_build_object(
            'status', 'no_results',
            'data', '{}',
            'safety_flags', '[]',
            'llm_guidance', 'No items match this description with current filters. '
                || 'Suggest loosening the filters (price, dietary) or describe differently.'
        )
    ELSE
        jsonb_build_object(
            'status', 'ok',
            'data', jsonb_build_object(
                'results', jsonb_agg(
                    jsonb_build_object(
                        'name',       name,
                        'price',      price,
                        'category',   category,
                        'description', description,
                        'tags',       tags,
                        'calories',   calories,
                        'tag_note',   tag_note
                    )
                    ORDER BY rank
                )
            ),
            'context', jsonb_build_object(
                'results_count', count(*),
                'allergens_filtered', p_allergens,
                'sort_applied', p_sort
            ),
            'safety_flags', '[]'
        )
    END
FROM ranked
WHERE rank <= p_limit;
$$;

-- compare_items
CREATE OR REPLACE FUNCTION compare_items(
    p_restaurant_id INT,
    p_item_a        TEXT,
    p_item_b        TEXT
) RETURNS JSONB
LANGUAGE plpgsql STABLE SECURITY DEFINER AS $$
DECLARE
    v_a menu_items;
    v_b menu_items;
BEGIN
    SELECT * INTO v_a FROM menu_items
    WHERE restaurant_id = p_restaurant_id AND is_available = true
      AND similarity(name, p_item_a) > 0.25
    ORDER BY similarity(name, p_item_a) DESC LIMIT 1;

    SELECT * INTO v_b FROM menu_items
    WHERE restaurant_id = p_restaurant_id AND is_available = true
      AND similarity(name, p_item_b) > 0.25
    ORDER BY similarity(name, p_item_b) DESC LIMIT 1;

    IF NOT FOUND OR v_a.id IS NULL OR v_b.id IS NULL THEN
        RETURN jsonb_build_object(
            'status', 'no_results',
            'data', '{}',
            'safety_flags', '[]'
        );
    END IF;

    -- Compute differences for key dimensions
    RETURN jsonb_build_object(
        'status', 'ok',
        'data', jsonb_build_object(
            'item_a', jsonb_build_object(
                'name',        v_a.name,
                'price',       v_a.price,
                'calories',    (v_a.nutrition_info->>'calories')::int,
                'protein_g',   (v_a.nutrition_info->>'protein_g')::float,
                'tags',        v_a.tags,
                'allergens',   v_a.allergens,
                'description', v_a.description
            ),
            'item_b', jsonb_build_object(
                'name',        v_b.name,
                'price',       v_b.price,
                'calories',    (v_b.nutrition_info->>'calories')::int,
                'protein_g',   (v_b.nutrition_info->>'protein_g')::float,
                'tags',        v_b.tags,
                'allergens',   v_b.allergens,
                'description', v_b.description
            ),
            'differences', jsonb_build_object(
                'price_diff',    round((v_b.price - v_a.price)::numeric, 2),
                'calorie_diff',  coalesce((v_b.nutrition_info->>'calories')::int, 0)
                               - coalesce((v_a.nutrition_info->>'calories')::int, 0),
                'protein_diff',  coalesce((v_b.nutrition_info->>'protein_g')::float, 0)
                               - coalesce((v_a.nutrition_info->>'protein_g')::float, 0),
                'allergen_diff', jsonb_build_object(
                    'only_in_a', (SELECT jsonb_agg(x) FROM unnest(v_a.allergens) x
                                  WHERE NOT (x = ANY(v_b.allergens))),
                    'only_in_b', (SELECT jsonb_agg(x) FROM unnest(v_b.allergens) x
                                  WHERE NOT (x = ANY(v_a.allergens)))
                ),
                'a_is_cheaper',       v_a.price < v_b.price,
                'a_is_lower_cal',     coalesce((v_a.nutrition_info->>'calories')::int,0)
                                    < coalesce((v_b.nutrition_info->>'calories')::int,0),
                'a_is_higher_protein', coalesce((v_a.nutrition_info->>'protein_g')::float,0)
                                     > coalesce((v_b.nutrition_info->>'protein_g')::float,0)
            )
        ),
        'context',      jsonb_build_object('searched_a', p_item_a, 'searched_b', p_item_b),
        'safety_flags', '[]'
    );
END;
$$;

-- get_recommendations
CREATE OR REPLACE FUNCTION get_recommendations(
    p_restaurant_id INT,
    p_allergens     TEXT[]  DEFAULT '{}',
    p_dietary       TEXT[]  DEFAULT '{}',
    p_time_of_day   TEXT    DEFAULT 'day',   -- 'morning' | 'day' | 'evening' | 'night'
    p_limit         INT     DEFAULT 5
) RETURNS JSONB
LANGUAGE sql STABLE SECURITY DEFINER AS $$
WITH
-- Historical popularity (real order count)
popularity AS (
    SELECT oi.menu_item_id, count(*)::int AS order_count
    FROM   order_items oi
    JOIN   orders o ON o.id = oi.order_id AND o.status = 'completed'
    WHERE  o.restaurant_id = p_restaurant_id
    GROUP  BY oi.menu_item_id
),
-- Items safe for this customer
safe_items AS (
    SELECT m.*, c.name AS category_name, COALESCE(p.order_count, 0) AS popularity
    FROM   menu_items m
    LEFT   JOIN menu_categories c ON c.id = m.category_id
    LEFT   JOIN popularity p ON p.menu_item_id = m.id
    WHERE  m.restaurant_id = p_restaurant_id
      AND  m.is_available  = true
      AND  NOT (m.allergens::text[] && p_allergens)
      AND  (NOT ('vegan'      = ANY(p_dietary)) OR m.tags @> '"vegan"'::jsonb)
      AND  (NOT ('vegetarian' = ANY(p_dietary)) OR m.tags @> '"vegetarian"'::jsonb
                                               OR m.tags @> '"vegan"'::jsonb)
),
-- Scored by popularity + bestseller tag + time-of-day relevance
scored AS (
    SELECT *,
        popularity * 1.0
        + CASE WHEN tags @> '"bestseller"'::jsonb THEN 20 ELSE 0 END
        + CASE
            WHEN p_time_of_day = 'morning' AND category_name ILIKE '%breakfast%' THEN 15
            WHEN p_time_of_day = 'evening' AND category_name ILIKE '%main%'      THEN 10
            ELSE 0
          END AS score
    FROM safe_items
)
SELECT jsonb_build_object(
    'status', 'ok',
    'data', jsonb_build_object(
        'recommendations', jsonb_agg(
            jsonb_build_object(
                'name',        name,
                'price',       price,
                'category',    category_name,
                'description', description,
                'tags',        tags,
                'order_count', popularity,
                'is_bestseller', tags @> '"bestseller"'::jsonb
            ) ORDER BY score DESC
        )
    ),
    'context', jsonb_build_object(
        'based_on',       'real order history',
        'allergens_safe', p_allergens,
        'time_of_day',    p_time_of_day
    ),
    'safety_flags', '[]'
) FROM scored
LIMIT p_limit;
$$;

-- suggest_complete_meal
CREATE OR REPLACE FUNCTION suggest_complete_meal(
    p_restaurant_id INT,
    p_budget        NUMERIC,
    p_allergens     TEXT[]  DEFAULT '{}',
    p_dietary       TEXT[]  DEFAULT '{}',
    p_goal          TEXT    DEFAULT 'balanced'   -- 'high_protein' | 'low_cal' | 'cheapest' | 'balanced'
) RETURNS JSONB
LANGUAGE sql STABLE SECURITY DEFINER AS $$
WITH
safe_mains AS (
    SELECT m.name, m.price,
           (m.nutrition_info->>'protein_g')::float AS protein,
           (m.nutrition_info->>'calories')::int AS calories
    FROM menu_items m
    JOIN menu_categories c ON c.id = m.category_id
    WHERE m.restaurant_id = p_restaurant_id AND m.is_available = true
      AND c.name ILIKE '%main%'
      AND NOT (m.allergens::text[] && p_allergens)
      AND (NOT ('vegan' = ANY(p_dietary)) OR m.tags @> '"vegan"'::jsonb)
),
safe_sides AS (
    SELECT m.name, m.price,
           (m.nutrition_info->>'protein_g')::float AS protein,
           (m.nutrition_info->>'calories')::int AS calories
    FROM menu_items m
    JOIN menu_categories c ON c.id = m.category_id
    WHERE m.restaurant_id = p_restaurant_id AND m.is_available = true
      AND c.name ILIKE '%side%'
      AND NOT (m.allergens::text[] && p_allergens)
      AND (NOT ('vegan' = ANY(p_dietary)) OR m.tags @> '"vegan"'::jsonb)
),
safe_drinks AS (
    SELECT m.name, m.price
    FROM menu_items m
    JOIN menu_categories c ON c.id = m.category_id
    WHERE m.restaurant_id = p_restaurant_id AND m.is_available = true
      AND c.name ILIKE '%drink%'
      AND NOT (m.allergens::text[] && p_allergens)
      AND (NOT ('vegan' = ANY(p_dietary)) OR m.tags @> '"vegan"'::jsonb)
),
combos AS (
    SELECT
        m.name AS main,  m.price AS main_price,  m.calories AS main_cal, m.protein AS main_prot,
        s.name AS side,  s.price AS side_price,
        d.name AS drink, d.price AS drink_price,
        m.price + s.price + d.price AS total,
        COALESCE(m.calories, 0) + COALESCE(s.calories, 0) AS total_calories,
        COALESCE(m.protein, 0) + COALESCE(s.protein, 0) AS total_protein
    FROM   safe_mains  m,
           safe_sides  s,
           safe_drinks d
    WHERE  m.price + s.price + d.price <= p_budget
)
SELECT
    CASE WHEN count(*) = 0 THEN
        jsonb_build_object(
            'status', 'no_results',
            'data', '{}',
            'safety_flags', '[]',
            'llm_guidance',
                format('No complete meal under $%s with current restrictions. '
                       'Suggest increasing the budget or adjusting dietary filters.', p_budget)
        )
    ELSE
        jsonb_build_object(
            'status', 'ok',
            'data', jsonb_build_object(
                'meals', (
                    SELECT jsonb_agg(meal ORDER BY score) FROM (
                        SELECT jsonb_build_object(
                            'main',           main,
                            'side',           side,
                            'drink',          drink,
                            'total',          total,
                            'total_calories', total_calories,
                            'total_protein_g', total_protein
                        ) AS meal,
                        CASE p_goal
                            WHEN 'high_protein' THEN -total_protein
                            WHEN 'low_cal'      THEN total_calories
                            WHEN 'cheapest'     THEN total
                            ELSE -(total_protein / NULLIF(total, 0))  -- value: protein per dollar
                        END AS score,
                        ROW_NUMBER() OVER (
                            ORDER BY CASE p_goal
                                WHEN 'high_protein' THEN -total_protein
                                WHEN 'low_cal'      THEN total_calories
                                WHEN 'cheapest'     THEN total
                                ELSE -(total_protein / NULLIF(total, 0))
                            END
                        ) AS rn
                        FROM combos
                    ) sub WHERE rn <= 3
                ),
                'goal_applied', p_goal,
                'budget',       p_budget
            ),
            'context',      jsonb_build_object('combinations_evaluated', count(*)),
            'safety_flags', '[]',
            'llm_guidance',
                'Present the first meal option as the primary suggestion. '
                'Briefly mention the alternatives as variants. '
                'State the total for each. Do not explain the optimization goal unless asked.'
        )
    END
FROM combos;
$$;

-- get_pairings
CREATE OR REPLACE FUNCTION get_pairings(
    p_restaurant_id INT,
    p_item_name     TEXT,
    p_allergens     TEXT[] DEFAULT '{}'
) RETURNS JSONB
LANGUAGE plpgsql STABLE SECURITY DEFINER AS $$
DECLARE
    v_item_id INT;
BEGIN
    SELECT m.id INTO v_item_id
    FROM   menu_items m
    WHERE  m.restaurant_id = p_restaurant_id
      AND  similarity(m.name, p_item_name) > 0.25
    ORDER  BY similarity(m.name, p_item_name) DESC
    LIMIT  1;

    IF NOT FOUND THEN
        RETURN jsonb_build_object(
            'status', 'no_results', 'data', '{}',
            'safety_flags', '[]'
        );
    END IF;

    RETURN (
        SELECT jsonb_build_object(
            'status', CASE WHEN count(*) > 0 THEN 'ok' ELSE 'no_results' END,
            'data', jsonb_build_object(
                'anchor_item', p_item_name,
                'top_pairings', jsonb_agg(
                    jsonb_build_object(
                        'name',          paired_item_name,
                        'price',         paired_item_price,
                        'co_order_rate', round((co_occurrence * 100.0 /
                            NULLIF((SELECT count(*) FROM order_items oi
                                    JOIN orders o ON o.id = oi.order_id
                                    WHERE oi.menu_item_id = v_item_id
                                      AND o.status = 'completed'), 0))::numeric, 0),
                        'lift_score',    lift_score
                    ) ORDER BY lift_score DESC
                )
            ),
            'context',      jsonb_build_object('based_on', 'real order co-occurrence'),
            'safety_flags', '[]'
        )
        FROM top_pairings tp
        WHERE tp.item_a_id = v_item_id
          AND tp.lift_score > 1.2   -- only meaningful pairings
          AND NOT EXISTS (          -- safe for customer
              SELECT 1 FROM menu_items mi
              WHERE mi.id = tp.item_b_id
                AND mi.allergens::text[] && p_allergens
          )
    );
END;
$$;

-- get_restaurant_info
CREATE OR REPLACE FUNCTION get_restaurant_info(
    p_restaurant_id INT,
    p_field         TEXT    -- e.g. 'hours', 'payment', 'delivery', 'allergen_policy'
) RETURNS JSONB
LANGUAGE plpgsql STABLE SECURITY DEFINER AS $$
DECLARE
    v_value TEXT;
    v_meta  JSONB;
BEGIN
    SELECT metadata INTO v_meta
    FROM   restaurants
    WHERE  id = p_restaurant_id;

    -- Try the specific field first
    v_value := v_meta->>p_field;

    IF v_value IS NULL THEN
        -- Try fuzzy field matching across known keys
        SELECT value::text INTO v_value
        FROM   jsonb_each_text(v_meta)
        WHERE  similarity(key, p_field) > 0.4
        ORDER  BY similarity(key, p_field) DESC
        LIMIT  1;
    END IF;

    IF v_value IS NULL THEN
        RETURN jsonb_build_object(
            'status', 'no_results',
            'data', '{}',
            'safety_flags', '[]'
        );
    END IF;

    RETURN jsonb_build_object(
        'status', 'ok',
        'data',   jsonb_build_object('field', p_field, 'value', v_value),
        'context', jsonb_build_object('exact_match', v_meta ? p_field),
        'safety_flags', '[]'
    );
END;
$$;

-- find_by_description
CREATE OR REPLACE FUNCTION find_by_description(
    p_restaurant_id   INT,
    p_description     TEXT,
    p_query_embedding vector(768) DEFAULT NULL,
    p_allergens       TEXT[] DEFAULT '{}'
) RETURNS JSONB
LANGUAGE plpgsql STABLE SECURITY DEFINER AS $$
DECLARE
    v_results JSONB;
BEGIN
    -- Method 1: FTS (fast, keyword-based)
    SELECT jsonb_agg(
        jsonb_build_object(
            'name',        m.name,
            'price',       m.price,
            'description', m.description,
            'match_method', 'full_text',
            'confidence',  'medium'
        ) ORDER BY ts_rank(m.search_vector, plainto_tsquery('english', p_description)) DESC
    )
    INTO v_results
    FROM menu_items m
    WHERE m.restaurant_id = p_restaurant_id
      AND m.is_available  = true
      AND NOT (m.allergens::text[] && p_allergens)
      AND m.search_vector @@ plainto_tsquery('english', p_description)
    LIMIT 3;

    IF v_results IS NOT NULL AND jsonb_array_length(v_results) > 0 THEN
        RETURN jsonb_build_object(
            'status', 'ok',
            'data',   jsonb_build_object('matches', v_results),
            'safety_flags', '[]',
            'llm_guidance',
                'Confirm which item the customer means by naming it and asking. '
                'Do not add it to the order until confirmed. Keep it to one question.'
        );
    END IF;

    -- Method 2: Semantic (if embedding provided)
    IF p_query_embedding IS NOT NULL THEN
        SELECT jsonb_agg(
            jsonb_build_object(
                'name',        m.name,
                'price',       m.price,
                'description', m.description,
                'match_method', 'semantic',
                'confidence',  CASE WHEN 1-(m.embedding<=>p_query_embedding)>0.8 THEN 'high' ELSE 'medium' END
            ) ORDER BY m.embedding <=> p_query_embedding
        )
        INTO v_results
        FROM menu_items m
        WHERE m.restaurant_id = p_restaurant_id
          AND m.is_available  = true
          AND NOT (m.allergens::text[] && p_allergens)
          AND 1 - (m.embedding <=> p_query_embedding) > 0.60
        LIMIT 3;

        IF v_results IS NOT NULL AND jsonb_array_length(v_results) > 0 THEN
            RETURN jsonb_build_object(
                'status', 'ok',
                'data',   jsonb_build_object('matches', v_results),
                'safety_flags', '[]',
                'llm_guidance',
                    'Suggest the best match by name with a brief description. '
                    'Ask if this is what the customer meant before adding it.'
            );
        END IF;
    END IF;

    -- Method 3: Trigram fallback
    SELECT jsonb_agg(
        jsonb_build_object(
            'name',        m.name,
            'price',       m.price,
            'match_method', 'fuzzy',
            'confidence',  'low'
        ) ORDER BY similarity(m.name || ' ' || coalesce(m.description,''), p_description) DESC
    )
    INTO v_results
    FROM menu_items m
    WHERE m.restaurant_id = p_restaurant_id
      AND m.is_available  = true
      AND NOT (m.allergens::text[] && p_allergens)
      AND similarity(m.name || ' ' || coalesce(m.description,''), p_description) > 0.15
    LIMIT 2;

    IF v_results IS NOT NULL THEN
        RETURN jsonb_build_object(
            'status', 'partial',
            'data',   jsonb_build_object('matches', v_results),
            'safety_flags', '[]',
            'llm_guidance',
                'Low confidence match. Ask the customer if any of these sound right. '
                'Offer to describe items if they are unsure.'
        );
    END IF;

    RETURN jsonb_build_object(
        'status', 'no_results', 'data', '{}',
        'safety_flags', '[]',
        'llm_guidance', 'Nothing matched the description. Ask one targeted question to narrow it down.'
    );
END;
$$;


-- get_active_offers
-- Allows LLM to intelligently navigate promotions, discounts, order rules, and deal schedules.
CREATE OR REPLACE FUNCTION get_active_offers(
    p_restaurant_id INT,
    p_order_id      INT,
    p_now           TIMESTAMP DEFAULT CURRENT_TIMESTAMP
) RETURNS JSONB
LANGUAGE plpgsql STABLE SECURITY DEFINER AS $$
DECLARE
    v_date DATE := p_now::DATE;
    v_time TIME := p_now::TIME;
    v_day  INT := EXTRACT(DOW FROM p_now); -- 0=Sunday..6=Saturday
    v_applied_discounts JSONB := '[]';
    v_available_offers  JSONB := '[]';
    v_all_offers_schedule JSONB := '[]';
    v_order_rules_status JSONB := '[]';
    v_order_total NUMERIC := 0;
    v_discount_total NUMERIC := 0;
BEGIN
    -- Get order totals if order exists
    IF p_order_id IS NOT NULL THEN
        SELECT COALESCE(total, 0), COALESCE(discount_total, 0)
        INTO v_order_total, v_discount_total
        FROM orders
        WHERE id = p_order_id;
    END IF;

    -- 1. Applied Discounts (from order_items table for the current order)
    IF p_order_id IS NOT NULL THEN
        SELECT COALESCE(jsonb_agg(
            jsonb_build_object(
                'item_name',      oi.name_snapshot,
                'quantity',       oi.quantity,
                'original_price', oi.original_price,
                'discounted_price', oi.price_snapshot,
                'savings',        (oi.original_price - oi.price_snapshot) * oi.quantity
            )
        ), '[]'::jsonb)
        INTO v_applied_discounts
        FROM order_items oi
        WHERE oi.order_id = p_order_id
          AND oi.original_price IS NOT NULL
          AND oi.original_price > oi.price_snapshot;
    END IF;

    -- 2. Available Offers RIGHT NOW (active price rules matching current date/time)
    WITH active_rules AS (
        SELECT pr.id, pr.name, pr.label, pr.description, pr.rule_type, pr.value, pr.applies_to, pr.applies_to_ids
        FROM price_rules pr
        WHERE pr.restaurant_id = p_restaurant_id
          AND pr.is_active = true
          AND (pr.valid_date_from IS NULL OR pr.valid_date_from <= v_date)
          AND (pr.valid_date_until IS NULL OR pr.valid_date_until >= v_date)
          AND (pr.valid_days IS NULL OR v_day = ANY(pr.valid_days))
          AND (pr.valid_from IS NULL OR pr.valid_from <= v_time)
          AND (pr.valid_until IS NULL OR pr.valid_until >= v_time)
    ),
    rule_eligible_items AS (
        SELECT ar.id AS rule_id,
               jsonb_agg(
                   jsonb_build_object(
                       'name',          mi.name,
                       'regular_price', mi.price,
                       'discounted_price', CASE
                           WHEN ar.rule_type = 'percentage_off' THEN mi.price * (1 - ar.value / 100)
                           WHEN ar.rule_type = 'fixed_off' THEN GREATEST(mi.price - ar.value, 0)
                           WHEN ar.rule_type = 'fixed_price' THEN ar.value
                           ELSE mi.price
                       END
                   )
               ) AS eligible_items
        FROM active_rules ar
        JOIN menu_items mi ON mi.restaurant_id = p_restaurant_id AND mi.is_available = true
        WHERE ar.applies_to = 'all'
           OR (ar.applies_to = 'category' AND mi.category_id = ANY(ar.applies_to_ids))
           OR (ar.applies_to = 'item' AND mi.id = ANY(ar.applies_to_ids))
        GROUP BY ar.id
    )
    SELECT COALESCE(jsonb_agg(
        jsonb_build_object(
            'name',        ar.name,
            'description', ar.description,
            'label',       ar.label,
            'eligible_items', COALESCE(rei.eligible_items, '[]'::jsonb)
        )
    ), '[]'::jsonb)
    INTO v_available_offers
    FROM active_rules ar
    LEFT JOIN rule_eligible_items rei ON rei.rule_id = ar.id;

    -- 3. All Offers Schedule (Active rules at any day/time, allowing exploration of other days)
    WITH all_rules AS (
        SELECT pr.id, pr.name, pr.label, pr.description, pr.rule_type, pr.value, pr.applies_to, pr.applies_to_ids,
               pr.valid_days, pr.valid_from, pr.valid_until
        FROM price_rules pr
        WHERE pr.restaurant_id = p_restaurant_id
          AND pr.is_active = true
    ),
    all_rule_items AS (
        SELECT al.id AS rule_id,
               jsonb_agg(mi.name) AS eligible_item_names
        FROM all_rules al
        JOIN menu_items mi ON mi.restaurant_id = p_restaurant_id AND mi.is_available = true
        WHERE al.applies_to = 'all'
           OR (al.applies_to = 'category' AND mi.category_id = ANY(al.applies_to_ids))
           OR (al.applies_to = 'item' AND mi.id = ANY(al.applies_to_ids))
        GROUP BY al.id
    )
    SELECT COALESCE(jsonb_agg(
        jsonb_build_object(
            'name',        al.name,
            'description', al.description,
            'label',       al.label,
            'valid_days',  al.valid_days,
            'valid_from',  al.valid_from,
            'valid_until', al.valid_until,
            'eligible_items', COALESCE(ari.eligible_item_names, '[]'::jsonb)
        )
    ), '[]'::jsonb)
    INTO v_all_offers_schedule
    FROM all_rules al
    LEFT JOIN all_rule_items ari ON ari.rule_id = al.id;

    -- 4. Order Rules Status (min_total, max_total, etc.)
    SELECT COALESCE(jsonb_agg(
        jsonb_build_object(
            'rule_type',   orl.rule_type,
            'description', orl.description,
            'target_value', orl.value,
            'current_value', v_order_total,
            'status',      CASE
                WHEN orl.rule_type = 'min_total' THEN
                    CASE WHEN v_order_total >= orl.value THEN 'met' ELSE 'unmet' END
                WHEN orl.rule_type = 'max_total' THEN
                    CASE WHEN v_order_total <= orl.value THEN 'met' ELSE 'violated' END
                ELSE 'active'
            END,
            'remaining_needed', CASE
                WHEN orl.rule_type = 'min_total' AND v_order_total < orl.value THEN
                    orl.value - v_order_total
                ELSE 0
            END,
            'suggestion',  CASE
                WHEN orl.rule_type = 'min_total' AND v_order_total < orl.value THEN
                    COALESCE(orl.error_message, 'Add a side or drink to meet the minimum.')
                ELSE NULL
            END
        )
    ), '[]'::jsonb)
    INTO v_order_rules_status
    FROM order_rules orl
    WHERE orl.restaurant_id = p_restaurant_id
      AND orl.is_active = true;

    RETURN jsonb_build_object(
        'status', 'ok',
        'data', jsonb_build_object(
            'applied_discounts',  v_applied_discounts,
            'available_offers',   v_available_offers,
            'all_offers_schedule', v_all_offers_schedule,
            'order_rules_status', v_order_rules_status
        ),
        'safety_flags', '[]',
        'llm_guidance', CASE
            -- If order is under minimum total
            WHEN EXISTS (
                SELECT 1 FROM jsonb_array_elements(v_order_rules_status) r
                WHERE r->>'rule_type' = 'min_total' AND r->>'status' = 'unmet'
            ) THEN
                'IMPORTANT: The order is currently below the required minimum. ' ||
                'Politely inform the customer of the remaining amount needed and suggest adding ' ||
                'specific eligible items (like popular drinks, desserts or sides) from the available offers to meet the minimum.'
            -- If discounts are applied
            WHEN jsonb_array_length(v_applied_discounts) > 0 THEN
                'Confirm the applied discounts and total savings with the customer. ' ||
                'If there are other available offers (e.g., Happy Hour on drinks), briefly suggest adding matching items to maximize savings. ' ||
                'If the user asks about other days or times, refer to all_offers_schedule.'
            -- Default available offers
            ELSE
                'Present the active promotions and available discounts clearly to the customer. ' ||
                'Recommend specific items that qualify for these deals (e.g. suggesting drinks during Happy Hour). ' ||
                'If the customer asks about deals on other days (e.g., when ramen is cheapest), look at all_offers_schedule to explain.'
        END
    );
END;
$$;

