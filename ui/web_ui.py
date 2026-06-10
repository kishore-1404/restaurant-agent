"""
ui/web_ui.py  —  Restaurant AI customer web interface.

Pure NiceGUI — zero React, zero HTML files, zero JS boilerplate.
All styling lives in _CSS.  All logic is Python.

Pages
-----
  /          → restaurant selection (glassmorphic cards)
  /chat/{id} → full chat + live order sidebar

Mount in api/main.py
--------------------
    from ui.web_ui import mount_web_ui
    mount_web_ui(app)           # → http://localhost:8000/

Add to pyproject.toml
---------------------
    "nicegui>=1.4.33",
"""

from __future__ import annotations

import asyncio
import uuid
from typing import Optional

from nicegui import ui


# ─────────────────────────────────────────────────────────────────────────────
# RESTAURANT DATA
# ─────────────────────────────────────────────────────────────────────────────

RESTAURANTS: list[dict] = [
    {
        "id": 1,
        "name": "The Smokehouse",
        "emoji": "🍖",
        "cuisine": "American BBQ · Burgers",
        "tagline": "Slow-smoked perfection since day one",
        "color":   "#ff6b35",
        "rgb":     "255, 107, 53",
        "greeting": (
            "Howdy, partner! 🤠 Welcome to The Smokehouse. "
            "Our pitmasters have been at it since dawn — the BBQ Ribs Platter ($18.49) "
            "is 12 hours over hickory today. What can I fire up for you?"
        ),
    },
    {
        "id": 2,
        "name": "Bella Napoli",
        "emoji": "🍕",
        "cuisine": "Italian · Pizza · Pasta",
        "tagline": "Authentic Neapolitan cuisine, con amore",
        "color":   "#ff4757",
        "rgb":     "255, 71, 87",
        "greeting": (
            "Benvenuti a Bella Napoli! 🍷 So wonderful to have you this evening. "
            "The Margherita Classica ($13.99) is singing tonight — San Marzano, "
            "fior di latte, fresh basil. What calls to your heart?"
        ),
    },
    {
        "id": 3,
        "name": "Tokyo Bites",
        "emoji": "🍣",
        "cuisine": "Japanese · Sushi · Ramen",
        "tagline": "Precision. Freshness. Harmony.",
        "color":   "#00d2ff",
        "rgb":     "0, 210, 255",
        "greeting": (
            "Irasshaimase. 🙏 Our fish arrived this morning. "
            "The Tonkotsu broth has simmered 18 hours. "
            "The Salmon Sashimi ($16) is exceptional today. "
            "How may I guide you this evening?"
        ),
    },
]

_R_BY_ID: dict[int, dict] = {r["id"]: r for r in RESTAURANTS}

STAGES = ["greeting", "ordering", "confirming", "payment", "done"]
STAGE_LABELS = ["Greeting", "Ordering", "Confirming", "Payment", "Done"]


# ─────────────────────────────────────────────────────────────────────────────
# STYLESHEET  (injected once per page — transforms NiceGUI/Quasar into the
#              dark, glassmorphic, futuristic design we want)
# ─────────────────────────────────────────────────────────────────────────────

_CSS = """
/* ── Fonts ── */
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&family=JetBrains+Mono:wght@400;500&display=swap');

/* ── Base ── */
*, *::before, *::after { box-sizing: border-box; }

html, body {
    height: 100%;
    font-family: 'Inter', -apple-system, BlinkMacSystemFont, sans-serif !important;
    -webkit-font-smoothing: antialiased;
    overflow: hidden;
}

body.body--dark {
    background-color: #080b14 !important;
    background-image:
        radial-gradient(ellipse 100% 55% at 50% -5%,
            rgba(var(--accent-rgb, 99 102 241), 0.10) 0%, transparent 65%),
        linear-gradient(rgba(255,255,255,0.016) 1px, transparent 1px),
        linear-gradient(90deg, rgba(255,255,255,0.016) 1px, transparent 1px);
    background-size: 100% 100%, 44px 44px, 44px 44px;
    background-attachment: fixed;
    color: #e2e8f0 !important;
}

/* ── Scrollbar ── */
::-webkit-scrollbar          { width: 3px; height: 3px; }
::-webkit-scrollbar-track    { background: transparent; }
::-webkit-scrollbar-thumb    { background: rgba(255,255,255,0.14); border-radius: 2px; }
::-webkit-scrollbar-thumb:hover { background: rgba(255,255,255,0.28); }

/* ── NiceGUI / Quasar resets ── */
.q-page-container { padding: 0 !important; }
.q-layout { background: transparent !important; }
.q-card { border-radius: 16px !important; }
.q-separator { background: rgba(255,255,255,0.07) !important; }
.q-footer, .q-header { border: none !important; box-shadow: none !important; }

/* ── Glass surface utility ── */
.glass {
    background: rgba(255,255,255,0.045) !important;
    backdrop-filter: blur(24px) !important;
    -webkit-backdrop-filter: blur(24px) !important;
    border: 1px solid rgba(255,255,255,0.09) !important;
}

/* ── Page header ── */
.top-bar {
    background: rgba(8,11,20,0.85) !important;
    backdrop-filter: blur(24px) !important;
    border-bottom: 1px solid rgba(255,255,255,0.07) !important;
    height: 60px;
}

/* ── Restaurant selection cards ── */
.r-card {
    background: rgba(255,255,255,0.04) !important;
    backdrop-filter: blur(20px) !important;
    border: 1px solid rgba(255,255,255,0.08) !important;
    border-radius: 22px !important;
    cursor: pointer;
    transition:
        transform 0.30s cubic-bezier(0.4, 0, 0.2, 1),
        background 0.25s ease,
        box-shadow 0.30s ease;
    overflow: hidden;
}
.r-card:hover {
    transform: translateY(-8px) !important;
    background: rgba(255,255,255,0.07) !important;
}
.r-card-1:hover { box-shadow: 0 24px 64px rgba(255,107,53,0.22), 0 0 0 1px rgba(255,107,53,0.18) !important; }
.r-card-2:hover { box-shadow: 0 24px 64px rgba(255,71,87,0.22),  0 0 0 1px rgba(255,71,87,0.18)  !important; }
.r-card-3:hover { box-shadow: 0 24px 64px rgba(0,210,255,0.22),  0 0 0 1px rgba(0,210,255,0.18)  !important; }

/* ── Chat: Quasar q-message overrides ── */
.q-message-text {
    font-family: 'Inter', sans-serif !important;
    font-size: 14px !important;
    line-height: 1.65 !important;
}

/* AI bubble */
.q-message:not(.q-message--sent) .q-message-text--received {
    background: rgba(255,255,255,0.055) !important;
    border: 1px solid rgba(255,255,255,0.09) !important;
    border-radius: 4px 18px 18px 18px !important;
    color: #e2e8f0 !important;
    box-shadow: 0 2px 12px rgba(0,0,0,0.25) !important;
}

/* User bubble */
.q-message--sent .q-message-text--sent {
    background: var(--accent-color, #6366f1) !important;
    border-radius: 18px 4px 18px 18px !important;
    color: #ffffff !important;
    box-shadow: 0 4px 20px rgba(var(--accent-rgb, 99 102 241), 0.30) !important;
}

/* Avatar overrides */
.q-message-avatar { border-radius: 10px !important; }

/* Name labels */
.q-message-name { color: #64748b !important; font-size: 11px !important; margin-bottom: 2px !important; }

/* ── Streaming cursor ── */
.stream-cursor {
    display: inline-block;
    width: 2px;
    height: 1em;
    vertical-align: text-bottom;
    margin-left: 1px;
    background-color: var(--accent-color, #6366f1);
    border-radius: 1px;
    animation: blink-cursor 1s step-start infinite;
}
@keyframes blink-cursor { 0%, 100% { opacity: 1; } 50% { opacity: 0; } }

/* ── Chat input field ── */
.chat-input .q-field__control {
    background: rgba(255,255,255,0.05) !important;
    border: 1px solid rgba(255,255,255,0.10) !important;
    border-radius: 14px !important;
    min-height: 48px !important;
    transition: border-color 0.2s ease, box-shadow 0.2s ease;
}
.chat-input .q-field__control:focus-within {
    border-color: var(--accent-color, #6366f1) !important;
    box-shadow: 0 0 0 3px rgba(var(--accent-rgb, 99 102 241), 0.18) !important;
}
.chat-input .q-field__native,
.chat-input .q-field__input      { color: #e2e8f0 !important; font-size: 14px !important; }
.chat-input .q-field__label      { color: #64748b !important; }
.chat-input .q-field__marginal   { color: #64748b !important; }

/* ── Send button ── */
.send-btn {
    background: var(--accent-color, #6366f1) !important;
    box-shadow: 0 0 18px rgba(var(--accent-rgb, 99 102 241), 0.35) !important;
    transition: box-shadow 0.25s ease, transform 0.15s ease !important;
}
.send-btn:hover  { box-shadow: 0 0 30px rgba(var(--accent-rgb, 99 102 241), 0.55) !important; transform: scale(1.06) !important; }
.send-btn:active { transform: scale(0.96) !important; }

/* ── Stage progress dots ── */
.stage-track {
    display: flex;
    align-items: center;
    gap: 0;
}
.s-dot {
    width: 7px; height: 7px;
    border-radius: 50%;
    flex-shrink: 0;
    transition: all 0.4s ease;
}
.s-dot.done   { background: var(--accent-color); opacity: 0.6; }
.s-dot.active { background: var(--accent-color); box-shadow: 0 0 10px var(--accent-color); animation: dot-pulse 1.8s ease infinite; }
.s-dot.future { background: rgba(255,255,255,0.18); }
.s-line       { flex: 1; height: 1px; background: rgba(255,255,255,0.10); min-width: 12px; }
@keyframes dot-pulse { 0%,100% { box-shadow: 0 0 8px var(--accent-color); } 50% { box-shadow: 0 0 20px var(--accent-color); } }

/* ── Order sidebar ── */
.order-panel {
    background: rgba(255,255,255,0.03) !important;
    border-left: 1px solid rgba(255,255,255,0.07) !important;
}
.cart-row {
    animation: cart-slide 0.3s cubic-bezier(0.4,0,0.2,1);
}
@keyframes cart-slide { from { opacity:0; transform:translateX(10px); } to { opacity:1; transform:translateX(0); } }

/* ── Confirm button ── */
.confirm-btn {
    background: var(--accent-color) !important;
    color: #fff !important;
    border-radius: 12px !important;
    font-weight: 600 !important;
    letter-spacing: 0.02em !important;
    animation: confirm-glow 2.5s ease infinite;
}
@keyframes confirm-glow {
    0%,100% { box-shadow: 0 0 16px rgba(var(--accent-rgb), 0.30); }
    50%      { box-shadow: 0 0 36px rgba(var(--accent-rgb), 0.65); }
}

/* ── Receipt dialog ── */
.receipt-dialog .q-dialog__inner > div {
    background: #101420 !important;
    border: 1px solid rgba(255,255,255,0.10) !important;
    border-radius: 20px !important;
    box-shadow: 0 32px 80px rgba(0,0,0,0.8), 0 0 0 1px rgba(var(--accent-rgb),0.15) !important;
}

/* ── Hero text ── */
.hero-title {
    font-size: clamp(26px, 4vw, 42px);
    font-weight: 700;
    letter-spacing: -0.025em;
    color: #f1f5f9;
    line-height: 1.15;
}
.hero-sub {
    font-size: 16px;
    color: #4e6076;
    margin-top: 10px;
    font-weight: 400;
}

/* ── Micro animations ── */
@keyframes fade-up {
    from { opacity: 0; transform: translateY(14px); }
    to   { opacity: 1; transform: translateY(0); }
}
.fade-up { animation: fade-up 0.45s cubic-bezier(0.4,0,0.2,1) both; }
.fade-up-1 { animation-delay: 0.05s; }
.fade-up-2 { animation-delay: 0.12s; }
.fade-up-3 { animation-delay: 0.19s; }
"""


# ─────────────────────────────────────────────────────────────────────────────
# STYLE INJECTION
# ─────────────────────────────────────────────────────────────────────────────

def _inject(restaurant: dict | None = None) -> None:
    """Inject global CSS + per-restaurant CSS custom properties."""
    color = restaurant["color"] if restaurant else "#6366f1"
    rgb   = restaurant["rgb"]   if restaurant else "99, 102, 241"

    ui.dark_mode().enable()
    ui.add_head_html(f"""
<link rel="preconnect" href="https://fonts.googleapis.com">
<style>
{_CSS}
:root {{ --accent-color:{color}; --accent-rgb:{rgb}; }}
</style>
""")


# ─────────────────────────────────────────────────────────────────────────────
# SHARED UI PIECES
# ─────────────────────────────────────────────────────────────────────────────

def _logo_wordmark(back_url: str | None = None) -> None:
    """Top navigation bar used on all pages."""
    with ui.header().classes("top-bar flex items-center").style(
        "padding: 0 24px; min-height: 60px;"
    ):
        if back_url:
            ui.button(
                icon="arrow_back_ios_new", color="white",
                on_click=lambda: ui.navigate.to(back_url),
            ).props("flat round dense")

        ui.icon("restaurant_menu", color="white").props("size=22px")
        ui.label("RESTAURANT AI").style(
            "font-size:13px; font-weight:600; letter-spacing:.12em; color:#e2e8f0; margin-left:8px;"
        )
        ui.space()


def _stage_bar(stage_ref: list) -> ui.row:
    """
    Horizontal stage progress with dot + line track.
    stage_ref is a 1-element list so callers can mutate it: stage_ref[0] = 'ordering'
    """
    with ui.row().classes("stage-track items-center").style("gap:0;") as row:
        dots: list[ui.element] = []
        for i, (key, label) in enumerate(zip(STAGES, STAGE_LABELS)):
            dot = ui.element("div").classes("s-dot future").props(f'title="{label}"')
            dots.append(dot)
            if i < len(STAGES) - 1:
                ui.element("div").classes("s-line")

    def refresh(stage: str):
        idx = STAGES.index(stage) if stage in STAGES else 0
        for i, dot in enumerate(dots):
            dot.classes(remove="done active future")
            if i < idx:
                dot.classes(add="done")
            elif i == idx:
                dot.classes(add="active")
            else:
                dot.classes(add="future")

    refresh(stage_ref[0])
    return row, refresh


# ─────────────────────────────────────────────────────────────────────────────
# PAGE 1 — RESTAURANT SELECTION
# ─────────────────────────────────────────────────────────────────────────────

@ui.page("/")
async def select_page() -> None:
    _inject()
    _logo_wordmark()

    def make_click_handler(rid: int):
        return lambda _: ui.navigate.to(f"/chat/{rid}")

    # ── Hero ──────────────────────────────────────────────────────────────────
    with ui.column().classes("w-full items-center fade-up").style(
        "padding: 72px 24px 52px; text-align: center;"
    ):
        ui.label("Choose your dining experience").classes("hero-title")
        ui.label(
            "Powered by AI — personalised ordering for every restaurant"
        ).classes("hero-sub")

    # ── Cards ─────────────────────────────────────────────────────────────────
    with ui.row().classes("w-full justify-center").style(
        "padding: 0 24px 64px; gap: 28px; flex-wrap: wrap;"
    ):
        for delay_cls, r in zip(("fade-up-1", "fade-up-2", "fade-up-3"), RESTAURANTS):

            with ui.card().classes(
                f"r-card r-card-{r['id']} {delay_cls} fade-up"
            ).style(
                f"width: 290px; padding: 32px 28px;"
                f"border-top: 2px solid {r['color']};"
            ).on("click", make_click_handler(r["id"])):

                # Emoji + name
                ui.label(r["emoji"]).style(
                    "font-size:44px; line-height:1; margin-bottom:12px;"
                )
                ui.label(r["name"]).style(
                    "font-size:20px; font-weight:600; color:#f1f5f9; margin-bottom:4px;"
                )
                ui.label(r["cuisine"]).style(
                    "font-size:12px; color:#64748b; letter-spacing:.03em; margin-bottom:16px;"
                )

                ui.separator()

                ui.label(r["tagline"]).style(
                    "font-size:12px; color:#475569; font-style:italic; margin:12px 0 20px;"
                )

                # CTA button
                ui.button(
                    "Begin Order",
                    on_click=make_click_handler(r["id"]),
                ).style(
                    f"background:{r['color']} !important; color:#fff !important;"
                    f"border-radius:10px !important; font-weight:500 !important;"
                    f"width:100%; letter-spacing:.03em;"
                    f"box-shadow: 0 4px 20px rgba({r['rgb']}, 0.30);"
                ).props("no-caps unelevated")


# ─────────────────────────────────────────────────────────────────────────────
# PAGE 2 — CHAT
# ─────────────────────────────────────────────────────────────────────────────

@ui.page("/chat/{restaurant_id}")
async def chat_page(restaurant_id: int) -> None:

    r = _R_BY_ID.get(restaurant_id)
    if not r:
        return ui.navigate.to("/")

    _inject(r)

    # ── Per-connection state ───────────────────────────────────────────────────
    session_id = str(uuid.uuid4())[:8]
    state = {
        "restaurant_id":  restaurant_id,
        "session_id":     session_id,
        "stage":          "greeting",
        "cart":           [],     # [{name, price, qty}]
        "order_id":       None,
        "is_streaming":   False,
        "menu_text":      "",
    }

    # ── Header ────────────────────────────────────────────────────────────────
    _logo_wordmark(back_url="/")

    with ui.header().classes("top-bar flex items-center").style(
        "padding: 0 24px; min-height: 60px; top: 60px;"
    ):
        ui.label(r["emoji"]).style("font-size:22px; margin-right:8px;")
        ui.label(r["name"]).style(
            "font-size:15px; font-weight:600; color:#f1f5f9;"
        )
        ui.space()

        # Stage dots (centre of header)
        stage_ref = [state["stage"]]
        _, update_stage_bar = _stage_bar(stage_ref)

        ui.space()

        # Session chip
        ui.chip(
            f"#{session_id}", icon="fiber_manual_record",
            color="grey",
        ).props("outline dense").style("font-size:10px;")

    # ── Main layout ───────────────────────────────────────────────────────────
    with ui.row().classes("w-full").style(
        "height: calc(100vh - 120px); overflow: hidden; gap: 0;"
    ):

        # ── LEFT: chat area ───────────────────────────────────────────────────
        with ui.column().classes("flex-1").style(
            "display:flex; flex-direction:column; overflow:hidden; height:100%;"
        ):
            # Scrollable messages
            scroll = ui.scroll_area().style(
                "flex:1; min-height:0; padding: 24px 28px; overflow-y:auto;"
            )
            with scroll:
                chat_col = ui.column().classes("w-full").style("gap:16px;")

            # Input row
            with ui.row().classes("w-full items-center").style(
                "padding: 14px 24px; gap: 12px; flex-shrink:0;"
                "border-top: 1px solid rgba(255,255,255,0.06);"
                "background: rgba(8,11,20,0.6); backdrop-filter:blur(12px);"
            ):
                chat_input = (
                    ui.input(placeholder=f"Message {r['name']}…")
                    .classes("flex-1 chat-input")
                    .props("outlined dense autofocus")
                    .style("font-size:14px;")
                )
                send_btn = (
                    ui.button(icon="arrow_upward")
                    .classes("send-btn")
                    .props("round unelevated")
                    .style("width:44px; height:44px; flex-shrink:0;")
                )

        # ── RIGHT: order sidebar ──────────────────────────────────────────────
        with ui.column().classes("order-panel").style(
            "width:320px; flex-shrink:0; height:100%; overflow-y:auto;"
            "display:flex; flex-direction:column; padding:20px 20px;"
        ):
            # Title row
            with ui.row().classes("items-center w-full").style("margin-bottom:16px;"):
                ui.icon("receipt_long", color="white").props("size=18px")
                ui.label("Your Order").style(
                    "font-size:14px; font-weight:600; color:#e2e8f0; margin-left:8px;"
                )
                ui.space()
                order_count_badge = ui.badge("0", color="grey").props("rounded")

            # Cart items container
            cart_col = ui.column().classes("w-full").style("gap:8px; flex:1;")

            # Empty state
            empty_label = ui.label("Your cart is empty").style(
                "font-size:13px; color:#334155; text-align:center; padding:32px 0;"
            )

            ui.separator().style("margin:12px 0;")

            # Total row
            with ui.row().classes("w-full items-center"):
                ui.label("Total").style("font-size:13px; color:#64748b;")
                ui.space()
                total_label = ui.label("$0.00").style(
                    f"font-size:22px; font-weight:700; color:{r['color']};"
                    "letter-spacing:-0.01em;"
                )

            # Confirm button (hidden until confirming stage)
            confirm_btn = (
                ui.button(
                    "Confirm & Place Order",
                    icon="check_circle",
                )
                .classes("confirm-btn w-full")
                .props("no-caps unelevated")
                .style("margin-top:16px; padding:12px; display:none;")
            )

            # Done state
            done_col = ui.column().classes("w-full items-center").style(
                "gap:8px; padding:16px 0; display:none;"
            )
            with done_col:
                ui.icon("check_circle", color="positive").props("size=40px")
                ui.label("Order Placed!").style(
                    "font-size:16px; font-weight:600; color:#4ade80;"
                )
                ui.label("Sent to kitchen").style(
                    "font-size:12px; color:#64748b;"
                )

    # ─────────────────────────────────────────────────────────────────────────
    # HELPER: add an AI chat bubble
    # ─────────────────────────────────────────────────────────────────────────

    def _ai_bubble_static(text: str):
        """Render a completed AI message."""
        with chat_col:
            ui.chat_message(
                text=text,
                name=r["name"],
                stamp=_now(),
                avatar=r["emoji"],
                sent=False,
                text_html=False,
            )
        scroll.scroll_to(percent=1.0)

    def _user_bubble(text: str):
        """Render a user message."""
        with chat_col:
            ui.chat_message(
                text=text,
                name="You",
                stamp=_now(),
                sent=True,
            )
        scroll.scroll_to(percent=1.0)

    async def _ai_bubble_stream(generator) -> str:
        """
        Create a streaming AI bubble.  Iterates the async generator,
        appending tokens to a label inside the bubble.
        Returns the full text when done.
        """
        with chat_col:
            msg = ui.chat_message(
                text="",
                name=r["name"],
                stamp=_now(),
                avatar=r["emoji"],
                sent=False,
            )
        with msg:
            stream_lbl = ui.label("").style(
                "white-space:pre-wrap; color:#e2e8f0; font-size:14px; line-height:1.65; display:inline;"
            )
            cursor = ui.html('<span class="stream-cursor"></span>')

        full = ""
        async for token in generator:
            full += token
            stream_lbl.set_text(full)
            scroll.scroll_to(percent=1.0)
            await asyncio.sleep(0)          # yield → WebSocket push

        cursor.delete()
        return full

    # ─────────────────────────────────────────────────────────────────────────
    # HELPER: refresh order sidebar
    # ─────────────────────────────────────────────────────────────────────────

    def _refresh_cart():
        cart = state["cart"]
        cart_col.clear()
        empty_label.set_visibility(len(cart) == 0)
        order_count_badge.set_text(str(sum(i.get("qty") or i.get("quantity") or 1 for i in cart)))

        if cart:
            with cart_col:
                for item in cart:
                    with ui.row().classes("cart-row w-full items-center").style(
                        "background:rgba(255,255,255,0.04); border-radius:10px; padding:8px 12px;"
                    ):
                        with ui.column().style("flex:1; gap:1px;"):
                            ui.label(item["name"]).style(
                                "font-size:13px; color:#e2e8f0; font-weight:500;"
                            )
                            ui.label(f"${item['price']:.2f} each").style(
                                "font-size:11px; color:#64748b;"
                            )
                        qty = item.get("qty") or item.get("quantity") or 1
                        ui.label(f"×{qty}").style(
                            f"font-size:12px; color:{r['color']}; font-weight:600; margin:0 8px;"
                        )
                        ui.label(
                            f"${item['price'] * qty:.2f}"
                        ).style("font-size:13px; color:#e2e8f0; font-weight:500;")

        total = sum(i["price"] * (i.get("qty") or i.get("quantity") or 1) for i in cart)
        total_label.set_text(f"${total:.2f}")

        # Show/hide confirm button based on stage
        show_confirm = state["stage"] == "confirming" and len(cart) > 0
        confirm_btn.style(
            f"margin-top:16px; padding:12px; display:{'flex' if show_confirm else 'none'};"
        )

        # Show done state
        if state["stage"] == "done":
            confirm_btn.style("display:none;")
            done_col.style("gap:8px; padding:16px 0; display:flex;")

    # ─────────────────────────────────────────────────────────────────────────
    # AGENT STREAMING
    # ─────────────────────────────────────────────────────────────────────────

    async def _call_agent(user_text: str):
        """
        Stream a response from the LangGraph agent.
        Falls back to a simulated stream if backend is unavailable.
        """
        try:
            from langchain_core.messages import HumanMessage
            from core.graph import graph
            from monitoring.hooks import MonitorCallback

            config = {
                "configurable": {"thread_id": state["session_id"]},
                "callbacks": [MonitorCallback(session_id=state["session_id"])],
            }

            async def _token_gen():
                async for event in graph.astream_events(
                    {"messages": [HumanMessage(content=user_text)]},
                    config=config,
                    version="v2",
                ):
                    if event["event"] == "on_chat_model_stream":
                        chunk = event["data"]["chunk"]
                        if chunk.content:
                            yield chunk.content
                    elif event["event"] == "on_chain_end":
                        out = event["data"].get("output") or {}
                        if isinstance(out, dict):
                            if "cart" in out:
                                state["cart"]  = out["cart"]
                            if "stage" in out:
                                state["stage"] = out["stage"]
                                update_stage_bar(state["stage"])

            return _token_gen()

        except Exception:
            # Graceful degradation — simulate a response
            return _mock_stream(user_text, r)

    # ─────────────────────────────────────────────────────────────────────────
    # SEND HANDLER
    # ─────────────────────────────────────────────────────────────────────────

    async def handle_send():
        text = chat_input.value.strip()
        if not text or state["is_streaming"]:
            return

        chat_input.set_value("")
        state["is_streaming"] = True
        send_btn.props("disabled")
        chat_input.props("disabled")

        _user_bubble(text)

        generator = await _call_agent(text)
        await _ai_bubble_stream(generator)

        _refresh_cart()

        state["is_streaming"] = False
        send_btn.props(remove="disabled")
        chat_input.props(remove="disabled")
        chat_input.run_method("focus")

    # Wire send button + Enter key
    send_btn.on("click", handle_send)
    chat_input.on("keydown.enter", handle_send)

    # Confirm order handler
    async def handle_confirm():
        confirm_btn.props("disabled loading")
        try:
            if state.get("order_id"):
                from db.base import AsyncSessionFactory
                from services.order_service import OrderService
                async with AsyncSessionFactory() as db:
                    await OrderService.confirm_order(db, state["order_id"])
                    await db.commit()
        except Exception:
            pass
        state["stage"] = "done"
        update_stage_bar("done")
        _refresh_cart()
        _show_receipt()

    confirm_btn.on("click", handle_confirm)

    # ─────────────────────────────────────────────────────────────────────────
    # RECEIPT DIALOG
    # ─────────────────────────────────────────────────────────────────────────

    def _show_receipt():
        with ui.dialog().classes("receipt-dialog") as dlg, \
             ui.card().style(
                "min-width:380px; padding:32px; background:#101420 !important;"
             ):

            with ui.row().classes("w-full items-center").style("margin-bottom:20px;"):
                ui.icon("check_circle", color="positive").props("size=28px")
                ui.label("Order Confirmed").style(
                    "font-size:18px; font-weight:600; color:#4ade80; margin-left:10px;"
                )

            ui.separator()

            for item in state["cart"]:
                with ui.row().classes("w-full").style("padding:6px 0;"):
                    ui.label(item["name"]).style("flex:1; font-size:13px; color:#cbd5e1;")
                    qty = item.get("qty") or item.get("quantity") or 1
                    ui.label(f"×{qty}").style(
                        f"font-size:13px; color:{r['color']}; margin:0 12px;"
                    )
                    ui.label(
                        f"${item['price'] * qty:.2f}"
                    ).style("font-size:13px; color:#e2e8f0; font-weight:500;")

            ui.separator().style("margin:12px 0;")

            with ui.row().classes("w-full"):
                ui.label("Total").style("flex:1; font-size:15px; font-weight:600; color:#e2e8f0;")
                total = sum(i["price"] * (i.get("qty") or i.get("quantity") or 1) for i in state["cart"])
                ui.label(f"${total:.2f}").style(
                    f"font-size:22px; font-weight:700; color:{r['color']};"
                )

            ui.button("Done", on_click=dlg.close).style(
                f"margin-top:20px; width:100%; background:{r['color']} !important;"
                "color:#fff !important; border-radius:10px !important;"
            ).props("no-caps unelevated")

        dlg.open()

    # ─────────────────────────────────────────────────────────────────────────
    # INITIALISE — load menu + show greeting
    # ─────────────────────────────────────────────────────────────────────────

    async def _init():
        # Try to load real menu from DB
        try:
            from db.base import AsyncSessionFactory
            from services.menu_service import MenuService
            from services.order_service import OrderService
            async with AsyncSessionFactory() as db:
                menu = await MenuService.get_menu(db, restaurant_id)
                state["menu_text"] = _format_menu(menu)
                order = await OrderService.create_order(
                    db, restaurant_id, state["session_id"]
                )
                await db.commit()
                state["order_id"] = order.id

                # Initialize/seed LangGraph checkpointer state
                from core.graph import graph
                config = {"configurable": {"thread_id": state["session_id"]}}
                await graph.aupdate_state(
                    config,
                    {
                        "restaurant_id": restaurant_id,
                        "session_id": state["session_id"],
                        "customer_name": None,
                        "cart": [],
                        "order_id": order.id,
                        "stage": "greeting",
                        "menu_text": state["menu_text"],
                        "messages": [],
                    }
                )
        except Exception as e:
            state["menu_text"] = f"(menu unavailable in dev mode: {e})"

        # Show greeting — stream it character by character for the wow effect
        async def _greet():
            for char in r["greeting"]:
                yield char
                await asyncio.sleep(0.018)

        await _ai_bubble_stream(_greet())
        _refresh_cart()

    ui.timer(0.1, _init, once=True)


# ─────────────────────────────────────────────────────────────────────────────
# UTILITIES
# ─────────────────────────────────────────────────────────────────────────────

def _now() -> str:
    from datetime import datetime
    return datetime.now().strftime("%H:%M")


def _format_menu(menu: dict) -> str:
    lines = []
    for cat, items in menu.items():
        lines.append(f"\n[{cat.upper()}]")
        for it in items:
            lines.append(f"  • {it['name']} — ${it['price']:.2f}")
    return "\n".join(lines)


async def _mock_stream(user_text: str, r: dict):
    """
    Fallback: simulated streaming response used when backend is unavailable.
    Lets the UI be developed/tested without a running LangGraph instance.
    """
    t = user_text.lower()
    if any(w in t for w in ["hi", "hello", "hey", "start"]):
        resp = f"Welcome! I'm your AI assistant for {r['name']}. How can I help you order today?"
    elif any(w in t for w in ["menu", "what", "options", "have"]):
        resp = f"We have a wonderful selection! Ask me about any item and I'll add it to your order."
    elif any(w in t for w in ["confirm", "place", "order", "done", "yes"]):
        resp = "Your order is confirmed and heading to the kitchen! 🎉 Thank you for choosing us."
    else:
        resp = f"Great choice! I've noted that for your order. Anything else you'd like to add?"

    async def _gen():
        for char in resp:
            yield char
            await asyncio.sleep(0.018)

    return _gen()


# ─────────────────────────────────────────────────────────────────────────────
# MOUNT
# ─────────────────────────────────────────────────────────────────────────────

def mount_web_ui(fastapi_app=None) -> None:
    """
    Attach the customer web UI to an existing FastAPI application.

    With FastAPI (api/main.py):
        from ui.web_ui import mount_web_ui
        mount_web_ui(app)
        # UI at http://localhost:8000/

    Standalone for development:
        from ui.web_ui import mount_web_ui
        mount_web_ui()
        # Starts its own Uvicorn at http://localhost:8080/
    """
    if fastapi_app:
        ui.run_with(
            fastapi_app,
            mount_path="/",
            storage_secret="restaurant-ui-secret",   # change in production
            favicon="🍽",
            title="Restaurant AI",
            dark=True,
        )
    else:
        ui.run(
            host="0.0.0.0",
            port=8080,
            title="Restaurant AI",
            favicon="🍽",
            dark=True,
            reload=False,
        )
