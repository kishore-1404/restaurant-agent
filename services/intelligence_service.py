# services/intelligence_service.py
"""
Thin Python wrappers around PostgreSQL intelligence functions.

Design rules:
1. These functions call PG and return the JSONB result as a dict.
2. They do NOT add reasoning, interpretation, or business logic.
3. They sanitise the response: strip any internal fields that leaked.
4. They handle database errors gracefully without masking them.
5. Tool response is passed directly to the LLM — it is already pre-reasoned.
"""

from __future__ import annotations
import json
import logging
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

# Fields that must never appear in tool results (defence in depth)
_STRIP_FIELDS = frozenset({
    "id", "restaurant_id", "category_id", "menu_item_id",
    "created_at", "updated_at", "session_id", "embedding",
    "search_vector", "order_id",
})


def _sanitise(obj: Any) -> Any:
    """Recursively strip internal fields from any nested structure."""
    if isinstance(obj, dict):
        return {k: _sanitise(v) for k, v in obj.items() if k not in _STRIP_FIELDS}
    if isinstance(obj, list):
        return [_sanitise(item) for item in obj]
    return obj


async def _call_pg_fn(db: AsyncSession, sql: str, params: dict) -> dict:
    """Execute a PG intelligence function and return sanitised JSONB."""
    try:
        result = await db.execute(text(sql), params)
        row = result.scalar_one_or_none()
        if row is None:
            return {"status": "error", "data": {}, "safety_flags": [],
                    "llm_guidance": "Internal error — no result from database."}
        data = row if isinstance(row, dict) else json.loads(row)
        return _sanitise(data)
    except Exception as e:
        logger.error(f"PG intelligence function failed: {e}")
        return {
            "status": "error",
            "data": {},
            "safety_flags": [],
            "llm_guidance": "Could not retrieve this information right now. Apologise briefly and continue."
        }


class IntelligenceService:

    @staticmethod
    async def safety_audit(
        db: AsyncSession,
        allergens: list[str],
        dietary: list[str],
        restaurant_id: int,
        strict: list[str] = None,
        session_id: str = None,
    ) -> dict:
        res = await _call_pg_fn(db, """
            SELECT safety_audit(:rid, CAST(:allergens AS text[]), CAST(:dietary AS text[]), CAST(:strict AS text[]))
        """, {
            "rid": restaurant_id,
            "allergens": allergens,
            "dietary":   dietary,
            "strict":    strict or [],
        })
        # Emit safety audit event
        from monitoring.events import bus, Event, EK
        verdict = res.get("data", {}).get("verdict", "UNKNOWN")
        unsafe_cnt = res.get("data", {}).get("unsafe_count", 0)
        mod_cnt = res.get("data", {}).get("modifiable_count", 0)
        safe_cnt = res.get("data", {}).get("safe_count", 0)
        bus.emit(Event(
            kind=EK.SAFETY,
            title=f"Safety Audit: {verdict} (Safe: {safe_cnt}, Modifiable: {mod_cnt}, Unsafe: {unsafe_cnt})",
            session_id=session_id or "",
            detail={
                "checked": {
                    "allergens": allergens,
                    "dietary": dietary,
                    "strict": strict or [],
                },
                "verdict": verdict,
                "counts": {
                    "safe": safe_cnt,
                    "modifiable": mod_cnt,
                    "unsafe": unsafe_cnt,
                },
                "safety_flags": res.get("safety_flags", []),
                "unsafe_items": res.get("data", {}).get("unsafe_items", []),
                "modifiable_items": res.get("data", {}).get("modifiable_items", []),
            }
        ))
        return res

    @staticmethod
    async def get_item_detail(
        db: AsyncSession, item_name: str, restaurant_id: int
    ) -> dict:
        return await _call_pg_fn(db, """
            SELECT get_item_detail(:rid, :name)
        """, {"rid": restaurant_id, "name": item_name})

    @staticmethod
    async def explore_semantic(
        db: AsyncSession,
        query_embedding: list[float],
        restaurant_id: int,
        allergens: list[str] = None,
        dietary: list[str] = None,
        max_price: float = None,
        max_calories: int = None,
        sort: str = "semantic",
        limit: int = 5,
        session_id: str = None,
        query_text: str = None,
    ) -> dict:
        from core.pre_dispatch import _vector_to_pg
        res = await _call_pg_fn(db, """
            SELECT explore_semantic(
                :rid, CAST(:emb AS vector), CAST(:allergens AS text[]), CAST(:dietary AS text[]),
                :max_price, :max_calories, NULL, :sort, :lim
            )
        """, {
            "rid":         restaurant_id,
            "emb":         _vector_to_pg(query_embedding),
            "allergens":   allergens or [],
            "dietary":     dietary or [],
            "max_price":   max_price,
            "max_calories": max_calories,
            "sort":        sort,
            "lim":         limit,
        })
        # Emit semantic search event
        from monitoring.events import bus, Event, EK
        results = res.get("data", {}).get("results", [])
        cnt = len(results)
        bus.emit(Event(
            kind=EK.SEMANTIC,
            title=f"Semantic Search: '{query_text or '(embedding)'}' matched {cnt} item(s)",
            session_id=session_id or "",
            detail={
                "query": query_text,
                "restaurant_id": restaurant_id,
                "filters": {
                    "allergens": allergens or [],
                    "dietary": dietary or [],
                    "max_price": max_price,
                    "max_calories": max_calories,
                },
                "sort": sort,
                "results_count": cnt,
                "results": [
                    {
                        "name": r.get("name"),
                        "price": float(r.get("price")) if r.get("price") else None,
                        "category": r.get("category"),
                        "tags": r.get("tags"),
                        "calories": r.get("calories"),
                    }
                    for r in results
                ]
            }
        ))
        return res

    @staticmethod
    async def compare_items(
        db: AsyncSession, item_a: str, item_b: str, restaurant_id: int
    ) -> dict:
        return await _call_pg_fn(db, """
            SELECT compare_items(:rid, :a, :b)
        """, {"rid": restaurant_id, "a": item_a, "b": item_b})

    @staticmethod
    async def get_recommendations(
        db: AsyncSession,
        restaurant_id: int,
        allergens: list[str] = None,
        dietary: list[str] = None,
        time_of_day: str = "day",
    ) -> dict:
        return await _call_pg_fn(db, """
            SELECT get_recommendations(:rid, CAST(:allergens AS text[]), CAST(:dietary AS text[]), :tod)
        """, {
            "rid":       restaurant_id,
            "allergens": allergens or [],
            "dietary":   dietary or [],
            "tod":       time_of_day,
        })

    @staticmethod
    async def suggest_complete_meal(
        db: AsyncSession,
        restaurant_id: int,
        budget: float,
        allergens: list[str] = None,
        dietary: list[str] = None,
        goal: str = "balanced",
    ) -> dict:
        return await _call_pg_fn(db, """
            SELECT suggest_complete_meal(:rid, :budget, CAST(:allergens AS text[]), CAST(:dietary AS text[]), :goal)
        """, {
            "rid":       restaurant_id,
            "budget":    budget,
            "allergens": allergens or [],
            "dietary":   dietary or [],
            "goal":      goal,
        })

    @staticmethod
    async def get_pairings(
        db: AsyncSession, item_name: str, restaurant_id: int, allergens: list[str] = None
    ) -> dict:
        return await _call_pg_fn(db, """
            SELECT get_pairings(:rid, :item, CAST(:allergens AS text[]))
        """, {"rid": restaurant_id, "item": item_name, "allergens": allergens or []})

    @staticmethod
    async def get_restaurant_info(
        db: AsyncSession, field: str, restaurant_id: int
    ) -> dict:
        return await _call_pg_fn(db, """
            SELECT get_restaurant_info(:rid, :field)
        """, {"rid": restaurant_id, "field": field})

    @staticmethod
    async def find_by_description(
        db: AsyncSession,
        description: str,
        restaurant_id: int,
        allergens: list[str] = None,
        embedding: list[float] = None,
        session_id: str = None,
    ) -> dict:
        from core.pre_dispatch import _vector_to_pg
        res = await _call_pg_fn(db, """
            SELECT find_by_description(:rid, :desc, CAST(:emb AS vector), CAST(:allergens AS text[]))
        """, {
            "rid":       restaurant_id,
            "desc":      description,
            "emb":       _vector_to_pg(embedding) if embedding else None,
            "allergens": allergens or [],
        })
        # Emit semantic search event
        from monitoring.events import bus, Event, EK
        matches = res.get("data", {}).get("matches", [])
        cnt = len(matches)
        bus.emit(Event(
            kind=EK.SEMANTIC,
            title=f"Find by Description: '{description}' matched {cnt} item(s)",
            session_id=session_id or "",
            detail={
                "description": description,
                "restaurant_id": restaurant_id,
                "filters": {
                    "allergens": allergens or [],
                },
                "results_count": cnt,
                "results": [
                    {
                        "name": r.get("name"),
                        "price": float(r.get("price")) if r.get("price") else None,
                        "match_method": r.get("match_method"),
                        "confidence": r.get("confidence"),
                    }
                    for r in matches
                ]
            }
        ))
        return res

    @staticmethod
    async def extract_item_name(
        db: AsyncSession, user_message: str, restaurant_id: int
    ) -> str | None:
        """
        Extract the most likely menu item name from a user message.
        Uses trigram similarity across menu item names.
        Returns the best match name, or None if no clear match.
        """
        result = await db.execute(
            text("""
                SELECT name, similarity(name, :msg) AS sim
                FROM   menu_items
                WHERE  restaurant_id = :rid
                  AND  is_available  = true
                  AND  similarity(name, :msg) > 0.30
                ORDER  BY similarity(name, :msg) DESC
                LIMIT  1
            """),
            {"rid": restaurant_id, "msg": user_message},
        )
        row = result.fetchone()
        return row.name if row else None

    @staticmethod
    async def get_last_order(
        db: AsyncSession, phone: str, restaurant_id: int
    ) -> dict:
        result = await db.execute(
            text("""
                SELECT jsonb_build_object(
                    'status', 'ok',
                    'data', jsonb_build_object(
                        'items', jsonb_agg(
                            jsonb_build_object(
                                'name',     oi.name_snapshot,
                                'price',    oi.price_snapshot,
                                'quantity', oi.quantity
                            ) ORDER BY oi.id
                        ),
                        'total',      o.total,
                        'order_date', o.created_at::date
                    ),
                    'safety_flags', '[]'
                )
                FROM orders o
                JOIN order_items oi ON oi.order_id = o.id
                WHERE o.customer_phone = :phone
                  AND o.restaurant_id  = :rid
                  AND o.status         = 'completed'
                ORDER BY o.created_at DESC
                LIMIT 1
            """),
            {"phone": phone, "rid": restaurant_id},
        )
        row = result.scalar_one_or_none()
        if not row:
            return {
                "status": "no_results",
                "data": {},
                "safety_flags": [],
            }
        return _sanitise(row if isinstance(row, dict) else json.loads(row))

    @staticmethod
    async def get_active_offers(
        db: AsyncSession, restaurant_id: int, order_id: int
    ) -> dict:
        return await _call_pg_fn(db, """
            SELECT get_active_offers(:rid, :oid)
        """, {"rid": restaurant_id, "oid": order_id})

