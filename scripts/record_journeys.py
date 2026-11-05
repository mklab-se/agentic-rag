# /// script
# requires-python = ">=3.12"
# dependencies = ["httpx"]
# ///
"""Record the prompts of the journey page on all three backends, on the deployed API.

    uv run scripts/record_journeys.py [--repeats 3]

Writes docs/evidence/journeys.json: per prompt and backend the median time, model calls and
tokens, the tools used per run, and the trace of the last run. docs/assets/prompt-journey.html
embeds this file.
"""

from __future__ import annotations

import argparse
import collections
import json
import statistics
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from voltrieve_client import Api, ApiError, api_token, api_url, cached_token, write_evidence

BACKENDS = ["loop", "prompt", "hosted"]
TIME_TOOL = {
    "name": "get_local_time",
    "description": "Get the local time and timezone of the user's machine.",
    "parameters": {"type": "object", "properties": {}},
}
FIRST = "What is the cheapest car that you can sell me?"
PROMPTS = {
    "yours": FIRST,
    "follow": "And what about one with all wheel drive?",
    "awd": "What is the cheapest car with all wheel drive that you can sell me in Sweden?",
    "detail": "I have a Voltrieve Fjord AWD. I want to completely change the brakes on the left "
    "front side. Which spare parts do I need?",
    "hello": "Good morning!",
    "client": "What time is it on my computer right now?",
    "curated": "What is the phone number to Voltrieve?",
}
OUTPUT = Path(__file__).parent.parent / "docs" / "evidence" / "journeys.json"


def local_time(arguments: str) -> str:
    return json.dumps({"local_time": "2026-11-05T16:42:10+01:00", "timezone": "Europe/Stockholm"})


def used(turn) -> list[str]:
    names = [c["tool"] for c in turn.trace("server_tool_called")]
    names += [f"MCP {c.get('server')}" for c in turn.trace("mcp_tool_called")]
    names += [c["tool"] for c in turn.trace("client_tool_requested")]
    return names


def trace_of(turn) -> dict:
    return {
        "server_tools": [
            {"tool": c["tool"], "arguments": c.get("arguments"), "iteration": c.get("iteration")}
            for c in turn.trace("server_tool_called")
        ],
        "mcp": [
            {"server": c.get("server"), "arguments": c.get("arguments"),
             "started_ms": c.get("started_ms"), "finished_ms": c.get("finished_ms")}
            for c in turn.trace("mcp_tool_called")
        ],
        "knowledge": [
            {"base": c.get("knowledge_base"), "sub_queries": c.get("sub_queries"),
             "references": (c.get("references") or [])[:4]}
            for c in turn.trace("knowledge_base_retrieved")
        ],
        "parallel": [
            {"wall_ms": c.get("wall_ms"), "one_by_one_ms": c.get("one_by_one_ms")}
            for c in turn.trace("tools_parallel_finished")
        ],
        "answer": turn.text[:900],
    }


def one(url, token, backend: str, key: str, repeat: int) -> dict:
    api = Api(url, token, backend)
    try:
        conversation = None
        if key == "follow":
            conversation = api.turn(FIRST).conversation_id
        began = time.perf_counter()
        try:
            turn = api.turn(
                PROMPTS[key],
                conversation_id=conversation,
                client_tools=[TIME_TOOL] if key == "client" else None,
                handlers={"get_local_time": local_time},
                correlation_id=f"journey-{backend}-{key}-{repeat}",
            )
        except ApiError as exc:
            return {"seconds": 0, "model_calls": 0, "tokens": 0, "used": [], "error": str(exc),
                    "trace": {"server_tools": [], "mcp": [], "knowledge": [], "parallel": [], "answer": ""}}
        return {            "seconds": round(time.perf_counter() - began, 2),
            "model_calls": len(turn.trace("model_called")),
            "tokens": (turn.done or {}).get("usage", {}).get("total_tokens", 0),
            "used": used(turn),
            "error": (turn.error or {}).get("code", ""),
            "trace": trace_of(turn),
        }
    finally:
        api.close()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--repeats", type=int, default=3)
    args = parser.parse_args()
    token = cached_token(api_token)
    url = api_url()

    def backend_runs(backend: str) -> dict:
        api = Api(url, token, backend)
        api.turn("Good morning!")  # wakes containers that scaled to zero
        api.close()
        result = {}
        for key in PROMPTS:
            runs = [one(url, token, backend, key, r) for r in range(args.repeats)]
            good = [r for r in runs if not r["error"]] or runs
            result[key] = {
                "runs": len(runs),
                "errors": sum(bool(r["error"]) for r in runs),
                "seconds": statistics.median(r["seconds"] for r in good),
                "model_calls": statistics.median(r["model_calls"] for r in good),
                "tokens": statistics.median(r["tokens"] for r in good),
                "paths": collections.Counter(
                    " + ".join(sorted(r["used"])) or "no tool" for r in runs
                ),
                "example": good[-1]["trace"],
            }
            print(f"{backend} {key}: {result[key]['seconds']} s", file=sys.stderr, flush=True)
        return result

    with ThreadPoolExecutor(len(BACKENDS)) as pool:
        data = dict(zip(BACKENDS, pool.map(backend_runs, BACKENDS)))
    write_evidence(OUTPUT, json.dumps(data, indent=1, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
