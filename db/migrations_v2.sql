-- ─────────────────────────────────────────────────────────────────────────────
-- EXTEND menu_items
-- ─────────────────────────────────────────────────────────────────────────────
ALTER TABLE menu_items ADD COLUMN IF NOT EXISTS ingredients       TEXT[]   DEFAULT '{}';
ALTER TABLE menu_items ADD COLUMN IF NOT EXISTS allergens         TEXT[]   DEFAULT '{}';
ALTER TABLE menu_items ADD COLUMN IF NOT EXISTS nutrition_info    JSONB    DEFAULT '{}';
ALTER TABLE menu_items ADD COLUMN IF NOT EXISTS allowed_modifications JSONB DEFAULT '{}';
ALTER TABLE menu_items ADD COLUMN IF NOT EXISTS available_during  TSTZRANGE;  -- NULL = always available
ALTER TABLE menu_items ADD COLUMN IF NOT EXISTS available_days    INT[]    DEFAULT '{0,1,2,3,4,5,6}'; -- 0=Sun..6=Sat
ALTER TABLE menu_items ADD COLUMN IF NOT EXISTS translations      JSONB    DEFAULT '{}';
ALTER TABLE menu_items ADD COLUMN IF NOT EXISTS available_quantity INT     DEFAULT NULL; -- NULL = unlimited
ALTER TABLE menu_items ADD COLUMN IF NOT EXISTS display_order     INT     DEFAULT 0;

-- GIN indexes for array operations
CREATE INDEX IF NOT EXISTS idx_items_allergens    ON menu_items USING GIN(allergens);
CREATE INDEX IF NOT EXISTS idx_items_ingredients  ON menu_items USING GIN(ingredients);
CREATE INDEX IF NOT EXISTS idx_items_available    ON menu_items USING GIN(available_days);

-- Generated columns for common allergen flags
ALTER TABLE menu_items ADD COLUMN IF NOT EXISTS has_gluten  BOOLEAN
  GENERATED ALWAYS AS ('gluten' = ANY(allergens)) STORED;
ALTER TABLE menu_items ADD COLUMN IF NOT EXISTS has_dairy   BOOLEAN
  GENERATED ALWAYS AS ('dairy' = ANY(allergens)) STORED;
ALTER TABLE menu_items ADD COLUMN IF NOT EXISTS has_nuts    BOOLEAN
  GENERATED ALWAYS AS ('peanuts' = ANY(allergens) OR 'tree_nuts' = ANY(allergens)) STORED;
ALTER TABLE menu_items ADD COLUMN IF NOT EXISTS has_shellfish BOOLEAN
  GENERATED ALWAYS AS ('shellfish' = ANY(allergens)) STORED;

-- Trigger: decrement stock and auto-disable when depleted
CREATE OR REPLACE FUNCTION check_item_quantity()
RETURNS TRIGGER AS $$
BEGIN
    IF NEW.available_quantity IS NOT NULL AND NEW.available_quantity <= 0 THEN
        NEW.is_available := false;
        PERFORM pg_notify('menu_updates',
            json_build_object('type','item_sold_out','item_id',NEW.id,'restaurant_id',NEW.restaurant_id)::text
        );
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_item_quantity ON menu_items;
CREATE TRIGGER trg_item_quantity
BEFORE UPDATE OF available_quantity ON menu_items
FOR EACH ROW EXECUTE FUNCTION check_item_quantity();


-- ─────────────────────────────────────────────────────────────────────────────
-- NEW TABLE: price_rules
-- ─────────────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS price_rules (
    id              SERIAL PRIMARY KEY,
    restaurant_id   INT NOT NULL REFERENCES restaurants(id) ON DELETE CASCADE,
    name            VARCHAR(200) NOT NULL,
    label           TEXT NOT NULL,           -- shown to customer: "Happy Hour"
    description     TEXT,                    -- "20% off all drinks Mon–Fri 3–6pm"
    rule_type       VARCHAR(50) NOT NULL,    -- 'percentage_off' | 'fixed_off' | 'fixed_price'
    value           NUMERIC(10,2) NOT NULL,  -- discount amount or new price
    applies_to      VARCHAR(50) NOT NULL,    -- 'category' | 'item' | 'order' | 'all'
    applies_to_ids  INT[] DEFAULT '{}',      -- category or item IDs this rule covers
    valid_days      INT[] DEFAULT '{0,1,2,3,4,5,6}',  -- days of week active
    valid_from      TIME,                    -- daily start time (NULL = all day)
    valid_until     TIME,                    -- daily end time (NULL = all day)
    valid_date_from DATE,                    -- calendar start (NULL = always)
    valid_date_until DATE,                   -- calendar end (NULL = always)
    priority        INT DEFAULT 0,           -- higher = applied first
    is_active       BOOLEAN DEFAULT true,
    created_at      TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_price_rules_restaurant ON price_rules(restaurant_id, is_active);
CREATE INDEX IF NOT EXISTS idx_price_rules_days       ON price_rules USING GIN(valid_days);

-- View: currently active price rules
CREATE OR REPLACE VIEW active_price_rules AS
SELECT * FROM price_rules
WHERE  is_active = true
  AND  (valid_date_from  IS NULL OR valid_date_from  <= CURRENT_DATE)
  AND  (valid_date_until IS NULL OR valid_date_until >= CURRENT_DATE)
  AND  EXTRACT(dow FROM NOW())::int = ANY(valid_days)
  AND  (valid_from  IS NULL OR valid_from  <= CURRENT_TIME)
  AND  (valid_until IS NULL OR valid_until >= CURRENT_TIME);


-- ─────────────────────────────────────────────────────────────────────────────
-- NEW TABLE: order_rules
-- ─────────────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS order_rules (
    id              SERIAL PRIMARY KEY,
    restaurant_id   INT NOT NULL REFERENCES restaurants(id) ON DELETE CASCADE,
    rule_type       VARCHAR(50) NOT NULL,
    value           NUMERIC(10,2),           -- numeric limit
    value_text      TEXT,                    -- for text-based rules
    applies_to_ids  INT[] DEFAULT '{}',      -- items or categories this applies to
    description     TEXT NOT NULL,           -- human-readable for agent context
    error_message   TEXT,                    -- what agent says when rule is hit
    is_active       BOOLEAN DEFAULT true
);

CREATE INDEX IF NOT EXISTS idx_order_rules_restaurant ON order_rules(restaurant_id, is_active);


-- ─────────────────────────────────────────────────────────────────────────────
-- NEW TABLE: customer_profiles
-- ─────────────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS customer_profiles (
    id                    SERIAL PRIMARY KEY,
    restaurant_id         INT REFERENCES restaurants(id) ON DELETE CASCADE,
    phone                 VARCHAR(30) UNIQUE,
    email                 VARCHAR(200) UNIQUE,
    name                  VARCHAR(200),
    language_code         VARCHAR(10) DEFAULT 'en',
    dietary_restrictions  TEXT[] DEFAULT '{}',
    allergens             TEXT[] DEFAULT '{}',
    strict_allergens      TEXT[] DEFAULT '{}',
    preferences           JSONB DEFAULT '{}',
    total_orders          INT DEFAULT 0,
    total_spend           NUMERIC(10,2) DEFAULT 0,
    loyalty_points        INT DEFAULT 0,
    created_at            TIMESTAMPTZ DEFAULT NOW(),
    last_seen_at          TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_profiles_phone     ON customer_profiles(phone) WHERE phone IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_profiles_allergens ON customer_profiles USING GIN(allergens);
CREATE INDEX IF NOT EXISTS idx_profiles_dietary   ON customer_profiles USING GIN(dietary_restrictions);

-- Trigger: update customer on order completion
CREATE OR REPLACE FUNCTION update_customer_on_order()
RETURNS TRIGGER AS $$
BEGIN
    INSERT INTO customer_profiles (phone, total_orders, total_spend, last_seen_at, restaurant_id)
    VALUES (NEW.customer_phone, 1, NEW.total, NOW(), NEW.restaurant_id)
    ON CONFLICT (phone) DO UPDATE
    SET    total_orders = customer_profiles.total_orders + 1,
           total_spend  = customer_profiles.total_spend  + NEW.total,
           last_seen_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_customer_order ON orders;
CREATE TRIGGER trg_customer_order
AFTER UPDATE OF status ON orders
FOR EACH ROW
WHEN (NEW.status = 'completed' AND OLD.status != 'completed' AND NEW.customer_phone IS NOT NULL)
EXECUTE FUNCTION update_customer_on_order();


-- ─────────────────────────────────────────────────────────────────────────────
-- NEW TABLE: item_affinity
-- ─────────────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS item_affinity (
    item_a_id       INT REFERENCES menu_items(id) ON DELETE CASCADE,
    item_b_id       INT REFERENCES menu_items(id) ON DELETE CASCADE,
    restaurant_id   INT NOT NULL,
    co_occurrence   INT DEFAULT 0,
    lift_score      NUMERIC(6,3),
    last_computed   TIMESTAMPTZ DEFAULT NOW(),
    PRIMARY KEY (item_a_id, item_b_id)
);

CREATE INDEX IF NOT EXISTS idx_affinity_item_a ON item_affinity(item_a_id, lift_score DESC);

-- Materialized view: top pairing per item
CREATE MATERIALIZED VIEW IF NOT EXISTS top_pairings AS
SELECT DISTINCT ON (item_a_id)
    item_a_id,
    item_b_id,
    m.name         AS paired_item_name,
    m.price        AS paired_item_price,
    co_occurrence,
    lift_score
FROM   item_affinity ia
JOIN   menu_items m ON m.id = ia.item_b_id AND m.is_available = true
ORDER  BY item_a_id, lift_score DESC;

CREATE UNIQUE INDEX IF NOT EXISTS top_pairings_item_a_idx ON top_pairings(item_a_id);


-- ─────────────────────────────────────────────────────────────────────────────
-- EXTEND orders AND order_items
-- ─────────────────────────────────────────────────────────────────────────────
ALTER TABLE orders ADD COLUMN IF NOT EXISTS customer_phone   VARCHAR(30);
ALTER TABLE orders ADD COLUMN IF NOT EXISTS language_code    VARCHAR(10) DEFAULT 'en';
ALTER TABLE orders ADD COLUMN IF NOT EXISTS discount_total   NUMERIC(10,2) DEFAULT 0;
ALTER TABLE orders ADD COLUMN IF NOT EXISTS promotions_applied JSONB DEFAULT '[]';

CREATE INDEX IF NOT EXISTS idx_orders_customer_phone ON orders(customer_phone) WHERE customer_phone IS NOT NULL;

ALTER TABLE order_items ADD COLUMN IF NOT EXISTS modifications_applied  JSONB DEFAULT '{}';
ALTER TABLE order_items ADD COLUMN IF NOT EXISTS allergen_warnings      TEXT[] DEFAULT '{}';
ALTER TABLE order_items ADD COLUMN IF NOT EXISTS original_price         NUMERIC(10,2);
ALTER TABLE order_items ADD COLUMN IF NOT EXISTS added_by               TEXT;

-- Store original price on insert (immutable)
CREATE OR REPLACE FUNCTION snapshot_original_price()
RETURNS TRIGGER AS $$
BEGIN
    IF NEW.original_price IS NULL THEN
        NEW.original_price := NEW.price_snapshot;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_snapshot_original_price ON order_items;
CREATE TRIGGER trg_snapshot_original_price
BEFORE INSERT ON order_items
FOR EACH ROW EXECUTE FUNCTION snapshot_original_price();


-- ─────────────────────────────────────────────────────────────────────────────
-- ENABLE ROW LEVEL SECURITY FOR NEW TABLES
-- ─────────────────────────────────────────────────────────────────────────────
ALTER TABLE price_rules ENABLE ROW LEVEL SECURITY;
ALTER TABLE order_rules ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS tenant_isolation ON price_rules;
CREATE POLICY tenant_isolation ON price_rules
    USING (restaurant_id = current_setting('app.restaurant_id', true)::int);

DROP POLICY IF EXISTS tenant_isolation ON order_rules;
CREATE POLICY tenant_isolation ON order_rules
    USING (restaurant_id = current_setting('app.restaurant_id', true)::int);

DROP POLICY IF EXISTS admin_bypass ON price_rules;
CREATE POLICY admin_bypass ON price_rules TO postgres USING (true);

DROP POLICY IF EXISTS admin_bypass ON order_rules;
CREATE POLICY admin_bypass ON order_rules TO postgres USING (true);
