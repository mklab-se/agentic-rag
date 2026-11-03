"""Local client tools: declarations sent on every request and their implementations."""

from __future__ import annotations

import json
import sys
import time
from collections.abc import Callable
from datetime import datetime
from typing import Any

MAX_NOISE = 10

CLIENT_TOOLS: list[dict[str, Any]] = [
    {
        "name": "make_noise",
        "description": f"Ring the terminal bell on the user's machine. At most {MAX_NOISE} times.",
        "parameters": {
            "type": "object",
            "properties": {"times": {"type": "integer", "minimum": 1, "maximum": MAX_NOISE}},
            "required": ["times"],
        },
    },
    {
        "name": "get_local_time",
        "description": "Get the local time and timezone of the user's machine.",
        "parameters": {"type": "object", "properties": {}},
    },
    {
        "name": "show_banner",
        "description": "Show a highlighted banner with the given text in the user's terminal.",
        "parameters": {
            "type": "object",
            "properties": {"text": {"type": "string"}},
            "required": ["text"],
        },
    },
]


def make_noise(times: Any, bell: Callable[[], None] | None = None) -> str:
    try:
        if isinstance(times, bool) or isinstance(times, float) and not times.is_integer():
            raise ValueError
        count = int(times)
    except (TypeError, ValueError):
        return f"error: times must be an integer between 1 and {MAX_NOISE}"
    count = max(1, min(count, MAX_NOISE))
    ring = bell or _bell
    for _ in range(count):
        ring()
        if bell is None:
            time.sleep(0.15)
    return f"Rang the terminal bell {count} time(s)."


def _bell() -> None:  # pragma: no cover
    sys.stdout.write("\a")
    sys.stdout.flush()


def get_local_time() -> str:
    now = datetime.now().astimezone()
    return f"{now.isoformat(timespec='seconds')} ({now.tzname()})"


def show_banner(text: Any, show: Callable[[str], None] | None = None) -> str:
    text = str(text)
    (show or (lambda t: None))(text)
    return f"Showed banner: {text}"


def parse_arguments(arguments: Any) -> dict[str, Any]:
    """Arguments may arrive as a dict or as a JSON string."""
    if isinstance(arguments, str):
        arguments = json.loads(arguments) if arguments.strip() else {}
    if not isinstance(arguments, dict):
        raise ValueError("arguments must be a JSON object")
    return arguments


def run_tool(name: str, arguments: Any, banner: Callable[[str], None] | None = None,
             bell: Callable[[], None] | None = None) -> str:
    """Run one tool. Failures come back as an error string, never as an exception."""
    try:
        args = parse_arguments(arguments)
        if name == "make_noise":
            return make_noise(args.get("times"), bell=bell)
        if name == "get_local_time":
            return get_local_time()
        if name == "show_banner":
            return show_banner(args.get("text", ""), show=banner)
        return f"error: unknown tool '{name}'"
    except Exception as exc:  # noqa: BLE001 - reported to the model instead of crashing the turn
        return f"error: {name} failed: {exc}"
