"""
monitoring/dashboard.py

NiceGUI developer monitoring dashboard.
Mounts at /monitor inside your FastAPI app.

Features
--------
  Timeline   — live chronological event stream, colour-coded by kind
  LLM        — every call: tokens in/out, latency, prompt & response preview
  DB         — every query: SQL, table, duration, slow-query highlighting
  Redis      — every op: key, hit/miss, TTL, cache-hit-rate gauge
  Tools      — every tool call: args, result, latency
  Agent      — OrderState snapshots per session, expandable JSON
  Errors     — isolated error feed, never buried in the timeline

Mount in api/main.py
--------------------
    from monitoring.dashboard import mount_dashboard
    mount_dashboard(app)          # adds /monitor route
    # Dashboard at http://localhost:8000/monitor

Add to pyproject.toml
---------------------
    "nicegui>=1.4.33",
"""

from __future__ import annotations

import json

from nicegui import ui

from monitoring.events import EK, Event, bus


# ─────────────────────────────────────────────────────────────────────────────
# THEME / DESIGN TOKENS
# ─────────────────────────────────────────────────────────────────────────────

_DARK_BG = "#0f1117"
_CARD_BG = "#1a1d27"
_BORDER = "#2a2d3e"
_MONO = "font-family: 'JetBrains Mono', 'Fira Code', monospace; font-size: 12px;"
# Maps EK → Quasar color name  (used for badges, chips, borders)
_Q_COLOR: dict[EK, str] = {
    EK.LLM: "blue",
    EK.TOOL: "green",
    EK.DB: "amber",
    EK.REDIS: "purple",
    EK.AGENT: "cyan",
    EK.ORDER: "teal",
    EK.ERROR: "red",
    EK.ALLERGEN: "red",
    EK.PROFILE: "indigo",
    EK.PRICING: "light-green",
    EK.UPSELL: "orange",
    EK.RULE: "deep-orange",
}

_ICON: dict[EK, str] = {
    EK.LLM: "smart_toy",
    EK.TOOL: "build",
    EK.DB: "storage",
    EK.REDIS: "bolt",
    EK.AGENT: "account_tree",
    EK.ORDER: "receipt_long",
    EK.ERROR: "error_outline",
    EK.ALLERGEN: "warning",
    EK.PROFILE: "person",
    EK.PRICING: "sell",
    EK.UPSELL: "shopping_cart",
    EK.RULE: "gavel",
}
# ─────────────────────────────────────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────────────────────────────────────


def _dur_badge(event: Event):
    if event.duration_ms is None:
        return
    ui.badge(event.dur_str, color=event.dur_color).props("outline rounded")


def _ts_label(event: Event):
    ui.label(event.ts.strftime("%H:%M:%S.%f")[:12]).style(_MONO + "color:#6272a4;")


def _session_chip(event: Event):
    if event.session_id:
        ui.chip(event.session_short, icon="person", color="grey").props("outline dense").style(
            "font-size:11px;"
        )


def _kind_badge(event: Event):
    ui.badge(event.kind.value.upper(), color=_Q_COLOR[event.kind]).props("rounded")


def _detail_expansion(event: Event):
    """Expandable JSON detail block for any event."""
    if not event.detail:
        return
    with ui.expansion("Details", icon="expand_more").classes("w-full"):
        ui.code(json.dumps(event.detail, indent=2, default=str)).classes("w-full text-xs").style(
            "background:#0d1117; border-radius:6px; max-height:350px; overflow:auto; white-space:pre;"
        )


def _event_card(event: Event, container=None):
    """Render one event as a card with left colour border."""
    ctx = container if container else ui
    with ctx:
        with (
            ui.card()
            .classes("w-full q-mb-xs")
            .style(
                f"background:{_CARD_BG}; border:1px solid {_BORDER}; "
                f"border-left: 4px solid {event.color}; padding:8px 12px;"
            )
        ):
            with ui.row().classes("items-center gap-2 w-full flex-wrap"):
                _ts_label(event)
                ui.icon(_ICON.get(event.kind, "circle"), color=_Q_COLOR[event.kind]).props(
                    "size=18px"
                )
                _kind_badge(event)
                ui.label(event.title).style(
                    _MONO + f"color:{'#ff6b6b' if event.is_error else '#e2e8f0'}; flex:1;"
                )
                _dur_badge(event)
                _session_chip(event)
            _detail_expansion(event)


# ─────────────────────────────────────────────────────────────────────────────
# METRIC CARDS ROW  (top of page)
# ─────────────────────────────────────────────────────────────────────────────


def _build_metric_card(title: str, value: str, subtitle: str, color: str):
    with ui.card().style(
        f"background:{_CARD_BG}; border:1px solid {_BORDER}; "
        f"border-top:3px solid {color}; min-width:130px; padding:12px 16px;"
    ):
        ui.label(title).style(
            "color:#6272a4; font-size:11px; text-transform:uppercase; letter-spacing:.06em;"
        )
        ui.label(value).style(f"color:{color}; font-size:22px; font-weight:600; line-height:1.3;")
        ui.label(subtitle).style("color:#6272a4; font-size:11px;")


def _metrics_row(m_cards_ref: dict):
    """Build the top metric strip. Returns a dict of label refs for live update."""
    refs: dict[str, ui.label] = {}
    with ui.row().classes("gap-3 w-full flex-wrap q-mb-md"):
        specs = [
            ("total", "Total Events", bus.metrics.total_events, "#e2e8f0", lambda v: str(v)),
            ("errors", "Errors", bus.metrics.error_count, "#ff6b6b", lambda v: str(v)),
            (
                "llm_avg",
                "Avg LLM",
                lambda: bus.metrics.avg_ms(EK.LLM),
                "#42a5f5",
                lambda v: f"{v:.0f}ms" if v else "—",
            ),
            (
                "db_avg",
                "Avg DB",
                lambda: bus.metrics.avg_ms(EK.DB),
                "#ffa726",
                lambda v: f"{v:.0f}ms" if v else "—",
            ),
            (
                "redis_avg",
                "Avg Redis",
                lambda: bus.metrics.avg_ms(EK.REDIS),
                "#ab47bc",
                lambda v: f"{v:.1f}ms" if v else "—",
            ),
            (
                "tools_avg",
                "Avg Tool",
                lambda: bus.metrics.avg_ms(EK.TOOL),
                "#66bb6a",
                lambda v: f"{v:.0f}ms" if v else "—",
            ),
            (
                "cache_rate",
                "Cache Hit",
                bus.metrics.cache_hit_rate,
                "#66bb6a",
                lambda v: f"{v}%" if v else "—",
            ),
        ]
        for key, title, getter, color, fmt in specs:
            with ui.card().style(
                f"background:{_CARD_BG}; border:1px solid {_BORDER}; "
                f"border-top:3px solid {color}; min-width:130px; padding:12px 16px; cursor:default;"
            ):
                ui.label(title).style(
                    "color:#6272a4; font-size:11px; text-transform:uppercase; letter-spacing:.06em;"
                )
                val_label = ui.label("—").style(
                    f"color:{color}; font-size:22px; font-weight:600; line-height:1.3;"
                )
                refs[key] = (val_label, getter, fmt)

    return refs


# ─────────────────────────────────────────────────────────────────────────────
# SIDEBAR — sessions + filters
# ─────────────────────────────────────────────────────────────────────────────


def _build_sidebar(filter_state: dict):
    """Left drawer: active sessions + event-kind filter toggles."""
    with ui.left_drawer(value=True).style(
        f"background:{_CARD_BG}; border-right:1px solid {_BORDER}; padding:16px;"
    ):
        ui.label("SESSIONS").style(
            "color:#6272a4; font-size:11px; font-weight:600; letter-spacing:.08em;"
        )

        session_container = ui.column().classes("w-full q-mb-md gap-1")

        ui.separator().style("margin:12px 0; border-color:#2a2d3e;")

        ui.label("FILTER BY TYPE").style(
            "color:#6272a4; font-size:11px; font-weight:600; letter-spacing:.08em;"
        )
        for kind in EK:
            color = _Q_COLOR[kind]
            sw = (
                ui.switch(kind.value.upper(), value=True)
                .props(f"color={color} dense")
                .style("margin:2px 0;")
            )
            sw.on("update:model-value", lambda v, k=kind: filter_state.update({k: v}))
            filter_state[kind] = True

        ui.separator().style("margin:12px 0; border-color:#2a2d3e;")

        ui.label("SLOW THRESHOLDS").style(
            "color:#6272a4; font-size:11px; font-weight:600; letter-spacing:.08em;"
        )
        ui.label("DB > 100ms").style("color:#ffa726; font-size:11px;")
        ui.label("LLM > 5s").style("color:#42a5f5; font-size:11px;")
        ui.label("Redis > 20ms").style("color:#ab47bc; font-size:11px;")

        return session_container


# ─────────────────────────────────────────────────────────────────────────────
# TAB BUILDERS
# ─────────────────────────────────────────────────────────────────────────────


def _tab_timeline(filter_state: dict) -> dict:
    """
    Main live event feed. Returns refs needed for the update timer.
    """
    with ui.row().classes("w-full items-center gap-2 q-mb-sm"):
        ui.label("Live event stream — newest at bottom").style("color:#6272a4; font-size:12px;")
        ui.space()
        clear_btn = ui.button("Clear", icon="delete_sweep", color="grey").props(
            "flat dense size=sm"
        )

    scroll = ui.scroll_area().classes("w-full").style("height: calc(100vh - 230px);")
    with scroll:
        event_col = ui.column().classes("w-full gap-1")

    # Seed with existing events
    for ev in bus.recent(80):
        if filter_state.get(ev.kind, True):
            _event_card(ev, event_col)

    def on_clear():
        event_col.clear()

    clear_btn.on("click", on_clear)

    return {"event_col": event_col, "scroll": scroll}


def _tab_llm() -> dict:
    """Token usage, latency table, prompt/response preview."""
    rows = [
        {
            "ts": e.ts.strftime("%H:%M:%S"),
            "title": e.title[:60],
            "duration": e.dur_str,
            "session": e.session_short,
            "error": "✗" if e.is_error else "",
            "_detail": json.dumps(e.detail, default=str),
        }
        for e in reversed(bus.by_kind(EK.LLM))
    ]
    cols = [
        {"name": "ts", "label": "Time", "field": "ts", "align": "left"},
        {"name": "title", "label": "Summary", "field": "title", "align": "left"},
        {"name": "duration", "label": "Duration", "field": "duration", "align": "right"},
        {"name": "session", "label": "Session", "field": "session", "align": "left"},
        {"name": "error", "label": "", "field": "error", "align": "center"},
    ]
    tbl = ui.table(columns=cols, rows=rows, row_key="ts").classes("w-full").props("dense flat")
    tbl.add_slot(
        "body-cell-duration",
        """
        <q-td :props="props">
          <q-badge :color="props.value.endsWith('s') && parseFloat(props.value) > 5 ? 'negative' : 'positive'"
                   :label="props.value" outline rounded />
        </q-td>
    """,
    )

    ui.separator().style("margin:12px 0;")
    ui.label("Click a row to see prompt / response preview").style("color:#6272a4; font-size:12px;")
    detail_box = (
        ui.json_editor(properties={"content": {"json": {}}, "readOnly": True})
        .classes("w-full")
        .style("min-height:350px;")
    )

    def on_row_click(e):
        try:
            row = e.args[1] if len(e.args) > 1 else {}
            detail_data = json.loads(row.get("_detail", "{}"))
            detail_box.properties["content"] = {"json": detail_data}
            detail_box.update()
        except Exception:
            pass

    tbl.on("rowClick", on_row_click)
    return {"tbl": tbl}


def _tab_db() -> dict:
    """All DB queries. Slow ones (>100ms) highlighted amber/red."""
    rows = [
        {
            "ts": e.ts.strftime("%H:%M:%S"),
            "op": e.detail.get("operation", "?"),
            "table": e.detail.get("table", "?"),
            "sql": (e.detail.get("sql") or "")[:70],
            "duration": e.dur_str,
            "dur_raw": e.duration_ms or 0,
            "session": e.session_short,
        }
        for e in reversed(bus.by_kind(EK.DB))
    ]
    cols = [
        {"name": "ts", "label": "Time", "field": "ts", "align": "left", "sortable": True},
        {"name": "op", "label": "Op", "field": "op", "align": "left"},
        {"name": "table", "label": "Table", "field": "table", "align": "left"},
        {"name": "sql", "label": "SQL", "field": "sql", "align": "left"},
        {
            "name": "duration",
            "label": "Duration",
            "field": "duration",
            "align": "right",
            "sortable": True,
        },
        {"name": "session", "label": "Session", "field": "session", "align": "left"},
    ]
    tbl = ui.table(columns=cols, rows=rows, row_key="ts").classes("w-full").props("dense flat")
    tbl.add_slot(
        "body-cell-duration",
        """
        <q-td :props="props">
          <q-badge
            :color="props.row.dur_raw > 500 ? 'negative' : props.row.dur_raw > 100 ? 'warning' : 'positive'"
            :label="props.value" outline rounded />
        </q-td>
    """,
    )
    tbl.add_slot(
        "body-cell-op",
        """
        <q-td :props="props">
          <q-badge
            :color="props.value === 'INSERT' ? 'green' : props.value === 'UPDATE' ? 'amber' : props.value === 'DELETE' ? 'red' : 'blue'"
            :label="props.value" />
        </q-td>
    """,
    )
    return {"tbl": tbl}


def _tab_redis() -> dict:
    """Redis ops with hit/miss indicator and cache-hit rate."""
    hit_total = sum(1 for e in bus.by_kind(EK.REDIS) if e.detail.get("hit") is True)
    miss_total = sum(1 for e in bus.by_kind(EK.REDIS) if e.detail.get("hit") is False)
    total_hm = hit_total + miss_total

    with ui.row().classes("gap-4 q-mb-md"):
        with ui.card().style(
            f"background:{_CARD_BG}; border:1px solid {_BORDER}; padding:12px 20px;"
        ):
            ui.label("Cache Hit Rate").style("color:#6272a4; font-size:11px;")
            rate = round(hit_total / total_hm * 100) if total_hm else 0
            hit_label = ui.label(f"{rate}%").style(
                "color:#66bb6a; font-size:24px; font-weight:600;"
            )
            ui.linear_progress(rate / 100, color="green", size="6px")
        with ui.card().style(
            f"background:{_CARD_BG}; border:1px solid {_BORDER}; padding:12px 20px;"
        ):
            ui.label("Hits / Misses").style("color:#6272a4; font-size:11px;")
            hm_label = ui.label(f"{hit_total} / {miss_total}").style(
                "color:#e2e8f0; font-size:18px; font-weight:500;"
            )

    rows = [
        {
            "ts": e.ts.strftime("%H:%M:%S"),
            "op": e.detail.get("op", "?"),
            "key": e.detail.get("key", ""),
            "hit": "HIT ✓"
            if e.detail.get("hit") is True
            else ("MISS ✗" if e.detail.get("hit") is False else "—"),
            "ttl": str(e.detail.get("ttl", "—")),
            "dur": e.dur_str,
            "session": e.session_short,
        }
        for e in reversed(bus.by_kind(EK.REDIS))
    ]
    cols = [
        {"name": "ts", "label": "Time", "field": "ts", "align": "left"},
        {"name": "op", "label": "Op", "field": "op", "align": "left"},
        {"name": "key", "label": "Key", "field": "key", "align": "left"},
        {"name": "hit", "label": "Hit", "field": "hit", "align": "left"},
        {"name": "ttl", "label": "TTL", "field": "ttl", "align": "right"},
        {"name": "dur", "label": "Latency", "field": "dur", "align": "right"},
        {"name": "session", "label": "Session", "field": "session", "align": "left"},
    ]
    tbl = ui.table(columns=cols, rows=rows, row_key="ts").classes("w-full").props("dense flat")
    tbl.add_slot(
        "body-cell-hit",
        """
        <q-td :props="props">
          <span :style="{color: props.value.includes('HIT') ? '#66bb6a' : props.value.includes('MISS') ? '#ff6b6b' : '#6272a4'}">
            {{ props.value }}
          </span>
        </q-td>
    """,
    )
    return {"tbl": tbl, "hit_label": hit_label, "hm_label": hm_label}


def _tab_tools() -> dict:
    """Tool calls with args and results."""
    rows = [
        {
            "ts": e.ts.strftime("%H:%M:%S"),
            "tool": e.detail.get("tool", e.title[:40]),
            "input": str(e.detail.get("input", ""))[:60],
            "output": str(e.detail.get("output", ""))[:60],
            "dur": e.dur_str,
            "ok": "✗" if e.is_error else "✓",
            "session": e.session_short,
        }
        for e in reversed(bus.by_kind(EK.TOOL))
    ]
    cols = [
        {"name": "ts", "label": "Time", "field": "ts", "align": "left"},
        {"name": "tool", "label": "Tool", "field": "tool", "align": "left"},
        {"name": "input", "label": "Input", "field": "input", "align": "left"},
        {"name": "output", "label": "Output", "field": "output", "align": "left"},
        {"name": "dur", "label": "Latency", "field": "dur", "align": "right"},
        {"name": "ok", "label": "", "field": "ok", "align": "center"},
        {"name": "session", "label": "Session", "field": "session", "align": "left"},
    ]
    tbl = ui.table(columns=cols, rows=rows, row_key="ts").classes("w-full").props("dense flat")
    tbl.add_slot(
        "body-cell-ok",
        """
        <q-td :props="props">
          <span :style="{color: props.value === '✓' ? '#66bb6a' : '#ff6b6b', fontWeight:'bold'}">
            {{ props.value }}
          </span>
        </q-td>
    """,
    )
    return {"tbl": tbl}


def _tab_agent() -> dict:
    """Per-session OrderState snapshots — rendered as structured info + raw JSON."""
    sessions = bus.sessions()

    with ui.row().classes("items-center gap-4 q-mb-md"):
        session_select = ui.select(
            options=sessions or ["(no sessions yet)"],
            value=sessions[0] if sessions else None,
            label="Select Session to Inspect State",
        ).classes("w-80")

    # 1. Summary Cards Row
    with ui.row().classes("gap-3 w-full flex-wrap q-mb-md"):
        with ui.card().style(
            f"background:{_CARD_BG}; border:1px solid {_BORDER}; min-width:140px; padding:10px 14px;"
        ):
            ui.label("Conversation Stage").style(
                "color:#6272a4; font-size:11px; text-transform:uppercase;"
            )
            stage_badge = (
                ui.badge("—", color="cyan")
                .props("rounded")
                .style("font-size:14px; padding:4px 8px; margin-top:4px;")
            )

        with ui.card().style(
            f"background:{_CARD_BG}; border:1px solid {_BORDER}; min-width:140px; padding:10px 14px;"
        ):
            ui.label("Customer Name").style(
                "color:#6272a4; font-size:11px; text-transform:uppercase;"
            )
            customer_label = ui.label("—").style(
                "color:#e2e8f0; font-size:18px; font-weight:600; margin-top:4px;"
            )

        with ui.card().style(
            f"background:{_CARD_BG}; border:1px solid {_BORDER}; min-width:140px; padding:10px 14px;"
        ):
            ui.label("Database Order ID").style(
                "color:#6272a4; font-size:11px; text-transform:uppercase;"
            )
            order_id_label = ui.label("—").style(
                "color:#e2e8f0; font-size:18px; font-weight:600; margin-top:4px;"
            )

        with ui.card().style(
            f"background:{_CARD_BG}; border:1px solid {_BORDER}; min-width:140px; padding:10px 14px;"
        ):
            ui.label("Cart Total").style("color:#6272a4; font-size:11px; text-transform:uppercase;")
            cart_total_label = ui.label("—").style(
                "color:#26a69a; font-size:18px; font-weight:600; margin-top:4px;"
            )

    # 2. Cart Items Table Section
    ui.label("CART ITEMS").style(
        "color:#6272a4; font-size:11px; font-weight:600; letter-spacing:.08em; margin-bottom:4px; margin-top:8px;"
    )
    cart_container = ui.column().classes("w-full q-mb-md gap-1")

    # 3. Raw JSON Section
    with (
        ui.expansion("Raw State JSON (Advanced)", icon="terminal")
        .classes("w-full")
        .style("margin-top:12px;")
    ):
        state_code = (
            ui.json_editor(properties={"content": {"json": {}}, "readOnly": True})
            .classes("w-full")
            .style("min-height:450px;")
        )

    def load_session(session_id: str | None):
        if not session_id or session_id.startswith("("):
            stage_badge.set_text("—")
            customer_label.set_text("—")
            order_id_label.set_text("—")
            cart_total_label.set_text("—")
            with cart_container:
                cart_container.clear()
                ui.label("No active session.").style("color:#6272a4; font-size:12px; padding:12px;")
            state_code.properties["content"] = {"json": {}}
            state_code.update()
            return

        events = [e for e in bus.by_session(session_id) if e.kind == EK.AGENT]
        if not events:
            stage_badge.set_text("—")
            customer_label.set_text("—")
            order_id_label.set_text("—")
            cart_total_label.set_text("—")
            with cart_container:
                cart_container.clear()
                ui.label("No agent state events captured for this session yet.").style(
                    "color:#6272a4; font-size:12px; padding:12px;"
                )
            state_code.properties["content"] = {"json": {"message": "No agent state captured yet."}}
            state_code.update()
            return

        # Get latest agent state
        latest = events[-1]
        detail = latest.detail or {}

        # Determine full state dict
        full_state = detail.get("full_state")
        state_dict = {}
        if isinstance(full_state, str):
            try:
                clean_str = full_state
                if clean_str.endswith("…"):
                    clean_str = clean_str[:-1]
                state_dict = json.loads(clean_str)
            except Exception:
                state_dict = detail
        elif isinstance(full_state, dict):
            state_dict = full_state
        else:
            state_dict = detail

        # Fallback to direct keys from detail if state_dict is empty
        if not state_dict:
            state_dict = detail

        # Update stage badge
        stage_val = state_dict.get("stage", "greeting").upper()
        stage_badge.set_text(stage_val)

        # Color based on stage
        stage_colors = {
            "GREETING": "blue",
            "ORDERING": "amber",
            "CONFIRMING": "purple",
            "PAYMENT": "teal",
            "DONE": "green",
        }
        stage_badge.props(f"color={stage_colors.get(stage_val, 'grey')}")

        # Update labels
        customer_label.set_text(str(state_dict.get("customer_name") or "Anonymous"))
        order_id_label.set_text(
            f"#{state_dict.get('order_id')}" if state_dict.get("order_id") else "None"
        )

        # Render Cart
        cart = state_dict.get("cart", [])
        total_price = sum(item.get("price", 0) * item.get("quantity", 0) for item in cart)
        cart_total_label.set_text(f"${total_price:.2f}")

        with cart_container:
            cart_container.clear()
            if not cart:
                ui.label("Cart is empty").style("color:#6272a4; font-size:12px; padding:12px;")
            else:
                cols = [
                    {"name": "name", "label": "Item Name", "field": "name", "align": "left"},
                    {"name": "price", "label": "Price", "field": "price", "align": "right"},
                    {"name": "qty", "label": "Qty", "field": "qty", "align": "center"},
                    {
                        "name": "subtotal",
                        "label": "Subtotal",
                        "field": "subtotal",
                        "align": "right",
                    },
                ]
                rows = [
                    {
                        "name": i.get("name", "?"),
                        "price": f"${i.get('price', 0):.2f}",
                        "qty": f"×{i.get('quantity', 1)}",
                        "subtotal": f"${(i.get('price', 0) * i.get('quantity', 1)):.2f}",
                    }
                    for i in cart
                ]
                ui.table(columns=cols, rows=rows, row_key="name").classes("w-full").props(
                    "dense flat"
                )

        # Update JSON code block
        state_code.properties["content"] = {"json": state_dict}
        state_code.update()

    session_select.on_value_change(lambda e: load_session(e.value))

    # Auto-load initial value
    if sessions:
        load_session(sessions[0])

    return {"select": session_select, "load_session_fn": load_session}


def _tab_errors() -> dict:
    """Isolated error stream — never buried in the main timeline."""
    errors = bus.errors()
    container = ui.column().classes("w-full gap-1")
    with container:
        no_errors_label = ui.label("✅  No errors recorded").style(
            "color:#66bb6a; font-size:14px; padding:24px;"
        )
        no_errors_label.set_visibility(len(errors) == 0)

        err_col = ui.column().classes("w-full gap-1")
        for ev in reversed(errors[-100:]):
            _event_card(ev, err_col)
    return {"err_col": err_col, "no_errors_label": no_errors_label}


def _tab_allergens() -> dict:
    """Allergen checks and warnings."""
    rows = [
        {
            "ts": e.ts.strftime("%H:%M:%S"),
            "item": e.detail.get("item", e.title),
            "allergens": ", ".join(e.detail.get("allergens", [])),
            "session": e.session_short,
        }
        for e in reversed(bus.by_kind(EK.ALLERGEN))
    ]
    cols = [
        {"name": "ts", "label": "Time", "field": "ts", "align": "left"},
        {"name": "item", "label": "Item Name", "field": "item", "align": "left"},
        {"name": "allergens", "label": "Flagged Allergens", "field": "allergens", "align": "left"},
        {"name": "session", "label": "Session", "field": "session", "align": "left"},
    ]
    tbl = ui.table(columns=cols, rows=rows, row_key="ts").classes("w-full").props("dense flat")
    return {"tbl": tbl}


def _tab_pricing() -> dict:
    """Applied pricing rules and discounts."""
    rows = [
        {
            "ts": e.ts.strftime("%H:%M:%S"),
            "item": e.detail.get("item", ""),
            "rule": e.detail.get("rule", ""),
            "original": f"${e.detail.get('original', 0.0):.2f}",
            "final": f"${e.detail.get('final', 0.0):.2f}",
            "discount": f"{round((1 - e.detail.get('final', 0.0)/e.detail.get('original', 1.0)) * 100)}%" if e.detail.get('original', 0.0) > 0 else "0%",
            "session": e.session_short,
        }
        for e in reversed(bus.by_kind(EK.PRICING))
    ]
    cols = [
        {"name": "ts", "label": "Time", "field": "ts", "align": "left"},
        {"name": "item", "label": "Item Name", "field": "item", "align": "left"},
        {"name": "rule", "label": "Rule Label", "field": "rule", "align": "left"},
        {"name": "original", "label": "Original Price", "field": "original", "align": "right"},
        {"name": "final", "label": "Final Price", "field": "final", "align": "right"},
        {"name": "discount", "label": "Discount (%)", "field": "discount", "align": "right"},
        {"name": "session", "label": "Session", "field": "session", "align": "left"},
    ]
    tbl = ui.table(columns=cols, rows=rows, row_key="ts").classes("w-full").props("dense flat")
    return {"tbl": tbl}


# ─────────────────────────────────────────────────────────────────────────────
# PAGE
# ─────────────────────────────────────────────────────────────────────────────


def _build_page():
    """Full NiceGUI page definition. Called once per browser connection."""

    # Per-connection state
    pending_events: list[Event] = []
    filter_state: dict = {"session_id": None}  # None = All Sessions

    def on_new_event(event: Event):
        """Callback from EventBus — called in emitter's thread, not NiceGUI's."""
        pending_events.append(event)

    bus.subscribe(on_new_event)

    # ── Dark mode ────────────────────────────────────────────────────────────
    ui.dark_mode().enable()
    ui.query("body").style(f"background:{_DARK_BG};")
    ui.query(".q-table__container").style("background:transparent;")
    ui.query(".q-table tbody tr:hover").style(f"background:{_BORDER} !important;")
    ui.query(".q-table th").style("color:#6272a4 !important; font-size:11px; letter-spacing:.06em;")
    ui.query(".q-table td").style(_MONO)
    ui.add_head_html(
        "<link rel='preconnect' href='https://fonts.googleapis.com'>"
        "<link href='https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;500&display=swap' rel='stylesheet'>"
    )

    # ── Header ───────────────────────────────────────────────────────────────
    with (
        ui.header()
        .style(
            f"background:{_CARD_BG}; border-bottom:1px solid {_BORDER}; "
            "padding:0 24px; height:52px;"
        )
        .classes("items-center")
    ):
        ui.icon("monitor_heart", color="green").props("size=22px")
        ui.label("Restaurant AI").style(
            "color:#e2e8f0; font-size:15px; font-weight:600; margin:0 8px;"
        )
        ui.label("Dev Monitor").style("color:#6272a4; font-size:14px;")
        ui.space()
        ui.badge("● LIVE", color="green").props("rounded").style("font-size:11px;")
        err_chip = ui.chip(
            f"{bus.metrics.error_count()} errors",
            icon="error_outline",
            color="red" if bus.metrics.error_count() > 0 else "grey",
        ).props("outline dense")
        ui.space()
        ui.button(icon="refresh", on_click=ui.navigate.reload).props("flat round dense color=grey")

    # ── Sidebar ───────────────────────────────────────────────────────────────
    with ui.left_drawer(value=True).style(
        f"background:{_CARD_BG}; border-right:1px solid {_BORDER}; padding:16px;"
    ):
        ui.label("SESSIONS").style(
            "color:#6272a4; font-size:11px; font-weight:600; letter-spacing:.08em;"
        )

        session_container = ui.column().classes("w-full q-mb-md gap-1")

        ui.separator().style("margin:12px 0; border-color:#2a2d3e;")

        ui.label("FILTER BY TYPE").style(
            "color:#6272a4; font-size:11px; font-weight:600; letter-spacing:.08em;"
        )
        for kind in EK:
            color = _Q_COLOR[kind]
            sw = (
                ui.switch(kind.value.upper(), value=True)
                .props(f"color={color} dense")
                .style("margin:2px 0;")
            )
            sw.on(
                "update:model-value",
                lambda v, k=kind: [filter_state.update({k: v}), rebuild_views()],
            )
            filter_state[kind] = True

        ui.separator().style("margin:12px 0; border-color:#2a2d3e;")

        ui.label("SLOW THRESHOLDS").style(
            "color:#6272a4; font-size:11px; font-weight:600; letter-spacing:.08em;"
        )
        ui.label("DB > 100ms").style("color:#ffa726; font-size:11px;")
        ui.label("LLM > 5s").style("color:#42a5f5; font-size:11px;")
        ui.label("Redis > 20ms").style("color:#ab47bc; font-size:11px;")

    # ── Main area ─────────────────────────────────────────────────────────────
    with ui.column().classes("w-full").style("padding:16px 20px; gap:12px;"):
        # Metric strip
        metric_refs = _metrics_row({})

        # Tabs
        with (
            ui.tabs()
            .classes("w-full")
            .props("dense align=left")
            .style(f"border-bottom:1px solid {_BORDER};") as tabs
        ):
            for name, label, icon_name in [
                ("timeline", "Timeline", "timeline"),
                ("llm", "LLM", "smart_toy"),
                ("db", "Database", "storage"),
                ("redis", "Redis", "bolt"),
                ("tools", "Tools", "build"),
                ("agent", "Agent", "account_tree"),
                ("errors", "Errors", "error_outline"),
                ("allergens", "Allergens", "warning"),
                ("pricing", "Pricing", "sell"),
            ]:
                with ui.tab(name, label=label, icon=icon_name).props("no-caps"):
                    pass

        with (
            ui.tab_panels(tabs, value="timeline").classes("w-full").style("background:transparent;")
        ):
            with ui.tab_panel("timeline"):
                tl_refs = _tab_timeline(filter_state)
            with ui.tab_panel("llm"):
                llm_refs = _tab_llm()
            with ui.tab_panel("db"):
                db_refs = _tab_db()
            with ui.tab_panel("redis"):
                redis_refs = _tab_redis()
            with ui.tab_panel("tools"):
                tool_refs = _tab_tools()
            with ui.tab_panel("agent"):
                agent_refs = _tab_agent()
            with ui.tab_panel("errors"):
                err_refs = _tab_errors()
            with ui.tab_panel("allergens"):
                allergens_refs = _tab_allergens()
            with ui.tab_panel("pricing"):
                pricing_refs = _tab_pricing()

    # ── Helper: select session filter ──
    def select_session_filter(sid: str | None):
        filter_state["session_id"] = sid
        rebuild_views()

    # ── Helper: render sidebar sessions ──
    def render_sidebar_sessions():
        current_sessions = bus.sessions()
        selected_sid = filter_state.get("session_id")

        with session_container:
            session_container.clear()

            # Add "All Sessions" option
            is_all_active = selected_sid is None
            with (
                ui.row()
                .classes("items-center gap-1 q-pa-xs cursor-pointer w-full")
                .style(
                    f"background:{_BORDER if is_all_active else 'transparent'}; border-radius:6px; padding:6px 8px;"
                ) as row_all
            ):
                ui.icon("people", size="14px", color="cyan" if is_all_active else "grey")
                ui.label("All Sessions").style(
                    f"color:{'#e2e8f0' if is_all_active else '#6272a4'}; font-size:11px; flex:1; font-weight:{'600' if is_all_active else 'normal'};"
                )
                row_all.on("click", lambda: select_session_filter(None))

            # Add individual sessions
            for sid in current_sessions[:12]:
                is_selected = selected_sid == sid
                count = len(bus.by_session(sid))
                with (
                    ui.row()
                    .classes("items-center gap-1 q-pa-xs cursor-pointer w-full")
                    .style(
                        f"background:{_BORDER if is_selected else 'transparent'}; border-radius:6px; padding:6px 8px;"
                    ) as row_sid
                ):
                    ui.icon("person", size="14px", color="cyan" if is_selected else "grey")
                    ui.label(sid[:8]).style(
                        f"color:{'#e2e8f0' if is_selected else '#6272a4'}; font-size:11px; flex:1; font-family:var(--mono); font-weight:{'600' if is_selected else 'normal'};"
                    )
                    ui.badge(str(count), color="cyan" if is_selected else "grey").props(
                        "rounded dense"
                    )
                    row_sid.on("click", lambda s=sid: select_session_filter(s))

    # ── Helper: update metrics strip ──
    def update_metrics():
        selected_sid = filter_state.get("session_id")
        for key, (label, getter, fmt) in metric_refs.items():
            try:
                if selected_sid:
                    session_events = bus.by_session(selected_sid)
                    if key == "total":
                        val = len(session_events)
                    elif key == "errors":
                        val = sum(1 for e in session_events if e.is_error)
                    elif key == "llm_avg":
                        llm_durs = [
                            e.duration_ms
                            for e in session_events
                            if e.kind == EK.LLM and e.duration_ms
                        ]
                        val = sum(llm_durs) / len(llm_durs) if llm_durs else None
                    elif key == "db_avg":
                        db_durs = [
                            e.duration_ms
                            for e in session_events
                            if e.kind == EK.DB and e.duration_ms
                        ]
                        val = sum(db_durs) / len(db_durs) if db_durs else None
                    elif key == "redis_avg":
                        redis_durs = [
                            e.duration_ms
                            for e in session_events
                            if e.kind == EK.REDIS and e.duration_ms
                        ]
                        val = sum(redis_durs) / len(redis_durs) if redis_durs else None
                    elif key == "tools_avg":
                        tool_durs = [
                            e.duration_ms
                            for e in session_events
                            if e.kind == EK.TOOL and e.duration_ms
                        ]
                        val = sum(tool_durs) / len(tool_durs) if tool_durs else None
                    elif key == "cache_rate":
                        redis_events = [e for e in session_events if e.kind == EK.REDIS]
                        hits = sum(1 for e in redis_events if e.detail.get("hit") is True)
                        misses = sum(1 for e in redis_events if e.detail.get("hit") is False)
                        total = hits + misses
                        val = round(hits / total * 100, 1) if total else None
                else:
                    val = getter()
                label.set_text(fmt(val) if val is not None else "—")
            except Exception:
                pass

    # ── Helper: rebuild all dashboard views ──
    def rebuild_views():
        # Clear timeline
        tl_refs["event_col"].clear()

        # Determine filtered events
        sid = filter_state.get("session_id")
        events = bus.all_events()
        if sid:
            events = [e for e in events if e.session_id == sid]

        # 1. Timeline: Seed with filtered events
        filtered_recent = events[-80:]
        for ev in filtered_recent:
            if filter_state.get(ev.kind, True):
                _event_card(ev, tl_refs["event_col"])
        tl_refs["scroll"].scroll_to(percent=1.0)

        # 2. LLM Tab: Re-populate rows
        if "tbl" in llm_refs:
            llm_events = [e for e in events if e.kind == EK.LLM]
            llm_refs["tbl"].rows = [
                {
                    "ts": e.ts.strftime("%H:%M:%S"),
                    "title": e.title[:60],
                    "duration": e.dur_str,
                    "session": e.session_short,
                    "error": "✗" if e.is_error else "",
                    "_detail": json.dumps(e.detail, default=str),
                }
                for e in reversed(llm_events)
            ]
            llm_refs["tbl"].update()

        # 3. DB Tab: Re-populate rows
        if "tbl" in db_refs:
            db_events = [e for e in events if e.kind == EK.DB]
            db_refs["tbl"].rows = [
                {
                    "ts": e.ts.strftime("%H:%M:%S"),
                    "op": e.detail.get("operation", "?"),
                    "table": e.detail.get("table", "?"),
                    "sql": (e.detail.get("sql") or "")[:70],
                    "duration": e.dur_str,
                    "dur_raw": e.duration_ms or 0,
                    "session": e.session_short,
                }
                for e in reversed(db_events)
            ]
            db_refs["tbl"].update()

        # 4. Redis Tab: Re-populate rows and recalculate hit rates
        if "tbl" in redis_refs:
            redis_events = [e for e in events if e.kind == EK.REDIS]
            redis_refs["tbl"].rows = [
                {
                    "ts": e.ts.strftime("%H:%M:%S"),
                    "op": e.detail.get("op", "?"),
                    "key": e.detail.get("key", ""),
                    "hit": "HIT ✓"
                    if e.detail.get("hit") is True
                    else ("MISS ✗" if e.detail.get("hit") is False else "—"),
                    "ttl": str(e.detail.get("ttl", "—")),
                    "dur": e.dur_str,
                    "session": e.session_short,
                }
                for e in reversed(redis_events)
            ]
            redis_refs["tbl"].update()

            hit_total = sum(1 for e in redis_events if e.detail.get("hit") is True)
            miss_total = sum(1 for e in redis_events if e.detail.get("hit") is False)
            total_hm = hit_total + miss_total
            rate = round(hit_total / total_hm * 100) if total_hm else 0
            if "hit_label" in redis_refs:
                redis_refs["hit_label"].set_text(f"{rate}%")
            if "hm_label" in redis_refs:
                redis_refs["hm_label"].set_text(f"{hit_total} / {miss_total}")

        # 5. Tools Tab: Re-populate rows
        if "tbl" in tool_refs:
            tool_events = [e for e in events if e.kind == EK.TOOL]
            tool_refs["tbl"].rows = [
                {
                    "ts": e.ts.strftime("%H:%M:%S"),
                    "tool": e.detail.get("tool", e.title[:40]),
                    "input": str(e.detail.get("input", ""))[:60],
                    "output": str(e.detail.get("output", ""))[:60],
                    "dur": e.dur_str,
                    "ok": "✗" if e.is_error else "✓",
                    "session": e.session_short,
                }
                for e in reversed(tool_events)
            ]
            tool_refs["tbl"].update()

        # 6. Errors Tab: Re-populate
        if "err_col" in err_refs:
            err_refs["err_col"].clear()
            error_events = [e for e in events if e.is_error]
            for ev in reversed(error_events[-100:]):
                _event_card(ev, err_refs["err_col"])
            if "no_errors_label" in err_refs:
                err_refs["no_errors_label"].set_visibility(len(error_events) == 0)

        # 8. Allergens Tab: Re-populate rows
        if "tbl" in allergens_refs:
            allergen_events = [e for e in events if e.kind == EK.ALLERGEN]
            allergens_refs["tbl"].rows = [
                {
                    "ts": e.ts.strftime("%H:%M:%S"),
                    "item": e.detail.get("item", e.title),
                    "allergens": ", ".join(e.detail.get("allergens", [])),
                    "session": e.session_short,
                }
                for e in reversed(allergen_events)
            ]
            allergens_refs["tbl"].update()

        # 9. Pricing Tab: Re-populate rows
        if "tbl" in pricing_refs:
            pricing_events = [e for e in events if e.kind == EK.PRICING]
            pricing_refs["tbl"].rows = [
                {
                    "ts": e.ts.strftime("%H:%M:%S"),
                    "item": e.detail.get("item", ""),
                    "rule": e.detail.get("rule", ""),
                    "original": f"${e.detail.get('original', 0.0):.2f}",
                    "final": f"${e.detail.get('final', 0.0):.2f}",
                    "discount": f"{round((1 - e.detail.get('final', 0.0)/e.detail.get('original', 1.0)) * 100)}%" if e.detail.get('original', 0.0) > 0 else "0%",
                    "session": e.session_short,
                }
                for e in reversed(pricing_events)
            ]
            pricing_refs["tbl"].update()

        # 7. Update metric strip and sidebar sessions list
        render_sidebar_sessions()
        update_metrics()

    # ── Update timer: 200ms polling ───────────────────────────────────────────
    first_tick = True

    def tick():
        nonlocal first_tick
        if not pending_events and not first_tick:
            return

        first_tick = False

        # Drain the queue
        batch = pending_events[:]
        pending_events.clear()

        # ── Filter by selected session if active ──
        selected_sid = filter_state.get("session_id")

        # ── Timeline ──
        for ev in batch:
            if selected_sid and ev.session_id != selected_sid:
                continue
            if filter_state.get(ev.kind, True):
                _event_card(ev, tl_refs["event_col"])
                # Auto-scroll
                tl_refs["scroll"].scroll_to(percent=1.0)

        # ── Update Individual Tabs ──
        for ev in batch:
            if selected_sid and ev.session_id != selected_sid:
                continue

            # Update error tab if it's an error event
            if ev.is_error and "err_col" in err_refs:
                _event_card(ev, err_refs["err_col"])
                if "no_errors_label" in err_refs:
                    err_refs["no_errors_label"].set_visibility(False)

            if ev.kind == EK.LLM and "tbl" in llm_refs:
                new_row = {
                    "ts": ev.ts.strftime("%H:%M:%S"),
                    "title": ev.title[:60],
                    "duration": ev.dur_str,
                    "session": ev.session_short,
                    "error": "✗" if ev.is_error else "",
                    "_detail": json.dumps(ev.detail, default=str),
                }
                llm_refs["tbl"].rows.insert(0, new_row)
                llm_refs["tbl"].update()

            elif ev.kind == EK.DB and "tbl" in db_refs:
                new_row = {
                    "ts": ev.ts.strftime("%H:%M:%S"),
                    "op": ev.detail.get("operation", "?"),
                    "table": ev.detail.get("table", "?"),
                    "sql": (ev.detail.get("sql") or "")[:70],
                    "duration": ev.dur_str,
                    "dur_raw": ev.duration_ms or 0,
                    "session": ev.session_short,
                }
                db_refs["tbl"].rows.insert(0, new_row)
                db_refs["tbl"].update()

            elif ev.kind == EK.REDIS and "tbl" in redis_refs:
                new_row = {
                    "ts": ev.ts.strftime("%H:%M:%S"),
                    "op": ev.detail.get("op", "?"),
                    "key": ev.detail.get("key", ""),
                    "hit": "HIT ✓"
                    if ev.detail.get("hit") is True
                    else ("MISS ✗" if ev.detail.get("hit") is False else "—"),
                    "ttl": str(ev.detail.get("ttl", "—")),
                    "dur": ev.dur_str,
                    "session": ev.session_short,
                }
                redis_refs["tbl"].rows.insert(0, new_row)
                redis_refs["tbl"].update()

                # Recalculate hit rates
                hit_total = sum(1 for e in bus.by_kind(EK.REDIS) if e.detail.get("hit") is True)
                miss_total = sum(1 for e in bus.by_kind(EK.REDIS) if e.detail.get("hit") is False)
                total_hm = hit_total + miss_total
                rate = round(hit_total / total_hm * 100) if total_hm else 0
                if "hit_label" in redis_refs:
                    redis_refs["hit_label"].set_text(f"{rate}%")
                if "hm_label" in redis_refs:
                    redis_refs["hm_label"].set_text(f"{hit_total} / {miss_total}")

            elif ev.kind == EK.TOOL and "tbl" in tool_refs:
                new_row = {
                    "ts": ev.ts.strftime("%H:%M:%S"),
                    "tool": ev.detail.get("tool", ev.title[:40]),
                    "input": str(ev.detail.get("input", ""))[:60],
                    "output": str(ev.detail.get("output", ""))[:60],
                    "dur": ev.dur_str,
                    "ok": "✗" if ev.is_error else "✓",
                    "session": ev.session_short,
                }
                tool_refs["tbl"].rows.insert(0, new_row)
                tool_refs["tbl"].update()

            elif ev.kind == EK.ALLERGEN and "tbl" in allergens_refs:
                new_row = {
                    "ts": ev.ts.strftime("%H:%M:%S"),
                    "item": ev.detail.get("item", ev.title),
                    "allergens": ", ".join(ev.detail.get("allergens", [])),
                    "session": ev.session_short,
                }
                allergens_refs["tbl"].rows.insert(0, new_row)
                allergens_refs["tbl"].update()

            elif ev.kind == EK.PRICING and "tbl" in pricing_refs:
                new_row = {
                    "ts": ev.ts.strftime("%H:%M:%S"),
                    "item": ev.detail.get("item", ""),
                    "rule": ev.detail.get("rule", ""),
                    "original": f"${ev.detail.get('original', 0.0):.2f}",
                    "final": f"${ev.detail.get('final', 0.0):.2f}",
                    "discount": f"{round((1 - ev.detail.get('final', 0.0)/ev.detail.get('original', 1.0)) * 100)}%" if ev.detail.get('original', 0.0) > 0 else "0%",
                    "session": ev.session_short,
                }
                pricing_refs["tbl"].rows.insert(0, new_row)
                pricing_refs["tbl"].update()

            elif ev.kind == EK.AGENT and "select" in agent_refs:
                # If this is the currently selected session in the dropdown, update the entire view
                if ev.session_id == agent_refs["select"].value:
                    agent_refs["load_session_fn"](ev.session_id)

        # ── Metrics strip ──
        update_metrics()

        # ── Sidebar sessions ──
        render_sidebar_sessions()

        # ── Error chip ──
        ec = bus.metrics.error_count()
        err_chip.set_text(f"{ec} error{'s' if ec != 1 else ''}")
        err_chip.props(f"color={'red' if ec > 0 else 'grey'} outline dense icon=error_outline")

        # ── Agent tab — refresh session list ──
        new_sessions = bus.sessions()
        if new_sessions and "select" in agent_refs:
            agent_refs["select"].options = new_sessions
            agent_refs["select"].update()

            # If the selected value was None or placeholder, auto-select the latest one
            if not agent_refs["select"].value or agent_refs["select"].value.startswith("("):
                agent_refs["select"].value = new_sessions[0]

        # ── Notify on errors ──
        for ev in batch:
            if ev.is_error:
                ui.notify(
                    f"[{ev.kind.value.upper()}] {ev.title[:60]}",
                    type="negative",
                    position="top-right",
                    timeout=4000,
                )

    ui.timer(0.2, tick)

    # ── Cleanup on browser disconnect ─────────────────────────────────────────
    async def on_disconnect():
        bus.unsubscribe(on_new_event)

    ui.on("disconnect", on_disconnect)


# ─────────────────────────────────────────────────────────────────────────────
# MOUNT
# ─────────────────────────────────────────────────────────────────────────────


def mount_dashboard(fastapi_app, mount_path: str = "/monitor") -> None:
    """
    Attach the NiceGUI monitoring dashboard to an existing FastAPI application.

    After calling this, the dashboard is live at:
        http://localhost:8000/monitor

    Call in api/main.py:
        from monitoring.dashboard import mount_dashboard
        mount_dashboard(app)
    """
    ui.page("/")(_build_page)

    ui.run_with(
        fastapi_app,
        mount_path=mount_path,
        storage_secret="restaurant-monitor-dev",  # change in production
        favicon="🔍",
        title="Dev Monitor",
        dark=True,
    )


def mount_dashboard_on_root(fastapi_app) -> None:
    """
    Register the developer monitoring dashboard page at '/monitor' on the shared NiceGUI app.
    Used when the main Web UI is mounted at the root '/'.
    """
    ui.page("/monitor")(_build_page)
