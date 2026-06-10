"""
ui/terminal.py — Restaurant AI Ordering System Terminal UI

Layout:
┌──────────────────────────────────────────────────────────────────────┐
│  🍽  The Smokehouse     ▶ Ordering     ⚡ Gemini     Order #5        │
├────────────────────────────────────────┬─────────────────────────────┤
│                                        │  ✓ 👋 Greeting              │
│  12:31  You   I'll have BBQ ribs       │  ▶ 🍽  Ordering             │
│                                        │     🔍 Confirming           │
│  12:31  🤖   Great choice partner!     │     💳 Payment              │
│              The ribs are slow-smoked  │     ✅ Complete             │
│              for 12 hours. Want sides? │                             │
│                                        │  ─────────────────────────  │
│  12:32  You   Add loaded fries too     │  BBQ Ribs Platter    $18.49 │
│                                        │  Loaded Fries         $5.99 │
│  12:32  🤖▌  (streaming…)             │  Chocolate Milkshake  $5.49 │
│                                        │  ─────────────────────────  │
│                                        │  Total               $29.97 │
└────────────────────────────────────────┴─────────────────────────────┘
You: ▌
"""

import logging
import sys
import time
from contextlib import contextmanager
from datetime import datetime
from typing import Optional

from rich.align import Align
from rich.console import Console, Group
from rich.layout import Layout
from rich.live import Live
from rich.panel import Panel
from rich.rule import Rule
from rich.table import Table
from rich.text import Text
from rich import box


# ─────────────────────────────────────────────────────────────────────────────
# LOGGING — keep SQLAlchemy / httpx / LangChain noise out of the terminal
# ─────────────────────────────────────────────────────────────────────────────

def configure_logging(log_file: str = "debug.log") -> None:
    """
    All logs → debug.log (full detail).
    Only WARNING+ → stderr (never stdout, never the Rich console).

    Call this once at process start, before any other imports that trigger
    logging.  The Rich Live display owns stdout entirely.
    """
    fmt = logging.Formatter(
        "%(asctime)s  %(name)-35s  %(levelname)-8s  %(message)s"
    )

    # Everything to file
    fh = logging.FileHandler(log_file, mode="a", encoding="utf-8")
    fh.setLevel(logging.DEBUG)
    fh.setFormatter(fmt)

    # Only warnings/errors to stderr (not stdout — Rich owns that)
    eh = logging.StreamHandler(sys.stderr)
    eh.setLevel(logging.WARNING)
    eh.setFormatter(fmt)

    root = logging.getLogger()
    root.setLevel(logging.DEBUG)
    root.handlers.clear()
    root.addHandler(fh)
    root.addHandler(eh)

    # Silence the noisiest namespaces at INFO level
    _silence = (
        "sqlalchemy.engine",
        "sqlalchemy.engine.Engine",
        "sqlalchemy.pool",
        "sqlalchemy.dialects",
        "sqlalchemy.orm",
        "httpx",
        "httpcore",
        "asyncio",
        "hpack",
        "h2",
        "langchain",
        "langchain_core",
        "langchain_google_genai",
        "langchain_ollama",
        "langchain_openai",
        "openai",
        "google.auth",
        "urllib3",
        "celery",
    )
    for name in _silence:
        logging.getLogger(name).setLevel(logging.WARNING)


configure_logging()


# ─────────────────────────────────────────────────────────────────────────────
# CONSTANTS
# ─────────────────────────────────────────────────────────────────────────────

STAGES: dict[str, tuple[str, str]] = {
    "greeting":   ("👋 Greeting",    "cyan"),
    "ordering":   ("🍽  Ordering",    "cyan"),
    "confirming": ("🔍 Confirming",   "yellow"),
    "payment":    ("💳 Payment",      "magenta"),
    "done":       ("✅ Complete",     "green"),
}

STAGE_ORDER = list(STAGES.keys())

# How often (seconds) to redraw during streaming — throttle to avoid flicker
_STREAM_REFRESH_INTERVAL = 0.05   # 20 fps max


# ─────────────────────────────────────────────────────────────────────────────
# MESSAGE STORE
# ─────────────────────────────────────────────────────────────────────────────

class _Message:
    __slots__ = ("role", "content", "ts")

    def __init__(self, role: str, content: str):
        self.role = role
        self.content = content
        self.ts = datetime.now().strftime("%H:%M")


# ─────────────────────────────────────────────────────────────────────────────
# MAIN UI CLASS
# ─────────────────────────────────────────────────────────────────────────────

class RestaurantUI:
    """
    Split-panel terminal UI.

    Typical usage
    -------------
    ui = RestaurantUI()
    ui.setup("The Smokehouse", "Gemini 1.5 Flash", order_id=5)

    ui.print_menu(menu_dict)          # prints once, before live layout starts

    with ui:                          # starts Live layout
        while True:
            text = ui.get_input()     # pauses Live, reads line, resumes

            if text.lower() == "quit":
                break

            ui.add_message("user", text)

            # Token-by-token streaming
            ui.begin_stream()
            async for token in llm_stream(text):
                ui.push_stream_token(token)
            ui.end_stream()

            ui.update_cart(cart, total)
            ui.set_stage("confirming")

    ui.print_receipt(order)           # called after with-block, outside Live
    """

    def __init__(self) -> None:
        self.console = Console(highlight=False)

        self._restaurant_name: str = "Restaurant"
        self._provider_name: str = ""
        self._order_id: Optional[int] = None

        self._messages: list[_Message] = []
        self._cart: list[dict] = []
        self._total: float = 0.0
        self._stage: str = "greeting"

        self._stream_buffer: str = ""
        self._is_streaming: bool = False

        self._live: Optional[Live] = None
        self._last_refresh: float = 0.0

    # ── Configuration ─────────────────────────────────────────────────────────

    def setup(
        self,
        restaurant_name: str,
        provider_name: str,
        order_id: int | None = None,
    ) -> None:
        self._restaurant_name = restaurant_name
        self._provider_name = provider_name
        self._order_id = order_id

    # ── Public state mutations ────────────────────────────────────────────────

    def add_message(self, role: str, content: str) -> None:
        """Append a completed message (user or assistant) to the chat."""
        self._messages.append(_Message(role, content))
        self._stream_buffer = ""
        self._is_streaming = False
        self._force_refresh()

    def begin_stream(self) -> None:
        """Signal that the assistant is about to start streaming tokens."""
        self._is_streaming = True
        self._stream_buffer = ""
        self._force_refresh()

    def push_stream_token(self, token: str) -> None:
        """
        Append one streaming token to the in-progress response bubble.
        Throttled to _STREAM_REFRESH_INTERVAL so fast local models don't flicker.
        """
        self._stream_buffer += token
        now = time.monotonic()
        if now - self._last_refresh >= _STREAM_REFRESH_INTERVAL:
            self._force_refresh()
            self._last_refresh = now

    def end_stream(self) -> None:
        """
        Commit the streamed buffer as a real assistant message.
        Called once streaming is complete.
        """
        if self._stream_buffer.strip():
            self.add_message("assistant", self._stream_buffer)
        self._is_streaming = False
        self._stream_buffer = ""
        self._force_refresh()

    def update_cart(self, cart: list[dict], total: float) -> None:
        """Refresh the sidebar with new cart contents."""
        self._cart = cart
        self._total = total
        self._force_refresh()

    def set_stage(self, stage: str) -> None:
        """Advance the conversation stage indicator in the header + sidebar."""
        if stage in STAGES:
            self._stage = stage
            self._force_refresh()

    # ── Input ─────────────────────────────────────────────────────────────────

    def get_input(self, prompt: str = "You") -> str:
        """
        Temporarily stop the Live layout, read a line of input, then restart.

        The Live display is paused during the input prompt so the cursor
        doesn't fight with the live-refresh redraws.  The layout reappears
        immediately after the user presses Enter.
        """
        if self._live:
            self._live.stop()

        try:
            value = self.console.input(f"\n[bold cyan]{prompt}:[/bold cyan] ").strip()
        except (EOFError, KeyboardInterrupt):
            value = "quit"
        finally:
            if self._live:
                self._live.start(refresh=True)

        return value

    # ── Pre-Live helpers ──────────────────────────────────────────────────────

    def print_menu(self, menu: dict) -> None:
        """
        Print the full menu to the console BEFORE the Live layout starts.
        It scrolls up naturally once the layout takes over the bottom portion.
        """
        self.console.print()
        self.console.rule(f"[bold green]Menu — {self._restaurant_name}[/bold green]")
        self.console.print()

        for category, items in menu.items():
            t = Table(
                title=f"[bold]{category}[/bold]",
                box=box.SIMPLE_HEAVY,
                border_style="dim",
                header_style="bold cyan",
                show_edge=True,
                padding=(0, 1),
            )
            t.add_column("Item", style="white", min_width=22)
            t.add_column("Description", style="dim", min_width=30)
            t.add_column("Tags", style="dim yellow", min_width=14)
            t.add_column("Price", style="green", justify="right")

            for item in items:
                tags = ", ".join(item.get("tags") or [])
                t.add_row(
                    item["name"],
                    (item.get("description") or "")[:38],
                    tags[:20] or "—",
                    f"${item['price']:.2f}",
                )
            self.console.print(t)

        self.console.print()
        self.console.rule("[dim]Start chatting below[/dim]")
        self.console.print()

    def print_receipt(self, order) -> None:
        """
        Print a final receipt panel.
        Always called OUTSIDE the Live context (after __exit__).
        """
        self.console.print()
        t = Table(box=box.MINIMAL, show_header=False, padding=(0, 1), expand=False)
        t.add_column("Item", style="white", min_width=25)
        t.add_column("Qty", style="cyan", justify="center")
        t.add_column("Price", style="green", justify="right")

        for item in order.items:
            t.add_row(
                item.name_snapshot,
                f"×{item.quantity}",
                f"${float(item.price_snapshot * item.quantity):.2f}",
            )

        t.add_row(Rule(), "", "")
        t.add_row(
            "[bold]TOTAL[/bold]", "",
            f"[bold green]${float(order.total):.2f}[/bold green]",
        )

        self.console.print(Panel(
            t,
            title=f"[bold green]✅  Order #{order.id} Confirmed[/bold green]",
            subtitle=f"[dim]Status: {order.status}[/dim]",
            border_style="green",
            padding=(1, 2),
        ))

    def print_restaurant_selector(self, restaurants: list) -> int:
        """Render a numbered list and return the chosen id. Called before Live."""
        self.console.print()
        self.console.rule("[bold]Choose a Restaurant[/bold]")
        self.console.print()

        t = Table(box=box.SIMPLE, show_header=False, padding=(0, 2))
        t.add_column("", style="bold cyan", justify="right")
        t.add_column("", style="white")
        t.add_column("", style="dim")

        for r in restaurants:
            t.add_row(str(r.id), r.name, r.cuisine_type)

        self.console.print(t)
        self.console.print()

        while True:
            raw = self.console.input("[bold]Enter number → [/bold]").strip()
            if raw.isdigit() and any(r.id == int(raw) for r in restaurants):
                return int(raw)
            self.console.print("[red]Invalid choice — try again.[/red]")

    def print_error(self, message: str) -> None:
        if self._live:
            self._live.stop()
        self.console.print(f"[bold red]✗  {message}[/bold red]")
        if self._live:
            self._live.start(refresh=True)

    # ── Context manager ───────────────────────────────────────────────────────

    def __enter__(self) -> "RestaurantUI":
        self._live = Live(
            self._build_layout(),
            console=self.console,
            refresh_per_second=8,
            screen=False,       # inline rendering, not full-screen takeover
            transient=False,    # keep the last frame visible after exit
            vertical_overflow="visible",
        )
        self._live.__enter__()
        return self

    def __exit__(self, *args) -> None:
        if self._live:
            self._live.__exit__(*args)
            self._live = None

    # ── Internal rendering ────────────────────────────────────────────────────

    def _force_refresh(self) -> None:
        if self._live:
            self._live.update(self._build_layout())

    def _build_layout(self) -> Layout:
        layout = Layout(name="root")
        layout.split_column(
            Layout(name="header", size=3),
            Layout(name="body"),
        )
        layout["body"].split_row(
            Layout(name="chat",    ratio=68),
            Layout(name="sidebar", ratio=32),
        )
        layout["header"].update(self._render_header())
        layout["chat"].update(self._render_chat())
        layout["sidebar"].update(self._render_sidebar())
        return layout

    # ── Header ────────────────────────────────────────────────────────────────

    def _render_header(self) -> Panel:
        stage_label, stage_style = STAGES.get(self._stage, ("●", "dim"))

        line = Text(overflow="ellipsis", no_wrap=True)
        line.append(f"  🍽  {self._restaurant_name}", style="bold green")
        line.append("   │   ", style="dim")
        line.append(stage_label, style=f"bold {stage_style}")
        line.append("   │   ", style="dim")
        line.append(f"⚡ {self._provider_name}", style="dim")
        if self._order_id is not None:
            line.append("   │   ", style="dim")
            line.append(f"Order #{self._order_id}", style="dim cyan")

        return Panel(
            Align(line, align="left", vertical="middle"),
            box=box.HORIZONTALS,
            style="on grey7",
            padding=(0, 0),
        )

    # ── Chat panel ────────────────────────────────────────────────────────────

    def _render_chat(self) -> Panel:
        """
        Renders the N most-recent messages that fit in the available height.
        Older messages scroll off the top — no manual scrolling needed.
        """
        # Estimate usable lines: terminal height minus header (3) + borders (4)
        term_h = self.console.size.height
        available_lines = max(term_h - 10, 6)

        renderables: list = []

        for msg in self._messages:
            if msg.role == "user":
                # Right-leaning: timestamp dim, name cyan, content white
                prefix = Text()
                prefix.append(f" {msg.ts}  ", style="dim")
                prefix.append("You  ", style="bold cyan")
                body = Text(msg.content, style="white", overflow="fold")
                renderables.append(prefix)
                renderables.append(Text(f"       {msg.content}", style="white", overflow="fold"))
                renderables.append(Text(""))
            else:
                prefix = Text()
                prefix.append(f" {msg.ts}  ", style="dim")
                prefix.append("🤖   ", style="bold blue")
                renderables.append(prefix)
                # Wrap long assistant messages at word boundaries
                words = msg.content.split()
                line, cols = [], 0
                max_cols = max(self.console.size.width * 68 // 100 - 12, 30)
                wrapped_lines = []
                for word in words:
                    if cols + len(word) + 1 > max_cols and line:
                        wrapped_lines.append("       " + " ".join(line))
                        line, cols = [word], len(word)
                    else:
                        line.append(word)
                        cols += len(word) + 1
                if line:
                    wrapped_lines.append("       " + " ".join(line))
                for wl in wrapped_lines:
                    renderables.append(Text(wl, style="white"))
                renderables.append(Text(""))

        # In-progress streaming bubble
        if self._is_streaming:
            renderables.append(Text(" ···  🤖", style="dim blue"))
            if self._stream_buffer:
                renderables.append(
                    Text(f"       {self._stream_buffer}▌", style="white")
                )
            else:
                renderables.append(Text("       ▌", style="blink dim"))
            renderables.append(Text(""))

        if not renderables:
            renderables = [
                Align.center(
                    Text("Conversation will appear here…", style="dim italic"),
                    vertical="middle",
                )
            ]

        # Clip to available height — keeps bottom (newest) messages visible
        visible = renderables[-available_lines:] if len(renderables) > available_lines else renderables

        return Panel(
            Group(*visible),
            title=f"[bold blue]💬 Chat[/bold blue]",
            border_style="blue",
            padding=(0, 1),
        )

    # ── Sidebar ───────────────────────────────────────────────────────────────

    def _render_sidebar(self) -> Panel:
        """
        Two sections:
          1. Stage progress tracker (top)
          2. Live cart summary (bottom)
        """
        renderables: list = []

        # ── Stage tracker ──
        current_idx = STAGE_ORDER.index(self._stage) if self._stage in STAGE_ORDER else 0
        for i, key in enumerate(STAGE_ORDER):
            label, style = STAGES[key]
            if i < current_idx:
                renderables.append(Text(f"  ✓ {label}", style="dim green"))
            elif i == current_idx:
                renderables.append(Text(f"  ▶ {label}", style=f"bold {style}"))
            else:
                renderables.append(Text(f"    {label}", style="dim"))

        renderables.append(Text(""))
        renderables.append(Rule(style="dim"))
        renderables.append(Text(""))

        # ── Cart items ──
        if not self._cart:
            renderables.append(
                Align.center(Text("Cart is empty", style="dim italic"))
            )
        else:
            for item in self._cart:
                name = item["name"]
                if len(name) > 19:
                    name = name[:17] + "…"
                subtotal = item["price"] * item["quantity"]
                row = Text()
                row.append(f"  {name:<19}", style="white")
                row.append(f"×{item['quantity']}", style="cyan")
                row.append(f"  ${subtotal:>6.2f}", style="green")
                renderables.append(row)

            renderables.append(Text(""))
            renderables.append(Rule(style="dim"))
            renderables.append(Text(""))

            total_line = Text()
            total_line.append("  Total", style="bold white")
            total_line.append(f"      ${self._total:>7.2f}", style="bold green")
            renderables.append(total_line)

        return Panel(
            Group(*renderables),
            title="[bold cyan]📋 Your Order[/bold cyan]",
            border_style="cyan",
            padding=(0, 1),
        )


# ─────────────────────────────────────────────────────────────────────────────
# MODULE-LEVEL SINGLETON
# ─────────────────────────────────────────────────────────────────────────────

# Single shared instance — import this everywhere instead of instantiating
ui = RestaurantUI()