from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from db.models import MenuItem, MenuCategory
from redis_client import cache, CacheKeys
from config import settings


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

        # 2. Cache miss — query DB (RLS already enforces restaurant scoping)
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
            })

        # 4. Store in Redis
        await cache.set_json(cache_key, menu, ttl=settings.menu_cache_ttl_seconds)
        return menu

    @staticmethod
    async def search_items(
        db: AsyncSession,
        restaurant_id: int,
        query: str,
        limit: int = 5
    ) -> list[dict]:
        """
        Full-text search + trigram fuzzy fallback.
        e.g. "something spicy" or "burgr" (typo) both work.
        """
        # Full-text search first
        fts_result = await db.execute(
            text("""
                SELECT id, name, price, description
                FROM   menu_items
                WHERE  restaurant_id = :rid
                  AND  is_available  = true
                  AND  search_vector @@ plainto_tsquery('english', :q)
                ORDER BY ts_rank(search_vector, plainto_tsquery('english', :q)) DESC
                LIMIT  :lim
            """),
            {"rid": restaurant_id, "q": query, "lim": limit}
        )
        results = fts_result.fetchall()

        # If FTS finds nothing, try fuzzy trigram match
        if not results:
            fuzzy_result = await db.execute(
                text("""
                    SELECT id, name, price, description
                    FROM   menu_items
                    WHERE  restaurant_id = :rid
                      AND  is_available  = true
                      AND  similarity(name, :q) > 0.2
                    ORDER BY similarity(name, :q) DESC
                    LIMIT  :lim
                """),
                {"rid": restaurant_id, "q": query, "lim": limit}
            )
            results = fuzzy_result.fetchall()

        return [
            {"id": r.id, "name": r.name, "price": float(r.price), "description": r.description}
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
