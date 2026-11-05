# /// script
# requires-python = ">=3.12"
# dependencies = ["httpx"]
# ///
"""How often does a prompt take each path through the own loop? Measured on the deployed API.

    uv run scripts/prompt_journey.py [--repeats 15]

Asks each prompt in a new conversation and sorts the runs by what the agent used. The follow-up
prompt runs after the first prompt in the same conversation, to show the use of earlier turns.
Writes docs/evidence/prompt-journey.txt. docs/prompt-journey.md explains the result.
"""

from __future__ import annotations

import argparse
import collections
import statistics
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from voltrieve_client import Api, Turn, api_token, api_url, cached_token, write_evidence

FIRST = "What is the cheapest car that you can sell me?"
FOLLOW_UP = "And what about one with all wheel drive?"
PROMPTS = [
    ("Your prompt", FIRST),
    ("Market given", "What is the cheapest car that you can sell me in Sweden?"),
    ("AWD, market given", "What is the cheapest car with all wheel drive that you can sell me in Sweden?"),
    ("Greeting", "Good morning!"),
]
EVIDENCE = Path(__file__).parent.parent / "docs" / "evidence" / "prompt-journey.txt"


def path_of(turn: Turn) -> str:
    tools = [c["tool"] for c in turn.trace("server_tool_called")]
    counts = collections.Counter(tools)
    if not counts:
        return "no tool"
    return " + ".join(f"{name} x{count}" for name, count in sorted(counts.items()))


def answer_of(text: str) -> str:
    if "419" in text:
        return "Lumen AWD 419,000 SEK"
    if "289" in text:
        return "Spark 289,000 SEK"
    if "SE" in text and "EU" in text:
        return "asked for the market"
    return "other"


def record(rows: dict, turn: Turn, seconds_from: float = 0.0) -> None:
    key = (path_of(turn), answer_of(turn.text))
    row = rows.setdefault(key, {"runs": 0, "steps": [], "tokens": [], "ms": []})
    row["runs"] += 1
    row["steps"].append(len(turn.trace("model_called")))
    row["tokens"].append((turn.done or {}).get("usage", {}).get("total_tokens", 0))
    stamps = [d.get("elapsed_ms", 0) for _, d in turn.events if isinstance(d, dict) and "elapsed_ms" in d]
    row["ms"].append(max(stamps, default=0))


def lines_for(label: str, prompt: str, rows: dict) -> list[str]:
    total = sum(r["runs"] for r in rows.values())
    lines = [f"{label}: {prompt}", f"  {total} runs"]
    for (path, answer), row in sorted(rows.items(), key=lambda kv: -kv[1]["runs"]):
        lines.append(
            f"  {row['runs']:>3} x  {path}  ->  {answer}  "
            f"(median {statistics.median(row['steps']):g} model calls, "
            f"{statistics.median(row['tokens']):.0f} tokens, "
            f"{statistics.median(row['ms']) / 1000:.1f} s)"
        )
    lines.append("")
    return lines


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--repeats", type=int, default=15)
    args = parser.parse_args()
    token = cached_token(api_token)
    url = api_url()
    output: list[str] = []
    for label, prompt in PROMPTS:
        rows: dict = {}
        for _ in range(args.repeats):
            api = Api(url, token, "loop")
            record(rows, api.turn(prompt))
            api.close()
        output += lines_for(label, prompt, rows)
        print("\n".join(output[-len(rows) - 3:]), flush=True)

    first_rows: dict = {}
    second_rows: dict = {}
    for _ in range(args.repeats):
        api = Api(url, token, "loop")
        first = api.turn(FIRST)
        record(first_rows, first)
        record(second_rows, api.turn(FOLLOW_UP, conversation_id=first.conversation_id))
        api.close()
    output += lines_for("Follow-up in the same conversation", FOLLOW_UP, second_rows)
    print("\n".join(output[-len(second_rows) - 3:]), flush=True)
    write_evidence(EVIDENCE, "\n".join(output))
    return 0


if __name__ == "__main__":
    sys.exit(main())
