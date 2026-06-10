from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from db.models import MenuItem, MenuCategory
from redis_client import cache, CacheKeys
from config import settings
from datetime import datetime


class MenuService:

    @staticmethod
    async def get_menu(
        db: AsyncSession,
        restaurant_id: int,
        use_cache: bool = True
    ) -> dict:
        """
        Fetch full menu for a restaurant.
        Cache-aside pattern: Redis first, DB fallback.
        """
        cache_key = CacheKeys.menu(restaurant_id)

        # 1. Try Redis cache
        if use_cache:
            cached = await cache.get_json(cache_key)
            if cached:
                return cached

        # 2. Cache miss — query DB
        result = await db.execute(
            select(MenuItem)
            .options(selectinload(MenuItem.category))
            .join(MenuCategory, MenuItem.category_id == MenuCategory.id, isouter=True)
            .where(
                MenuItem.restaurant_id == restaurant_id,
                MenuItem.is_available == True
            )
            .order_by(MenuCategory.display_order, MenuItem.name)
        )
        items = result.scalars().all()

        # 3. Structure menu by category
        menu = {}
        for item in items:
            cat = item.category.name if item.category else "Other"
            if cat not in menu:
                menu[cat] = []
            menu[cat].append({
                "id": item.id,
                "name": item.name,
                "description": item.description,
                "price": float(item.price),
                "tags": item.tags,
                "modifiers": item.modifiers,
                "ingredients": item.ingredients,
                "allergens": item.allergens,
                "nutrition_info": item.nutrition_info,
                "allowed_modifications": item.allowed_modifications,
                "translations": item.translations,
                "available_days": item.available_days,
                "available_during": item.available_during,
                "category_id": item.category_id,
            })

        # 4. Store in Redis
        await cache.set_json(cache_key, menu, ttl=settings.menu_cache_ttl_seconds)
        return menu

    @staticmethod
    async def get_contextual_menu(
        db: AsyncSession, restaurant_id: int, at: datetime
    ) -> dict:
        """
        Returns only items available at the given time.
        Uses PostgreSQL range containment: available_during @> now()
        """
        day_of_week = int(at.strftime('%w'))  # 0=Sun..6=Sat
        current_time = at.time()

        result = await db.execute(
            text("""
                SELECT
                    m.*,
                    c.name AS category_name,
                    c.display_order AS cat_order
                FROM   menu_items m
                LEFT JOIN menu_categories c ON c.id = m.category_id
                WHERE  m.restaurant_id = :rid
                  AND  m.is_available  = true
                  AND  :dow = ANY(m.available_days::int[])
                  AND  (
                      m.available_during IS NULL
                      OR (lower(m.available_during)::time <= :cur_time
                          AND upper(m.available_during)::time >= :cur_time)
                  )
                ORDER BY c.display_order, m.display_order, m.name
            """),
            {"rid": restaurant_id, "dow": day_of_week, "cur_time": current_time}
        )
        return _structure_menu(result.fetchall())

    @staticmethod
    async def search_items(
        db: AsyncSession,
        restaurant_id: int,
        query: str,
        limit: int = 5,
        safe_only: bool = False,
        customer_allergens: list[str] = None
    ) -> list[dict]:
        """
        Full-text search + trigram fuzzy fallback.
        Includes optional allergen safety filtering.
        """
        allergens_to_avoid = customer_allergens if customer_allergens else []

        # Full-text search first
        sql_fts = """
            SELECT id, name, price, description, category_id, tags, allergens
            FROM   menu_items
            WHERE  restaurant_id = :rid
              AND  is_available  = true
              AND  search_vector @@ plainto_tsquery('english', :q)
        """
        if safe_only and allergens_to_avoid:
            sql_fts += " AND NOT (allergens && (:allergens)::varchar[])"
        sql_fts += " ORDER BY ts_rank(search_vector, plainto_tsquery('english', :q)) DESC LIMIT :lim"

        fts_result = await db.execute(
            text(sql_fts),
            {"rid": restaurant_id, "q": query, "lim": limit, "allergens": allergens_to_avoid}
        )
        results = fts_result.fetchall()

        # If FTS finds nothing, try fuzzy trigram match
        if not results:
            sql_fuzzy = """
                SELECT id, name, price, description, category_id, tags, allergens
                FROM   menu_items
                WHERE  restaurant_id = :rid
                  AND  is_available  = true
                  AND  similarity(name, :q) > 0.2
            """
            if safe_only and allergens_to_avoid:
                sql_fuzzy += " AND NOT (allergens && (:allergens)::varchar[])"
            sql_fuzzy += " ORDER BY similarity(name, :q) DESC LIMIT :lim"

            fuzzy_result = await db.execute(
                text(sql_fuzzy),
                {"rid": restaurant_id, "q": query, "lim": limit, "allergens": allergens_to_avoid}
            )
            results = fuzzy_result.fetchall()

        return [
            {
                "id": r.id,
                "name": r.name,
                "price": float(r.price),
                "description": r.description,
                "category_id": r.category_id,
                "tags": r.tags,
                "allergens": r.allergens
            }
            for r in results
        ]

    @staticmethod
    async def get_item_by_id(
        db: AsyncSession, item_id: int, restaurant_id: int
    ) -> MenuItem | None:
        result = await db.execute(
            select(MenuItem).where(
                MenuItem.id == item_id,
                MenuItem.restaurant_id == restaurant_id,
                MenuItem.is_available == True
            )
        )
        return result.scalar_one_or_none()

    @staticmethod
    async def invalidate_cache(restaurant_id: int):
        """Call this whenever menu is updated (price change, item added, etc.)"""
        await cache.delete(CacheKeys.menu(restaurant_id))

    @staticmethod
    def format_for_prompt(menu: dict, language_code: str = "en", customer_allergens: list[str] = None) -> str:
        lines = []
        allergens_set = set(customer_allergens) if customer_allergens else set()
        for category, items in menu.items():
            lines.append(f"\n[{category.upper()}]")
            for item in items:
                # Check if item contains any of the customer's allergens
                item_allergens = item.get("allergens", []) or []
                is_unsafe = len(set(item_allergens) & allergens_set) > 0
                warning_flag = " ⚠" if is_unsafe else ""

                trans = item.get("translations", {}).get(language_code, {}) if item.get("translations") else {}
                name  = trans.get("name", item["name"])
                desc  = trans.get("description", item.get("description", ""))

                lines.append(f"  • {name}{warning_flag} — ${item['price']:.2f}")
                if desc:
                    lines.append(f"    {desc[:60]}")
        return "\n".join(lines)


def _structure_menu(rows) -> dict:
    menu = {}
    for r in rows:
        cat = r.category_name or "Other"
        if cat not in menu:
            menu[cat] = []
        menu[cat].append({
            "id": r.id,
            "name": r.name,
            "description": r.description,
            "price": float(r.price),
            "tags": r.tags,
            "modifiers": r.modifiers,
            "ingredients": r.ingredients,
            "allergens": r.allergens,
            "nutrition_info": r.nutrition_info,
            "allowed_modifications": r.allowed_modifications,
            "translations": r.translations,
            "available_days": r.available_days,
            "available_during": r.available_during,
            "category_id": r.category_id,
        })
    return menu
