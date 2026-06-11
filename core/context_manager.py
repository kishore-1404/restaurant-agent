# core/context_manager.py
"""
Dynamic context budget management.

Trigger condition: tokens_used > 15,000 OR turns > 30
On trigger:
  1. Summarise conversation (LLM call)
  2. Store summary in Redis (key: session:{session_id}:summary)
  3. Truncate message history to last 4 messages
  4. Cart state is ALWAYS from PostgreSQL — safe to truncate history

The cart is the source of truth. History is only conversational context.
"""

from __future__ import annotations
import logging
from typing import Any
from langchain_core.messages import SystemMessage, HumanMessage, RemoveMessage

logger = logging.getLogger(__name__)

# ── Thresholds ────────────────────────────────────────────────────────────────
TOKEN_LIMIT  = 15_000   # trigger summary at this token count
TURN_LIMIT   = 60       # or after this many turns — whichever comes first
KEEP_RECENT  = 4        # messages to keep after truncation

# Rough token estimation (4 chars ≈ 1 token)
def estimate_tokens(messages: list[Any]) -> int:
    total = 0
    for m in messages:
        content = getattr(m, "content", "")
        total += len(str(content)) // 4
    return total


async def should_summarise(messages: list[Any]) -> bool:
    """Returns True if the context manager should run."""
    if len(messages) >= TURN_LIMIT:
        return True
    if estimate_tokens(messages) >= TOKEN_LIMIT:
        return True
    return False


async def summarise_and_prune(
    messages:     list[Any],
    session_id:   str,
    llm_client,              # the active LLM provider (LangChain ChatModel)
    redis_cache,
) -> tuple[list[Any], list[Any]]:
    """
    Summarise the conversation and return (messages_update, pruned_messages).
    `messages_update` contains RemoveMessage actions + new pruned list.
    `pruned_messages` contains just the new list to be used locally in the node.
    """
    if not messages:
        return [], []

    # Build a minimal summary prompt
    history_text = ""
    for m in messages[:-KEEP_RECENT]:
        role = getattr(m, "type", "user").upper()
        content = getattr(m, "content", "")
        history_text += f"{role}: {str(content)[:200]}\n"

    summary_prompt = (
        "Summarise this ordering conversation in 3-4 sentences. "
        "Include: what was discussed, any dietary preferences or restrictions mentioned, "
        "any decisions made. Be factual and brief.\n\n"
        + history_text
    )

    try:
        # Invoke LLM client
        summary = await llm_client.ainvoke([
            HumanMessage(content=summary_prompt)
        ])
        summary_text = summary.content if hasattr(summary, "content") else str(summary)
    except Exception as e:
        logger.warning(f"Summary generation failed: {e}")
        summary_text = "(Conversation summary unavailable)"

    # Store in Redis
    if redis_cache:
        try:
            await redis_cache.set_json(
                f"session:{session_id}:summary",
                {"summary": summary_text, "turn_count": len(messages)},
                ttl=3600,
            )
        except Exception as e:
            logger.warning(f"Failed to store summary in Redis: {e}")

    # Create RemoveMessage actions for all messages that have IDs
    delete_actions = [RemoveMessage(id=m.id) for m in messages if hasattr(m, "id") and m.id]

    summary_msg = SystemMessage(
        content=f"[Earlier conversation summary] {summary_text}"
    )

    # Keep only the last KEEP_RECENT messages
    kept_messages = messages[-KEEP_RECENT:]
    pruned_messages = [summary_msg] + kept_messages
    messages_update = delete_actions + pruned_messages

    # Emit context pruning event
    from monitoring.events import bus, Event, EK
    bus.emit(Event(
        kind=EK.CONTEXT,
        title=f"Context Pruned: {len(messages)} → {len(pruned_messages)} messages",
        session_id=session_id,
        detail={
            "initial_turns": len(messages),
            "initial_tokens_est": estimate_tokens(messages),
            "pruned_turns": len(pruned_messages),
            "pruned_tokens_est": estimate_tokens(pruned_messages),
            "summary_generated": summary_text,
        }
    ))

    logger.info(
        f"Context pruned: {len(messages)} → {len(pruned_messages)} messages "
        f"(estimated tokens: {estimate_tokens(messages)} → {estimate_tokens(pruned_messages)})"
    )
    return messages_update, pruned_messages
