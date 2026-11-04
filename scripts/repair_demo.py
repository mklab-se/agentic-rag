# /// script
# requires-python = ">=3.12"
# dependencies = ["httpx"]
# ///
"""Proves that a paused turn nobody answers cannot break a conversation, on the deployed API.

    uv run scripts/repair_demo.py [--backends prompt,loop,hosted] [--wait 420]

A paused turn leaves a function call in the Foundry conversation with no output. The next model
call on that conversation would be refused. For each backend this asks for a client tool, never
answers it, and then sends a new message in two situations:

  abandon  straight away, while the API still holds the paused turn
  repair   after --wait seconds, long enough for the API to scale to zero and lose its memory

Pass means the new message is answered. Writes docs/evidence/repair.txt.
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from voltrieve_client import Api, api_token, api_url, cached_token, write_evidence

NOISE_TOOL = {
    "name": "make_noise",
    "description": "Ring the terminal bell a number of times.",
    "parameters": {
        "type": "object",
        "properties": {"times": {"type": "integer", "minimum": 1, "maximum": 10}},
        "required": ["times"],
        "additionalProperties": False,
    },
}
EVIDENCE = Path(__file__).parent.parent / "docs" / "evidence" / "repair.txt"


def pause(api: Api) -> str:
    """Start a turn that stops at a client tool call, and walk away from it."""
    events = list(api._stream("/chat", {"message": "Beep twice.", "client_tools": [NOISE_TOOL]}, None))
    calls = [data for name, data in events if name == "client_tool_calls"]
    if not calls:
        raise SystemExit(f"the model did not call the client tool: {[n for n, _ in events]}")
    return calls[0]["conversation_id"]


def follow_up(api: Api, conversation_id: str, label: str, lines: list[str]) -> bool:
    turn = api.turn(
        "What is the battery size of the Voltrieve Spark?",
        conversation_id=conversation_id,
        client_tools=[NOISE_TOOL],
    )
    recovery = [s for s in turn.trace_steps if s in ("turn_abandoned", "conversation_repaired")]
    passed = turn.done is not None and "42" in turn.text
    lines.append(f"{'PASS' if passed else 'FAIL'}  {label}  recovery steps: {recovery}  "
                 f"error: {turn.error}  answer: {turn.text[:90]!r}")
    print(lines[-1], flush=True)
    return passed


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--backends", default="prompt,loop,hosted")
    parser.add_argument("--wait", type=int, default=420)
    args = parser.parse_args()

    token = cached_token(api_token)
    url = api_url()
    lines: list[str] = []
    passed = True
    waiting: list[tuple[str, Api, str]] = []
    for backend in args.backends.split(","):
        api = Api(url, token, backend)
        passed &= follow_up(api, pause(api), f"{backend} abandon", lines)
        waiting.append((backend, api, pause(api)))

    print(f"waiting {args.wait}s for the API to scale to zero", flush=True)
    time.sleep(args.wait)
    for backend, api, conversation_id in waiting:
        passed &= follow_up(api, conversation_id, f"{backend} repair", lines)
        api.close()

    write_evidence(EVIDENCE, "\n".join(lines) + "\n")
    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(main())
