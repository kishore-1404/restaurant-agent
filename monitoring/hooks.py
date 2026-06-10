"""
monitoring/hooks.py

Zero-intrusion instrumentation. Drop these into the existing setup calls
and every DB query, Redis operation, and LLM/tool invocation automatically
emits a MonitorEvent to the bus.

Usage
-----
# In db/base.py — after creating `engine`:
    from monitoring.hooks import setup_db_hooks
    setup_db_hooks(engine)

# In redis_client.py — wrap the client:
    from monitoring.hooks import InstrumentedRedis
    redis = InstrumentedRedis(raw_redis_client)

# In core/graph.py — add callback to LLM:
    from monitoring.hooks import MonitorCallback
    llm = llm.with_config(callbacks=[MonitorCallback(session_id=...)])
"""

from __future__ import annotations

import time
import json
import re
from typing import Any, Sequence

from monitoring.events import bus, Event, EK


# ─────────────────────────────────────────────────────────────────────────────
# SQLALCHEMY HOOK
# ─────────────────────────────────────────────────────────────────────────────

def setup_db_hooks(engine) -> None:
    """
    Attach before/after execute listeners to a SQLAlchemy async engine.
    Works by listening on the sync engine underneath the async wrapper.

    Captures: SQL text, affected table, operation type, duration, row count.
    """
    from sqlalchemy import event as sa_event

    # For async engines, listen on the sync engine
    sync_engine = getattr(engine, "sync_engine", engine)

    @sa_event.listens_for(sync_engine, "before_cursor_execute")
    def _before(conn, cursor, statement, parameters, context, executemany):
        conn.info.setdefault("_mon_stack", []).append(time.perf_counter())

    @sa_event.listens_for(sync_engine, "after_cursor_execute")
    def _after(conn, cursor, statement, parameters, context, executemany):
        stack = conn.info.get("_mon_stack", [])
        start = stack.pop() if stack else None
        duration_ms = (time.perf_counter() - start) * 1000 if start else None

        op, table = _parse_sql(statement)
        short_sql = statement.strip()[:120].replace("\n", " ")

        # Sanitise parameters — don't log passwords or sensitive values
        safe_params = _sanitise_params(parameters)

        bus.emit(Event(
            kind=EK.DB,
            title=f"{op}  {table}",
            duration_ms=duration_ms,
            is_error=False,
            detail={
                "sql":        short_sql,
                "full_sql":   statement.strip(),
                "operation":  op,
                "table":      table,
                "params":     safe_params,
                "rowcount":   getattr(cursor, "rowcount", None),
            },
        ))


def _parse_sql(sql: str) -> tuple[str, str]:
    """Extract operation (SELECT/INSERT/…) and primary table from SQL text."""
    sql = sql.strip().upper()
    op_match = re.match(r"(SELECT|INSERT|UPDATE|DELETE|CREATE|ALTER|DROP|SET)", sql)
    op = op_match.group(1) if op_match else "QUERY"

    # Try to find table name
    table = "?"
    patterns = [
        r"FROM\s+(\w+)",
        r"INTO\s+(\w+)",
        r"UPDATE\s+(\w+)",
        r"JOIN\s+(\w+)",
    ]
    for pat in patterns:
        m = re.search(pat, sql)
        if m:
            table = m.group(1).lower()
            break

    return op, table


def _sanitise_params(params: Any) -> Any:
    """Remove anything that looks like a password or secret from logged params."""
    if not params:
        return params
    _SENSITIVE = {"password", "secret", "token", "api_key", "key"}
    if isinstance(params, dict):
        return {k: "***" if k.lower() in _SENSITIVE else v for k, v in params.items()}
    return params


# ─────────────────────────────────────────────────────────────────────────────
# REDIS INSTRUMENTATION WRAPPER
# ─────────────────────────────────────────────────────────────────────────────

class InstrumentedRedis:
    """
    Transparent wrapper around an async Redis client.
    Replace `self.client` references in RedisCache with this class.

    Every GET/SET/DEL/ZINCRBY/ZREVRANGE/EXISTS call emits a REDIS event.

    Usage:
        raw = aioredis.Redis(connection_pool=pool)
        client = InstrumentedRedis(raw, session_id_getter=lambda: current_session())
    """

    def __init__(self, client, session_id: str = ""):
        self._r = client
        self.session_id = session_id    # can be set per-operation

    # ── Core read/write operations ────────────────────────────────────────────

    async def get(self, key: str, *args, **kwargs):
        start = time.perf_counter()
        result = await self._r.get(key, *args, **kwargs)
        ms = (time.perf_counter() - start) * 1000
        hit = result is not None
        bus.emit(Event(
            kind=EK.REDIS,
            title=f"GET  {_short_key(key)}  {'HIT ✓' if hit else 'MISS ✗'}",
            duration_ms=ms,
            session_id=self.session_id,
            detail={"op": "GET", "key": key, "hit": hit,
                    "size_bytes": len(result) if result else 0},
        ))
        return result

    async def set(self, key: str, value, *args, **kwargs):
        start = time.perf_counter()
        result = await self._r.set(key, value, *args, **kwargs)
        ms = (time.perf_counter() - start) * 1000
        ttl = kwargs.get("ex") or kwargs.get("px", 0)
        ttl_str = f"  TTL:{ttl}s" if ttl else ""
        bus.emit(Event(
            kind=EK.REDIS,
            title=f"SET  {_short_key(key)}{ttl_str}",
            duration_ms=ms,
            session_id=self.session_id,
            detail={"op": "SET", "key": key, "ttl": ttl,
                    "size_bytes": len(str(value))},
        ))
        return result

    async def setex(self, key: str, seconds: int, value, *args, **kwargs):
        start = time.perf_counter()
        result = await self._r.setex(key, seconds, value, *args, **kwargs)
        ms = (time.perf_counter() - start) * 1000
        bus.emit(Event(
            kind=EK.REDIS,
            title=f"SETEX  {_short_key(key)}  TTL:{seconds}s",
            duration_ms=ms,
            session_id=self.session_id,
            detail={"op": "SETEX", "key": key, "ttl": seconds},
        ))
        return result

    async def delete(self, *keys):
        start = time.perf_counter()
        result = await self._r.delete(*keys)
        ms = (time.perf_counter() - start) * 1000
        bus.emit(Event(
            kind=EK.REDIS,
            title=f"DEL  {', '.join(_short_key(k) for k in keys)}",
            duration_ms=ms,
            session_id=self.session_id,
            detail={"op": "DEL", "keys": list(keys), "deleted": result},
        ))
        return result

    async def zincrby(self, name: str, amount, value):
        start = time.perf_counter()
        result = await self._r.zincrby(name, amount, value)
        ms = (time.perf_counter() - start) * 1000
        bus.emit(Event(
            kind=EK.REDIS,
            title=f"ZINCRBY  {_short_key(name)}  +{amount}  [{value}]",
            duration_ms=ms,
            session_id=self.session_id,
            detail={"op": "ZINCRBY", "key": name, "member": str(value), "by": amount},
        ))
        return result

    async def zrevrange(self, name: str, start: int, end: int, **kwargs):
        t0 = time.perf_counter()
        result = await self._r.zrevrange(name, start, end, **kwargs)
        ms = (time.perf_counter() - t0) * 1000
        bus.emit(Event(
            kind=EK.REDIS,
            title=f"ZREVRANGE  {_short_key(name)}  [{start}:{end}]  → {len(result)} items",
            duration_ms=ms,
            session_id=self.session_id,
            detail={"op": "ZREVRANGE", "key": name, "count": len(result)},
        ))
        return result

    # Distributed lock primitives
    async def set_nx(self, key: str, value, px: int = None):
        start = time.perf_counter()
        result = await self._r.set(key, value, nx=True, px=px)
        ms = (time.perf_counter() - start) * 1000
        bus.emit(Event(
            kind=EK.REDIS,
            title=f"LOCK  {_short_key(key)}  {'acquired ✓' if result else 'contested ✗'}",
            duration_ms=ms,
            session_id=self.session_id,
            detail={"op": "LOCK", "key": key, "acquired": result is True},
        ))
        return result

    # Passthrough for everything else
    def __getattr__(self, name: str):
        return getattr(self._r, name)


def _short_key(key: str) -> str:
    """Truncate long Redis keys for display."""
    return key if len(key) <= 35 else key[:32] + "…"


from langchain_core.callbacks import BaseCallbackHandler


class MonitorCallback(BaseCallbackHandler):
    """
    LangChain BaseCallbackHandler that emits MonitorEvents for LLM calls,
    tool invocations, and chain steps.

    Usage:
        from monitoring.hooks import MonitorCallback

        # Per-session callback (pass to graph.ainvoke config):
        config = {
            "configurable": {"thread_id": session_id},
            "callbacks": [MonitorCallback(session_id=session_id)],
        }
        result = await graph.ainvoke(inputs, config=config)
    """

    def __init__(self, session_id: str = ""):
        self.session_id = session_id
        self._llm_start: dict[str, float] = {}
        self._tool_start: dict[str, float] = {}

    # ── LLM ──────────────────────────────────────────────────────────────────

    def on_llm_start(
        self, serialized: dict | None, prompts: list[str], *, run_id=None, **kwargs
    ) -> None:
        rid = str(run_id)
        self._llm_start[rid] = time.perf_counter()
        model = "unknown-model"
        
        # 1. Try to extract from serialized kwargs
        if serialized and isinstance(serialized, dict):
            kwargs_dict = serialized.get("kwargs")
            if isinstance(kwargs_dict, dict):
                model = kwargs_dict.get("model") or kwargs_dict.get("model_name") or "unknown-model"
                
        # 2. Try to extract from invocation_params in kwargs
        if model == "unknown-model":
            invocation_params = kwargs.get("invocation_params")
            if invocation_params and isinstance(invocation_params, dict):
                model = invocation_params.get("model_name") or invocation_params.get("model") or "unknown-model"
                
        # 3. Fallback to settings
        if model == "unknown-model":
            try:
                from config import settings
                provider = settings.llm_provider.lower()
                if provider == "llamacpp":
                    model = settings.llamacpp_model_name
                elif provider == "gemini":
                    model = settings.gemini_model_name
                elif provider == "ollama":
                    model = settings.ollama_model_name
            except Exception:
                pass
                
        token_estimate = sum(len(p) // 4 for p in prompts)  # ~4 chars/token
        bus.emit(Event(
            kind=EK.LLM,
            title=f"▶ {model}  ~{token_estimate} prompt tokens",
            session_id=self.session_id,
            detail={
                "model":           model,
                "prompt_tokens":   token_estimate,
                "prompt_preview":  prompts[0] if prompts else "",
            },
        ))

    def on_llm_end(self, response, *, run_id=None, **kwargs) -> None:
        rid = str(run_id)
        start = self._llm_start.pop(rid, None)
        ms = (time.perf_counter() - start) * 1000 if start else None

        # Extract token usage if the provider returns it
        usage = {}
        try:
            # Try response.llm_output (standard for LangChain LLMResult)
            if hasattr(response, "llm_output") and response.llm_output:
                usage = response.llm_output.get("token_usage") or {}
            
            # Try generations message response_metadata or usage_metadata
            if not usage and hasattr(response, "generations") and response.generations:
                gen = response.generations[0][0]
                msg = getattr(gen, "message", None)
                if msg:
                    usage = getattr(msg, "usage_metadata", {}) or {}
                    if not usage and hasattr(msg, "response_metadata") and msg.response_metadata:
                        usage = msg.response_metadata.get("token_usage") or {}
        except Exception:
            pass

        in_t  = usage.get("prompt_tokens") or usage.get("input_tokens") or "?"
        out_t = usage.get("completion_tokens") or usage.get("output_tokens") or "?"

        text_preview = ""
        try:
            text_preview = response.generations[0][0].text
        except Exception:
            pass

        tool_calls = []
        try:
            msg = response.generations[0][0].message
            tool_calls = [tc["name"] for tc in getattr(msg, "tool_calls", [])]
        except Exception:
            pass

        extra = f"  → tools: {tool_calls}" if tool_calls else ""
        bus.emit(Event(
            kind=EK.LLM,
            title=f"✓ {in_t} in → {out_t} out{extra}",
            duration_ms=ms,
            session_id=self.session_id,
            detail={
                "input_tokens":   in_t,
                "output_tokens":  out_t,
                "tool_calls":     tool_calls,
                "response_preview": text_preview,
                "usage":          usage,
            },
        ))

    def on_llm_error(self, error, *, run_id=None, **kwargs) -> None:
        rid = str(run_id)
        start = self._llm_start.pop(rid, None)
        ms = (time.perf_counter() - start) * 1000 if start else None
        bus.emit(Event(
            kind=EK.LLM,
            title=f"✗ LLM error: {str(error)[:80]}",
            duration_ms=ms,
            is_error=True,
            session_id=self.session_id,
            detail={"error": str(error)},
        ))

    # ── Tools ─────────────────────────────────────────────────────────────────

    def on_tool_start(
        self, serialized: dict | None, input_str: str, *, run_id=None, **kwargs
    ) -> None:
        rid = str(run_id)
        self._tool_start[rid] = time.perf_counter()
        tool_name = "unknown_tool"
        if serialized and isinstance(serialized, dict):
            tool_name = serialized.get("name", "unknown_tool")
        bus.emit(Event(
            kind=EK.TOOL,
            title=f"▶ {tool_name}  ← {input_str[:80]}",
            session_id=self.session_id,
            detail={"tool": tool_name, "input": input_str},
        ))

    def on_tool_end(self, output: str, *, run_id=None, **kwargs) -> None:
        rid = str(run_id)
        start = self._tool_start.pop(rid, None)
        ms = (time.perf_counter() - start) * 1000 if start else None
        bus.emit(Event(
            kind=EK.TOOL,
            title=f"✓ → {str(output)[:80]}",
            duration_ms=ms,
            session_id=self.session_id,
            detail={"output": str(output)},
        ))

    def on_tool_error(self, error, *, run_id=None, **kwargs) -> None:
        rid = str(run_id)
        start = self._tool_start.pop(rid, None)
        ms = (time.perf_counter() - start) * 1000 if start else None
        bus.emit(Event(
            kind=EK.TOOL,
            title=f"✗ tool error: {str(error)[:80]}",
            duration_ms=ms,
            is_error=True,
            session_id=self.session_id,
            detail={"error": str(error)},
        ))

    # ── Agent / Chain ─────────────────────────────────────────────────────────

    def on_chain_start(self, serialized: dict | None, inputs: dict, *, run_id=None, **kwargs):
        if not serialized or not isinstance(serialized, dict):
            return
        name = serialized.get("name")
        if not name:
            id_list = serialized.get("id")
            if isinstance(id_list, list) and id_list:
                name = id_list[-1]
            else:
                name = "?"
        if name in ("RunnableSequence", "RunnableLambda"):
            return  # skip internal plumbing
        bus.emit(Event(
            kind=EK.AGENT,
            title=f"▶ {name}",
            session_id=self.session_id,
            detail={"chain": name, "inputs": _to_json_compatible(inputs)},
        ))

    def on_chain_end(self, outputs: dict, *, run_id=None, **kwargs):
        pass  # too noisy to log every chain end


# ─────────────────────────────────────────────────────────────────────────────
# AGENT STATE HOOK
# ─────────────────────────────────────────────────────────────────────────────

def emit_agent_state(state: dict, session_id: str, node_name: str = "") -> None:
    """
    Call from LangGraph nodes to capture OrderState snapshots.

    Usage in nodes.py:
        from monitoring.hooks import emit_agent_state
        def chatbot_node(state):
            emit_agent_state(state, state["session_id"], "chatbot_node")
            ...
    """
    cart_count = len(state.get("cart") or [])
    stage = state.get("stage", "?")
    bus.emit(Event(
        kind=EK.AGENT,
        title=f"{node_name}  stage={stage}  cart={cart_count} items",
        session_id=session_id,
        detail={
            "node":      node_name,
            "stage":     stage,
            "cart":      state.get("cart", []),
            "order_id":  state.get("order_id"),
            "full_state": _to_json_compatible(state),
        },
    ))


def emit_order_event(action: str, order_id: int, session_id: str, detail: dict = None) -> None:
    """
    Emit a business-level order lifecycle event.
    Call from OrderService when status changes.
    """
    bus.emit(Event(
        kind=EK.ORDER,
        title=f"{action}  order #{order_id}",
        session_id=session_id,
        detail={"action": action, "order_id": order_id, **(detail or {})},
    ))


def emit_allergen_event(item_name: str, allergens_found: list[str], session_id: str):
    bus.emit(Event(
        kind=EK.ALLERGEN,
        title=f"{item_name} — flagged: {', '.join(allergens_found)}",
        session_id=session_id,
        detail={"item": item_name, "allergens": allergens_found},
        is_error=False,
    ))


def emit_profile_loaded(profile_name: str, session_id: str, has_restrictions: bool):
    bus.emit(Event(
        kind=EK.PROFILE,
        title=f"Profile loaded: {profile_name}  {'⚠ has restrictions' if has_restrictions else ''}",
        session_id=session_id,
        detail={"name": profile_name, "has_restrictions": has_restrictions},
    ))


def emit_price_rule(rule_label: str, item: str, original: float, final: float, session_id: str):
    pct = round((1 - final/original) * 100) if original > 0 else 0
    bus.emit(Event(
        kind=EK.PRICING,
        title=f"{rule_label} applied to {item} — {pct}% off",
        session_id=session_id,
        detail={"rule": rule_label, "item": item, "original": original, "final": final},
    ))


def emit_upsell(suggested_item: str, anchor_item: str, lift_score: float, session_id: str):
    bus.emit(Event(
        kind=EK.UPSELL,
        title=f"Suggested {suggested_item} with {anchor_item} (lift: {lift_score:.2f})",
        session_id=session_id,
        detail={"suggestion": suggested_item, "anchor": anchor_item, "lift": lift_score},
    ))


def emit_rule_violation(rule_label: str, session_id: str, detail: dict = None):
    bus.emit(Event(
        kind=EK.RULE,
        title=f"Rule hit: {rule_label}",
        session_id=session_id,
        detail=detail or {},
    ))


# ─────────────────────────────────────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────────────────────────────────────

def _to_json_compatible(obj: Any) -> Any:
    if isinstance(obj, dict):
        return {k: _to_json_compatible(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_to_json_compatible(v) for v in obj]
    if isinstance(obj, (set, tuple)):
        return [_to_json_compatible(v) for v in list(obj)]
    
    from decimal import Decimal
    if isinstance(obj, Decimal):
        return float(obj)
        
    from datetime import datetime, date
    if isinstance(obj, (datetime, date)):
        return obj.isoformat()
        
    try:
        from langchain_core.messages import BaseMessage
        if isinstance(obj, BaseMessage):
            return {
                "type": obj.type,
                "content": obj.content,
                "additional_kwargs": obj.additional_kwargs,
                "response_metadata": obj.response_metadata,
                "name": obj.name,
                "id": obj.id,
            }
    except ImportError:
        pass

    if hasattr(obj, "dict") and callable(obj.dict):
        try:
            return _to_json_compatible(obj.dict())
        except Exception:
            pass
            
    try:
        json.dumps(obj)
        return obj
    except Exception:
        return str(obj)


def _safe_truncate(obj: Any, max_len: int = 500) -> str:
    try:
        s = json.dumps(_to_json_compatible(obj))
        return s if len(s) <= max_len else s[:max_len] + "…"
    except Exception:
        return str(obj)[:max_len]
