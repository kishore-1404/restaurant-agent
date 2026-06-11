# core/pre_dispatch.py
"""
Pre-dispatch layer: fires tool calls BEFORE the LLM runs.

The flow:
  1. User message arrives
  2. Embed the message (Gemini embedding API or local)
  3. Call dispatch_intent() — pgvector similarity search
  4. For each matched intent: call the corresponding tool
  5. Inject results into SessionContext.predispatch_facts
  6. LLM runs with facts already in context
"""

from __future__ import annotations
import asyncio
import logging
import re
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

_PII_PATTERNS = [
    (r'\b\d{10,}\b',           '[PHONE]'),
    (r'[\w.]+@[\w.]+\.\w{2,}', '[EMAIL]'),
    (r'\b\d{4}[\s-]?\d{4}[\s-]?\d{4}[\s-]?\d{4}\b', '[CARD]'),
]

def sanitise_for_embedding(text: str) -> str:
    for pattern, replacement in _PII_PATTERNS:
        text = re.sub(pattern, replacement, text)
    return text[:512]  # cap length — embeddings beyond ~512 chars add little value


async def run_pre_dispatch(
    user_message:  str,
    session_ctx,                # SessionContext
    db:            AsyncSession,
) -> dict[str, Any]:
    """
    Returns a dict of {tool_name: tool_result} for all intents that fired.
    Empty dict if no intents matched above threshold.
    """
    # Step 1: sanitise and embed the message
    sanitised_msg = sanitise_for_embedding(user_message)
    embedding = await _embed(sanitised_msg)
    if embedding is None:
        return {}

    # Step 2: dispatch_intent — pgvector similarity search
    result = await db.execute(
        text("""
            SELECT intent_code, tool_name, tool_params_hint,
                   is_safety_critical, similarity, example_matched
            FROM   dispatch_intent(CAST(:emb AS vector))
            ORDER  BY is_safety_critical DESC, similarity DESC
        """),
        {"emb": _vector_to_pg(embedding)},
    )
    intents = result.fetchall()

    if not intents:
        return {}

    # Emit pre-dispatch event to the global telemetry bus
    from monitoring.events import bus, Event, EK
    bus.emit(Event(
        kind=EK.PRE_DISPATCH,
        title=f"pgvector: matched {len(intents)} intent(s) for query: '{sanitised_msg}'",
        session_id=session_ctx.session_id,
        detail={
            "query": sanitised_msg,
            "intents": [
                {
                    "intent_code": i.intent_code,
                    "tool_name": i.tool_name,
                    "tool_params_hint": i.tool_params_hint,
                    "is_safety_critical": i.is_safety_critical,
                    "similarity": float(i.similarity),
                    "example_matched": i.example_matched,
                }
                for i in intents
            ]
        }
    ))

    # Step 3: fire tools for each matched intent
    predispatch_facts: dict[str, Any] = {}
    tasks = []

    for intent in intents:
        logger.info(
            f"Pre-dispatch: intent={intent.intent_code} "
            f"tool={intent.tool_name} sim={intent.similarity:.3f} "
            f"safety={intent.is_safety_critical}"
        )
        task = _call_tool(
            tool_name=intent.tool_name,
            params_hint=intent.tool_params_hint or {},
            session_ctx=session_ctx,
            db=db,
            user_message=user_message,
        )
        tasks.append((intent.tool_name, task))

    # Run tool calls in parallel (safety_audit + item_detail can fire simultaneously)
    results = await asyncio.gather(*[t for _, t in tasks], return_exceptions=True)

    for (tool_name, _), result in zip(tasks, results):
        if isinstance(result, Exception):
            logger.error(f"Pre-dispatch tool {tool_name} failed: {result}")
            continue
        if result:
            predispatch_facts[tool_name] = result

    return predispatch_facts


async def _call_tool(
    tool_name:   str,
    params_hint: dict,
    session_ctx,
    db:          AsyncSession,
    user_message: str,
) -> dict | None:
    """Route intent to the correct tool function."""
    from services.intelligence_service import IntelligenceService as IS

    profile    = session_ctx.customer_profile
    allergens  = profile.allergens if profile else []
    dietary    = profile.dietary_restrictions if profile else []
    rid        = session_ctx.restaurant.id

    if tool_name == "safety_audit":
        strict = profile.strict_allergens if profile else []
        return await IS.safety_audit(db, allergens, dietary, rid, strict=strict)

    elif tool_name == "get_item_detail":
        # Extract item name from the message using fuzzy match on menu
        item_name = await IS.extract_item_name(db, user_message, rid)
        if item_name:
            return await IS.get_item_detail(db, item_name, rid)

    elif tool_name == "get_last_order":
        if session_ctx.customer_profile and session_ctx.customer_profile.phone:
            return await IS.get_last_order(
                db, session_ctx.customer_profile.phone, rid
            )

    elif tool_name == "explore_semantic":
        embedding = await _embed(user_message)
        if embedding:
            return await IS.explore_semantic(
                db, embedding, rid, allergens=allergens, dietary=dietary
            )

    elif tool_name == "get_active_offers":
        from sqlalchemy import select
        from db.models import Order
        res = await db.execute(
            select(Order.id).where(
                Order.session_id == session_ctx.session_id,
                Order.restaurant_id == rid
            )
        )
        order_id = res.scalar_one_or_none()
        if order_id:
            return await IS.get_active_offers(db, rid, order_id)

    return None


async def _embed(text: str) -> list[float] | None:
    """
    Generate embedding for a text string.
    Uses the configured embedding provider.
    Returns None on failure (pre-dispatch degrades gracefully).
    """
    from core.embeddings import generate_embedding
    try:
        return await generate_embedding(text)
    except Exception as e:
        logger.warning(f"Embedding failed (pre-dispatch will be skipped): {e}")
        return None


def _vector_to_pg(vec: list[float]) -> str:
    """Format a Python list as a PostgreSQL vector literal."""
    return "[" + ",".join(str(v) for v in vec) + "]"
