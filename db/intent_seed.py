# db/intent_seed.py
"""
Intent definitions for pgvector pre-dispatch.
Each entry is an example query for a known intent type.
Multiple entries per intent = better semantic coverage.
Embeddings are generated separately by db/embedding_gen.py.

Adding new intents: INSERT rows here + run embedding_gen.py. No code changes.
Adjusting sensitivity: UPDATE similarity_threshold for the intent. No code changes.
"""

INTENT_DEFINITIONS = [
    # ── ALLERGEN CHECK — safety_critical, lower threshold ─────────────────
    # These MUST fire on any reasonable indication of a safety concern
    ("allergen_check", "does this have peanuts",                      "safety_audit", True,  0.72),
    ("allergen_check", "I am allergic to nuts",                       "safety_audit", True,  0.72),
    ("allergen_check", "is this gluten free",                         "safety_audit", True,  0.72),
    ("allergen_check", "what can I eat with a dairy allergy",         "safety_audit", True,  0.72),
    ("allergen_check", "my wife is lactose intolerant",               "safety_audit", True,  0.72),
    ("allergen_check", "I have celiac disease",                       "safety_audit", True,  0.72),
    ("allergen_check", "is it safe for someone with a shellfish allergy", "safety_audit", True, 0.72),
    ("allergen_check", "what is safe for me to eat",                  "safety_audit", True,  0.72),
    ("allergen_check", "I cannot eat gluten",                         "safety_audit", True,  0.72),
    ("allergen_check", "are there any nuts in this",                  "safety_audit", True,  0.72),
    ("allergen_check", "vegan options please",                        "safety_audit", True,  0.72),
    ("allergen_check", "I am vegetarian what can I have",             "safety_audit", True,  0.72),

    # ── ITEM DETAIL — specific item questions ─────────────────────────────
    ("item_detail", "what is in the carbonara",                "get_item_detail", False, 0.80),
    ("item_detail", "what are the ingredients",                "get_item_detail", False, 0.80),
    ("item_detail", "tell me about the BBQ ribs",              "get_item_detail", False, 0.80),
    ("item_detail", "how spicy is the diavola",                "get_item_detail", False, 0.80),
    ("item_detail", "what does the burger come with",          "get_item_detail", False, 0.80),
    ("item_detail", "how many calories in the milkshake",      "get_item_detail", False, 0.80),
    ("item_detail", "what is the tonkotsu ramen made of",      "get_item_detail", False, 0.80),
    ("item_detail", "is the salmon fresh",                     "get_item_detail", False, 0.80),
    ("item_detail", "does the pizza have cheese",              "get_item_detail", False, 0.80),

    # ── SEMANTIC SEARCH — vague or descriptive intent ─────────────────────
    ("semantic_search", "I want something light",              "explore_semantic", False, 0.80),
    ("semantic_search", "something comforting and warm",       "explore_semantic", False, 0.80),
    ("semantic_search", "give me something fresh",             "explore_semantic", False, 0.80),
    ("semantic_search", "I feel like something spicy",         "explore_semantic", False, 0.80),
    ("semantic_search", "what is filling and hearty",          "explore_semantic", False, 0.80),
    ("semantic_search", "I want something healthy",            "explore_semantic", False, 0.80),
    ("semantic_search", "something adventurous I haven't had", "explore_semantic", False, 0.80),
    ("semantic_search", "I'm not sure what I want",            "explore_semantic", False, 0.80),

    # ── RECOMMENDATION — popularity or personalisation ────────────────────
    ("recommendation", "what do most people order",            "get_recommendations", False, 0.82),
    ("recommendation", "what would you recommend",             "get_recommendations", False, 0.82),
    ("recommendation", "what is the best thing here",         "get_recommendations", False, 0.82),
    ("recommendation", "what is popular",                     "get_recommendations", False, 0.82),
    ("recommendation", "what should I get",                   "get_recommendations", False, 0.82),
    ("recommendation", "surprise me",                         "get_recommendations", False, 0.82),

    # ── ORDER HISTORY — returning customer recall ─────────────────────────
    ("order_history", "what did I have last time",             "get_last_order", False, 0.82),
    ("order_history", "same as usual please",                  "get_last_order", False, 0.82),
    ("order_history", "the same as my last order",             "get_last_order", False, 0.82),
    ("order_history", "my usual order",                        "get_last_order", False, 0.82),
    ("order_history", "I'll have what I always get",           "get_last_order", False, 0.82),

    # ── PAIRINGS — what goes with something ───────────────────────────────
    ("pairings", "what goes well with the ribs",               "get_pairings", False, 0.82),
    ("pairings", "what should I have as a side",               "get_pairings", False, 0.82),
    ("pairings", "what drink pairs with this",                 "get_pairings", False, 0.82),
    ("pairings", "what else goes with my order",               "get_pairings", False, 0.82),

    # ── COMPARISON ────────────────────────────────────────────────────────
    ("comparison", "what is the difference between",           "compare_items", False, 0.82),
    ("comparison", "which ramen is more filling",              "compare_items", False, 0.82),
    ("comparison", "which is better the burger or the melt",   "compare_items", False, 0.82),
    ("comparison", "tonkotsu versus shoyu",                    "compare_items", False, 0.82),

    # ── MEAL BUILDING ─────────────────────────────────────────────────────
    ("meal_build", "can you build me a complete meal",         "suggest_complete_meal", False, 0.82),
    ("meal_build", "suggest a starter main and dessert",       "suggest_complete_meal", False, 0.82),
    ("meal_build", "I have a budget of forty dollars",         "suggest_complete_meal", False, 0.82),
    ("meal_build", "what would make a good dinner for two",    "suggest_complete_meal", False, 0.82),

    # ── RESTAURANT INFO ───────────────────────────────────────────────────
    ("restaurant_info", "what are your opening hours",         "get_restaurant_info", False, 0.82),
    ("restaurant_info", "do you accept card payments",         "get_restaurant_info", False, 0.82),
    ("restaurant_info", "is there delivery available",         "get_restaurant_info", False, 0.82),
    ("restaurant_info", "do you do takeaway",                  "get_restaurant_info", False, 0.82),
    ("restaurant_info", "where are you located",               "get_restaurant_info", False, 0.82),

    # ── FUZZY DESCRIPTION ─────────────────────────────────────────────────
    ("fuzzy_match", "that pasta with the creamy sauce",        "find_by_description", False, 0.78),
    ("fuzzy_match", "the thing with the green stuff on top",   "find_by_description", False, 0.78),
    ("fuzzy_match", "the spicy noodle soup",                   "find_by_description", False, 0.78),
    ("fuzzy_match", "that fish dish you have",                 "find_by_description", False, 0.78),

    # ── OFFERS AND DISCOUNTS ──────────────────────────────────────────────
    ("offers_and_discounts", "what deals do you have",           "get_active_offers", False, 0.80),
    ("offers_and_discounts", "are there any discounts today",    "get_active_offers", False, 0.80),
    ("offers_and_discounts", "what promotions are active",       "get_active_offers", False, 0.80),
    ("offers_and_discounts", "do I qualify for any discount",    "get_active_offers", False, 0.80),
    ("offers_and_discounts", "tell me about current offers",     "get_active_offers", False, 0.80),
    ("offers_and_discounts", "discounts running on other days",  "get_active_offers", False, 0.80),
    ("offers_and_discounts", "what is the best time to buy ramen", "get_active_offers", False, 0.80),
]


async def seed_intent_definitions():
    """Insert intent definitions. Clears table first to ensure updates are seeded."""
    from db.base import AsyncSessionFactory
    from sqlalchemy import text

    async with AsyncSessionFactory() as db:
        await db.execute(text("TRUNCATE TABLE intent_definitions CASCADE"))
        await db.commit()

        for intent_code, example_query, tool_name, is_safety_critical, threshold in INTENT_DEFINITIONS:
            await db.execute(
                text("""
                    INSERT INTO intent_definitions
                        (intent_code, example_query, tool_name, is_safety_critical, similarity_threshold)
                    VALUES (:code, :query, :tool, :safety, :threshold)
                """),
                {
                    "code":      intent_code,
                    "query":     example_query,
                    "tool":      tool_name,
                    "safety":    is_safety_critical,
                    "threshold": threshold,
                }
            )

        await db.commit()
