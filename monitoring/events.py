"""
monitoring/events.py

Central event system. Every layer (DB, Redis, LLM, tools, agent) emits
MonitorEvents into the global `bus`. The NiceGUI dashboard subscribes.

Import and use from anywhere:
    from monitoring.events import bus, Event, EK
    bus.emit(Event(kind=EK.DB, title="SELECT menu_items", duration_ms=12.4))
"""

from __future__ import annotations

import threading
import time
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Callable


# ─────────────────────────────────────────────────────────────────────────────
# EVENT KINDS
# ─────────────────────────────────────────────────────────────────────────────

class EK(str, Enum):
    LLM   = "llm"
    TOOL  = "tool"
    DB    = "db"
    REDIS = "redis"
    AGENT = "agent"
    ORDER = "order"
    ERROR = "error"


# Visual config — one place to change colours / icons for every consumer
_KIND_META: dict[EK, dict] = {
    EK.LLM:   {"color": "#42a5f5", "label": "🤖 LLM",   "dark": "#1565c0"},
    EK.TOOL:  {"color": "#66bb6a", "label": "🔧 TOOL",  "dark": "#2e7d32"},
    EK.DB:    {"color": "#ffa726", "label": "🗄  DB",    "dark": "#e65100"},
    EK.REDIS: {"color": "#ab47bc", "label": "⚡ REDIS",  "dark": "#6a1b9a"},
    EK.AGENT: {"color": "#26c6da", "label": "🌐 AGENT",  "dark": "#00838f"},
    EK.ORDER: {"color": "#26a69a", "label": "🧾 ORDER",  "dark": "#00695c"},
    EK.ERROR: {"color": "#ef5350", "label": "❌ ERROR",  "dark": "#b71c1c"},
}


# ─────────────────────────────────────────────────────────────────────────────
# EVENT DATACLASS
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class Event:
    kind:        EK
    title:       str                          # one-line summary shown in timeline
    detail:      dict[str, Any]  = field(default_factory=dict)  # expandable detail
    session_id:  str             = ""
    duration_ms: float | None   = None
    is_error:    bool            = False
    ts:          datetime        = field(default_factory=datetime.now)

    # ── Derived display helpers ───────────────────────────────────────────

    @property
    def color(self) -> str:
        return _KIND_META[EK.ERROR if self.is_error else self.kind]["color"]

    @property
    def dark_color(self) -> str:
        return _KIND_META[EK.ERROR if self.is_error else self.kind]["dark"]

    @property
    def label(self) -> str:
        return _KIND_META[self.kind]["label"]

    @property
    def dur_str(self) -> str:
        if self.duration_ms is None:
            return ""
        if self.duration_ms >= 1000:
            return f"{self.duration_ms / 1000:.2f}s"
        return f"{self.duration_ms:.0f}ms"

    @property
    def dur_color(self) -> str:
        """Traffic-light colouring for duration."""
        if self.duration_ms is None:
            return "grey"
        thresholds = {
            EK.DB:    (100, 500),
            EK.REDIS: (10, 50),
            EK.LLM:   (3000, 10000),
            EK.TOOL:  (500, 2000),
        }
        lo, hi = thresholds.get(self.kind, (200, 1000))
        if self.duration_ms < lo:   return "positive"
        if self.duration_ms < hi:   return "warning"
        return "negative"

    @property
    def session_short(self) -> str:
        return self.session_id[:8] if self.session_id else "—"

    def to_log_line(self) -> str:
        ts  = self.ts.strftime("%H:%M:%S.%f")[:12]
        dur = f"  {self.dur_str:<8}" if self.duration_ms is not None else " " * 10
        sid = f"  [{self.session_short}]" if self.session_id else ""
        err = "  ⚠ SLOW" if (
            self.duration_ms and self.dur_color == "negative"
        ) else ""
        return f"{ts}  {self.label:<14}  {self.title}{dur}{sid}{err}"


# ─────────────────────────────────────────────────────────────────────────────
# METRICS TRACKER
# ─────────────────────────────────────────────────────────────────────────────

class Metrics:
    """Rolling window stats per event kind."""

    _WINDOW = 100   # keep last N durations

    def __init__(self) -> None:
        self._counts: dict[EK, int]          = {k: 0 for k in EK}
        self._durations: dict[EK, deque]     = {k: deque(maxlen=self._WINDOW) for k in EK}
        self._errors: int                    = 0
        self._cache_hits: int                = 0
        self._cache_misses: int              = 0
        self._lock = threading.Lock()

    def record(self, event: Event) -> None:
        with self._lock:
            self._counts[event.kind] += 1
            if event.duration_ms is not None:
                self._durations[event.kind].append(event.duration_ms)
            if event.is_error:
                self._errors += 1
            if event.kind == EK.REDIS:
                if event.detail.get("hit"):
                    self._cache_hits += 1
                elif event.detail.get("hit") is False:
                    self._cache_misses += 1

    def avg_ms(self, kind: EK) -> float | None:
        d = list(self._durations[kind])
        return round(sum(d) / len(d), 1) if d else None

    def p95_ms(self, kind: EK) -> float | None:
        d = sorted(self._durations[kind])
        if not d:
            return None
        idx = max(0, int(len(d) * 0.95) - 1)
        return round(d[idx], 1)

    def count(self, kind: EK) -> int:
        return self._counts[kind]

    def total_events(self) -> int:
        return sum(self._counts.values())

    def error_count(self) -> int:
        return self._errors

    def cache_hit_rate(self) -> float | None:
        total = self._cache_hits + self._cache_misses
        return round(self._cache_hits / total * 100, 1) if total else None


# ─────────────────────────────────────────────────────────────────────────────
# EVENT BUS
# ─────────────────────────────────────────────────────────────────────────────

class EventBus:
    """
    Thread-safe pub/sub bus.

    - Stores last `max_events` events in a ring buffer.
    - Calls all synchronous listener callbacks on emit() (in the caller's thread).
    - NiceGUI dashboard uses timer-based polling rather than direct callbacks
      to stay on the correct async context — see dashboard.py.
    """

    def __init__(self, max_events: int = 2000) -> None:
        self._buffer: deque[Event]               = deque(maxlen=max_events)
        self._listeners: list[Callable[[Event], None]] = []
        self._lock = threading.Lock()
        self.metrics = Metrics()

    # ── Emit ─────────────────────────────────────────────────────────────────

    def emit(self, event: Event) -> None:
        with self._lock:
            self._buffer.append(event)
        self.metrics.record(event)
        for fn in self._listeners[:]:       # snapshot to avoid mutation during iteration
            try:
                fn(event)
            except Exception:
                pass                        # listeners must not crash the emitter

    # ── Subscribe ─────────────────────────────────────────────────────────────

    def subscribe(self, fn: Callable[[Event], None]) -> None:
        with self._lock:
            if fn not in self._listeners:
                self._listeners.append(fn)

    def unsubscribe(self, fn: Callable[[Event], None]) -> None:
        with self._lock:
            try:
                self._listeners.remove(fn)
            except ValueError:
                pass

    # ── Query ─────────────────────────────────────────────────────────────────

    def all_events(self) -> list[Event]:
        return list(self._buffer)

    def by_kind(self, kind: EK) -> list[Event]:
        return [e for e in self._buffer if e.kind == kind]

    def by_session(self, session_id: str) -> list[Event]:
        return [e for e in self._buffer if e.session_id == session_id]

    def recent(self, n: int = 100) -> list[Event]:
        events = list(self._buffer)
        return events[-n:]

    def sessions(self) -> list[str]:
        seen, out = set(), []
        for e in reversed(self._buffer):
            if e.session_id and e.session_id not in seen:
                seen.add(e.session_id)
                out.append(e.session_id)
        return out

    def errors(self) -> list[Event]:
        return [e for e in self._buffer if e.is_error]


# ── Global singleton ──────────────────────────────────────────────────────────
bus = EventBus()
