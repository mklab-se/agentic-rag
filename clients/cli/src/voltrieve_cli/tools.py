"""Local client tools: declarations sent on every request and their implementations."""

from __future__ import annotations

import json
import math
import shutil
import struct
import subprocess
import sys
import tempfile
import time
import wave
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import Any

MAX_NOISE = 10
MAX_HONKS = 5
# A car horn is two notes a little apart. These are a common pair.
HORN_NOTES_HZ = (420.0, 500.0)
HONK_SECONDS = 0.4
SAMPLE_RATE = 22050
PLAYERS = (["afplay"], ["paplay"], ["aplay", "-q"])

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
        "name": "honk",
        "description": f"Honk like a car, out loud on the user's computer. At most {MAX_HONKS} times.",
        "parameters": {
            "type": "object",
            "properties": {"times": {"type": "integer", "minimum": 1, "maximum": MAX_HONKS}},
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
    # Not in the prompt agent's definition, on purpose: that agent refuses tools it was not
    # defined with, and this shows the limit.
    {
        "name": "set_gauge",
        "description": "Set the gauge shown in the user's terminal to a value from 0 to 100. Use it "
        "when the user asks to set or change the gauge.",
        "parameters": {
            "type": "object",
            "properties": {"value": {"type": "integer", "minimum": 0, "maximum": 100}},
            "required": ["value"],
        },
    },
]


def tools_for(gauge_on: bool) -> list[dict[str, Any]]:
    """The tools to offer: set_gauge only while the gauge is on."""
    return [t for t in CLIENT_TOOLS if gauge_on or t["name"] != "set_gauge"]


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
    sys.stderr.write("\a")  # stderr keeps `ask --json` stdout parseable
    sys.stderr.flush()


def _horn_samples() -> bytes:
    """A horn with a soft start and end, so that it does not click."""
    count = int(HONK_SECONDS * SAMPLE_RATE)
    fade = int(0.02 * SAMPLE_RATE)
    frames = bytearray()
    for n in range(count):
        t = n / SAMPLE_RATE
        # The sign of the sine is a square wave, which is what gives a horn its edge.
        value = sum(math.copysign(1, math.sin(2 * math.pi * f * t)) for f in HORN_NOTES_HZ) / 2
        envelope = min(1.0, n / fade, (count - n) / fade)
        frames += struct.pack("<h", int(value * envelope * 9000))
    return bytes(frames)


def _play_horn() -> bool:  # pragma: no cover
    """Play one honk. False when this machine has no player, and the bell has to do."""
    player = next((p for p in PLAYERS if shutil.which(p[0])), None)
    if player is None:
        return False
    with tempfile.TemporaryDirectory() as folder:
        path = Path(folder) / "honk.wav"
        with wave.open(str(path), "wb") as audio:
            audio.setnchannels(1)
            audio.setsampwidth(2)
            audio.setframerate(SAMPLE_RATE)
            audio.writeframes(_horn_samples())
        return subprocess.run([*player, str(path)], capture_output=True, timeout=5).returncode == 0


def honk(times: Any, play: Callable[[], bool] | None = None) -> str:
    try:
        if isinstance(times, bool) or isinstance(times, float) and not times.is_integer():
            raise ValueError
        count = int(times)
    except (TypeError, ValueError):
        return f"error: times must be an integer between 1 and {MAX_HONKS}"
    count = max(1, min(count, MAX_HONKS))
    sound = play or _play_horn
    played = [sound() for _ in range(count)]
    if all(played):
        return f"Honked {count} time(s)."
    _bell()
    return f"This computer cannot play sound, so the terminal bell rang instead of {count} honk(s)."


def get_local_time() -> str:
    now = datetime.now().astimezone()
    return f"{now.isoformat(timespec='seconds')} ({now.tzname()})"


def show_banner(text: Any, show: Callable[[str], None] | None = None) -> str:
    text = str(text)
    (show or (lambda t: None))(text)
    return f"Showed banner: {text}"


def set_gauge(value: Any, show: Callable[[int], None] | None = None) -> str:
    if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= 100:
        return "error: value must be a whole number from 0 to 100"
    (show or (lambda v: None))(value)
    return f"The gauge now shows {value}."


def parse_arguments(arguments: Any) -> dict[str, Any]:
    """Arguments may arrive as a dict or as a JSON string."""
    if isinstance(arguments, str):
        arguments = json.loads(arguments) if arguments.strip() else {}
    if not isinstance(arguments, dict):
        raise ValueError("arguments must be a JSON object")
    return arguments


def run_tool(name: str, arguments: Any, banner: Callable[[str], None] | None = None,
             bell: Callable[[], None] | None = None, play: Callable[[], bool] | None = None,
             gauge: Callable[[int], None] | None = None) -> str:
    """Run one tool. Failures come back as an error string, never as an exception."""
    try:
        args = parse_arguments(arguments)
        if name == "make_noise":
            return make_noise(args.get("times"), bell=bell)
        if name == "honk":
            return honk(args.get("times", 1), play=play)
        if name == "set_gauge":
            return set_gauge(args.get("value"), show=gauge)
        if name == "get_local_time":
            return get_local_time()
        if name == "show_banner":
            return show_banner(args.get("text", ""), show=banner)
        return f"error: unknown tool '{name}'"
    except Exception as exc:  # noqa: BLE001 - reported to the model instead of crashing the turn
        return f"error: {name} failed: {exc}"
