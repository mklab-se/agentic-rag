"""Terminal rendering: a conversation of message bubbles with one live status line.

Finished messages are printed once and stay in the terminal's scrollback, so scrolling, search
and copying keep working. Only the message being written redraws, in a region that clears
itself when the turn ends. When the output is not a terminal, everything is plain text.
"""

from __future__ import annotations

import json
import re
import time
from collections import deque
from datetime import datetime
from typing import Any

from rich import box
from rich.align import Align
from rich.cells import cell_len
from rich.console import Console, ConsoleOptions, Group, RenderResult
from rich.control import Control
from rich.live import Live
from rich.markdown import Markdown
from rich.panel import Panel
from rich.segment import ControlType, Segment
from rich.spinner import Spinner
from rich.text import Text

TRACE_LINES = 200
USER_COLOR = "#0a84ff"
AGENT_COLOR = "grey50"
# A new time heading after a pause this long, as in Messages.
QUIET_SECONDS = 600
# What the live region keeps free for the status line and the turn above it.
RESERVED_LINES = 7
GAUGE_WIDTH = 30
GAUGE_SECONDS = 0.7
EIGHTHS = ("", "▏", "▎", "▍", "▌", "▋", "▊", "▉")
_SOURCES = re.compile(
    r"(?:^|(?<=\s))\(?[*_]{0,2}Sources?:[*_]{0,2}[ \t]*(?P<names>.+?)\)?\.?[ \t]*$", re.MULTILINE
)

# C0 control characters (except newline and tab), DEL and the C1 range. The model's text and
# tool results reach the terminal; an ESC sequence in them could move the cursor, rewrite the
# screen or set the window title.
_CONTROL = re.compile("[\x00-\x08\x0b-\x1f\x7f-\x9f]")


def clean(value: Any) -> str:
    """Text safe to print: control characters removed."""
    return _CONTROL.sub("", str(value))


def format_trace(data: dict[str, Any], now: datetime | None = None) -> str:
    stamp = (now or datetime.now()).strftime("%H:%M:%S")
    elapsed = data.get("elapsed_ms")
    ms = f" +{int(elapsed)}ms" if isinstance(elapsed, (int, float)) else ""
    line = f"{stamp}{ms} [{data.get('component', '?')}] {data.get('step', '')}: {data.get('detail', '')}"
    return clean(line)


def json_line(name: str, data: dict[str, Any]) -> str:
    return json.dumps({"event": name, "data": data}, ensure_ascii=False)


def gauge_bar(value: float, width: int = GAUGE_WIDTH) -> Text:
    """A bar that fills smoothly, using the partial block characters, and warms up as it rises."""
    cells = max(0.0, min(value, 100.0)) / 100 * width
    full = int(cells)
    part = EIGHTHS[int((cells - full) * 8)]
    color = "green" if value < 60 else "yellow" if value < 85 else "red"
    bar = Text("  Gauge ", style="dim")
    bar.append("▕", style="dim")
    bar.append("█" * full + part, style=color)
    bar.append("░" * (width - full - (1 if part else 0)), style="dim")
    bar.append("▏", style="dim")
    bar.append(f" {round(value)}", style=f"bold {color}")
    return bar


def bubble_width(console_width: int) -> int:
    """The widest a bubble may be: about 70 percent of the terminal, more when it is narrow."""
    share = 0.7 if console_width >= 80 else 0.92
    return max(20, min(int(console_width * share), console_width - 2))


def split_sources(text: str) -> tuple[str, list[str]]:
    """The answer without its last `Sources: ...` sentence, and the names in that sentence."""
    matches = list(_SOURCES.finditer(text))
    if not matches:
        return text, []
    last = matches[-1]
    if ") " in last.group("names"):  # the sentence goes on after the bracket: leave it alone
        return text, []
    # "and" only splits between marked names: a title can hold it, as in "suspension and steering".
    pieces = re.split(r",\s*(?:and\s+)?|(?<=[*_`])\s+and\s+(?=[*_`])|\s+/\s+", last.group("names"))
    parts = [name for piece in pieces if (name := re.sub(r"[*_`]", "", piece).strip(" ."))]
    body = (text[: last.start()].rstrip(" ") + text[last.end() :]).strip()
    return re.sub(r"\n{3,}", "\n\n", body), parts


class _Lines:
    """Lines that were already rendered, so a long answer can show just its tail."""

    def __init__(self, lines: list[list[Segment]]):
        self.lines = lines

    def __rich_console__(self, console: Console, options: ConsoleOptions) -> RenderResult:
        for line in self.lines:
            yield from line
            yield Segment.line()


class ChatView:
    """The whole conversation. Use `with view:` around each turn."""

    def __init__(self, console: Console, show_trace: bool = False, gauge_on: bool = True):
        self.console = console
        self.show_trace = show_trace
        self.gauge_on = gauge_on
        self.trace: deque[str] = deque(maxlen=TRACE_LINES)
        self._answer = ""
        self._status: str | None = None
        self._status_since = 0.0
        self._last_time_shown = 0.0
        self._live: Live | None = None
        self._spinner = Spinner("dots", style=USER_COLOR)
        self._gauge = 0
        self._gauge_from = 0.0
        self._gauge_moved = 0.0

    @property
    def is_rich(self) -> bool:
        return self.console.is_terminal

    def __enter__(self) -> "ChatView":
        self._answer = ""
        self._status = None
        if self.is_rich:
            self._live = Live(console=self.console, get_renderable=self.renderable,
                              refresh_per_second=12, transient=True, vertical_overflow="crop")
            self._live.__enter__()
        return self

    def __exit__(self, *exc: object) -> None:
        if self._live:
            self._live.__exit__(*exc)
            self._live = None
        self._flush_answer()
        self._status = None

    def erase_input(self, text: str) -> None:
        """Remove the typed line, because it comes back as a bubble."""
        if not self.is_rich:
            return
        width = max(self.console.width, 1)
        # One more than the typed text: the gauge line above the prompt, which is drawn again.
        rows = (len(text) + 2) // width + (2 if self.gauge_on else 1)
        for _ in range(rows):
            self.console.control(Control((ControlType.CURSOR_UP, 1), (ControlType.ERASE_IN_LINE, 2)))

    def user(self, text: str) -> None:
        text = clean(text)
        if not self.is_rich:
            self.console.print(f"you: {text}", markup=False, highlight=False)
            return
        self._time_heading()
        width = bubble_width(self.console.width)
        self.console.print(Align.right(self._bubble(Text(text), USER_COLOR, self._fit(Text(text), width))))

    def set_gauge(self, value: int) -> None:
        self._gauge_from = self._gauge_now()
        self._gauge = value
        self._gauge_moved = time.monotonic()
        if not self.is_rich:
            self.console.print(f"gauge: {value}", markup=False, highlight=False)

    def print_gauge(self) -> None:
        """The line above the prompt. It is erased when you send, so it never piles up."""
        if self.is_rich and self.gauge_on:
            self.console.print(gauge_bar(self._gauge))

    def _gauge_now(self) -> float:
        progress = min((time.monotonic() - self._gauge_moved) / GAUGE_SECONDS, 1.0)
        eased = 1 - (1 - progress) ** 3
        return self._gauge_from + (self._gauge - self._gauge_from) * eased

    def on_event(self, name: str, data: dict[str, Any]) -> None:
        if name == "delta":
            self._on_delta(clean(data.get("text", "")))
        elif name == "status":
            self._status = clean(data.get("message", ""))
            self._status_since = time.monotonic()
            self._log(f"{datetime.now():%H:%M:%S} [status] {self._status}")
        elif name == "trace":
            self._log(format_trace(data))
        elif name == "tool_ran":
            self._log(clean(f"{datetime.now():%H:%M:%S} [client] ran {data.get('name')}: {data.get('output')}"))
        elif name == "turn_started":
            self.trace.clear()
            self._log(f"{datetime.now():%H:%M:%S} [client] correlation id {clean(data.get('correlation_id'))}")
        elif name == "done":
            self._status = None
            self._log(clean(f"{datetime.now():%H:%M:%S} done backend={data.get('backend')} usage={data.get('usage')}"))
        elif name == "error":
            self._status = None
            message = clean(f"error {data.get('code')}: {data.get('message')}")
            if self.is_rich:
                self.console.print(Text(message, style="bold red"))
            else:
                self.console.print(message, markup=False, highlight=False)

    def show_banner(self, text: str) -> None:
        if self.is_rich:
            self.console.print(Text(f" {clean(text)} ", style="bold black on yellow"))
        else:
            self.console.print(f"*** {clean(text)} ***", markup=False, highlight=False)

    def print_trace(self) -> None:
        for line in self.trace or ["No turn to show yet."]:
            self.console.print(Text(line, style="dim"))

    def renderable(self):
        parts = []
        if self._answer:
            parts.append(self._streaming_bubble())
        if self._status:
            seconds = int(time.monotonic() - self._status_since)
            self._spinner.update(text=Text(f"{self._status} · {seconds} s", style="dim"))
            parts.append(Text(""))
            parts.append(self._spinner)
        if self.gauge_on:
            parts.append(Text(""))
            parts.append(gauge_bar(self._gauge_now()))
        return Group(*parts)

    def _on_delta(self, text: str) -> None:
        self._status = None
        if not self.is_rich:
            if not self._answer:
                self.console.print("agent: ", end="", markup=False, highlight=False)
            self.console.print(text, end="", markup=False, highlight=False)
        self._answer += text

    def _log(self, line: str) -> None:
        self.trace.append(line)
        if self.show_trace:
            self.console.print(Text(line, style="dim", no_wrap=True, overflow="ellipsis"))

    def _time_heading(self) -> None:
        now = time.time()
        if now - self._last_time_shown >= QUIET_SECONDS:
            self.console.print()
            self.console.print(Align.center(Text(f"Today {datetime.now():%H:%M}", style="dim")))
        self._last_time_shown = now

    def _markdown(self, text: str) -> Markdown:
        # Links stay visible as text: a model's answer must not hide where a link goes.
        return Markdown(text, hyperlinks=False)

    def _fit(self, content, widest: int) -> int:
        """The bubble width that just holds this content."""
        inner = self.console.options.update(width=widest - 4)
        lines = self.console.render_lines(content, inner, pad=False)
        used = (cell_len("".join(segment.text for segment in line).rstrip()) for line in lines)
        return min(widest, max(used, default=1) + 4)

    @staticmethod
    def _bubble(content, color: str, width: int | None = None, title: str | None = None) -> Panel:
        return Panel(content, box=box.ROUNDED, border_style=color, padding=(0, 1), width=width,
                     expand=width is not None, title=title, title_align="left")

    def _streaming_bubble(self) -> Panel:
        width = bubble_width(self.console.width)
        room = max(self.console.height - RESERVED_LINES, 3)
        options = self.console.options.update(width=width - 4)
        lines = self.console.render_lines(self._markdown(self._answer), options, pad=False)
        if len(lines) <= room:
            return self._bubble(_Lines(lines), AGENT_COLOR, width)
        return self._bubble(_Lines(lines[-room:]), AGENT_COLOR, width, title="[dim]…[/dim]")

    def _flush_answer(self) -> None:
        """Print the finished answer into the scrollback."""
        answer, self._answer = self._answer.strip(), ""
        if not answer:
            return
        if not self.is_rich:
            self.console.print()
            return
        body, sources = split_sources(answer)
        content = self._markdown(body)
        width = self._fit(content, bubble_width(self.console.width))
        self.console.print()
        self.console.print(self._bubble(content, AGENT_COLOR, width))
        if sources:
            self.console.print(Text(f"  {' · '.join(sources)}", style="dim"))
