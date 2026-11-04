"""Terminal rendering: chat panel left, timestamped trace panel right."""

from __future__ import annotations

import json
import re
from collections import deque
from datetime import datetime
from typing import Any

from rich.console import Console, Group
from rich.layout import Layout
from rich.live import Live
from rich.panel import Panel
from rich.text import Text

TRACE_LINES = 200

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


class ChatView:
    """Accumulates chat and trace lines and renders them side by side (stacked when narrow)."""

    def __init__(self, console: Console):
        self.console = console
        self.chat: list[Text] = []
        self.trace: deque[str] = deque(maxlen=TRACE_LINES)
        self._agent_line = -1
        self._live: Live | None = None

    def __enter__(self) -> "ChatView":
        self._live = Live(self.renderable(), console=self.console, refresh_per_second=8,
                          transient=False)
        self._live.__enter__()
        return self

    def __exit__(self, *exc: object) -> None:
        if self._live:
            self._live.update(self.renderable())
            self._live.__exit__(*exc)

    def user(self, text: str) -> None:
        self.chat.append(Text(f"you: {clean(text)}", style="bold cyan"))
        self.refresh()

    def on_event(self, name: str, data: dict[str, Any]) -> None:
        if name == "trace":
            self.trace.append(format_trace(data))
        elif name == "delta":
            if self._agent_line != len(self.chat) - 1:
                self.chat.append(Text("agent: "))
                self._agent_line = len(self.chat) - 1
            self.chat[-1].append(clean(data.get("text", "")))
        elif name == "tool_ran":
            self.trace.append(clean(f"{datetime.now():%H:%M:%S} [client] ran {data.get('name')}: {data.get('output')}"))
        elif name == "turn_started":
            self.trace.append(f"{datetime.now():%H:%M:%S} [client] correlation id {clean(data.get('correlation_id'))}")
        elif name == "error":
            self.chat.append(Text(clean(f"error {data.get('code')}: {data.get('message')}"), style="bold red"))
        elif name == "done":
            self.trace.append(clean(f"{datetime.now():%H:%M:%S} done backend={data.get('backend')} usage={data.get('usage')}"))
        self.refresh()

    def show_banner(self, text: str) -> None:
        self.chat.append(Text(f"*** {clean(text)} ***", style="bold black on yellow"))
        self.refresh()

    def renderable(self):
        height = max(self.console.size.height - 4, 8)
        chat = Panel(Group(*self.chat[-height:]) if self.chat else Text(""), title="chat")
        lines = list(self.trace)[-(height - 2):]
        trace = Panel(Text("\n".join(lines), overflow="ellipsis", no_wrap=True), title="trace")
        if self.console.size.width < 100:
            return Group(chat, trace)
        layout = Layout()
        layout.split_row(Layout(chat, ratio=3), Layout(trace, ratio=2))
        layout.size = height + 2
        return layout

    def refresh(self) -> None:
        if self._live:
            self._live.update(self.renderable())
