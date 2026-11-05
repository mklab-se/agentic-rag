# /// script
# requires-python = ">=3.12"
# dependencies = ["httpx"]
# ///
"""Do curated answers slow down the questions that do not need them? Measured on the deployed API.

    uv run scripts/curated_latency.py before [--repeats 8]
    uv run scripts/curated_latency.py after  [--repeats 8]
    uv run scripts/curated_latency.py compare

Each label asks the same normal questions on every backend, one backend per thread, and stores
the runs in docs/evidence/curated-latency-<label>.json. `after` also asks curated questions.
`compare` writes docs/evidence/curated-latency.txt.
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from voltrieve_client import Api, api_token, api_url, cached_token, write_evidence

BACKENDS = ["loop", "prompt", "hosted"]
NORMAL = {
    "greeting": "Good morning!",
    "price": "What is the cheapest car that you can sell me in Sweden?",
    "documents": "What is the towing capacity of the Fjord?",
}
CURATED = {
    "phone": "What is the phone number to Voltrieve?",
    "hours": "What are the opening hours of Voltrieve?",
    "smoke": "There is smoke coming from under my car!",
}
EVIDENCE = Path(__file__).parent.parent / "docs" / "evidence"


def one(url, token, backend: str, name: str, prompt: str, repeat: int) -> dict:
    api = Api(url, token, backend)
    began = time.perf_counter()
    try:
        turn = api.turn(prompt, correlation_id=f"curated-{backend}-{name}-{repeat}")
        usage = (turn.done or {}).get("usage", {})
        return {
            "backend": backend,
            "question": name,
            "seconds": round(time.perf_counter() - began, 2),
            "model_calls": len(turn.trace("model_called")),
            "input_tokens": usage.get("input_tokens", 0),
            "final": bool(turn.trace("final_answer_sent")),
            "error": (turn.error or {}).get("code", ""),
        }
    finally:
        api.close()


def measure(label: str, repeats: int) -> None:
    token = cached_token(api_token)
    url = api_url()
    questions = {**NORMAL, **(CURATED if label == "after" else {})}

    def backend_runs(backend: str) -> list[dict]:
        runs = []
        # The first turn wakes containers that scaled to zero, so it does not count.
        one(url, token, backend, "warmup", "Good morning!", 0)
        for repeat in range(repeats):
            for name, prompt in questions.items():
                runs.append(one(url, token, backend, name, prompt, repeat))
            print(f"{backend}: {repeat + 1} of {repeats}", file=sys.stderr, flush=True)
        return runs

    with ThreadPoolExecutor(len(BACKENDS)) as pool:
        runs = [r for rows in pool.map(backend_runs, BACKENDS) for r in rows]
    EVIDENCE.joinpath(f"curated-latency-{label}.json").write_text(json.dumps(runs, indent=1) + "\n")


def med(rows: list[dict], key: str) -> float:
    return statistics.median(r[key] for r in rows) if rows else 0.0


def compare() -> None:
    before = json.loads(EVIDENCE.joinpath("curated-latency-before.json").read_text())
    after = json.loads(EVIDENCE.joinpath("curated-latency-after.json").read_text())
    pick = lambda runs, b, q: [r for r in runs if r["backend"] == b and r["question"] == q and not r["error"]]
    lines = ["Normal questions, median of each backend, before and after curated answers", ""]
    lines.append(f"{'backend':8}{'question':11}{'runs':>5}{'s before':>10}{'s after':>9}"
                 f"{'calls before':>14}{'calls after':>13}{'tokens before':>15}{'tokens after':>14}")
    for backend in BACKENDS:
        for name in NORMAL:
            old, new = pick(before, backend, name), pick(after, backend, name)
            lines.append(f"{backend:8}{name:11}{len(new):>5}{med(old, 'seconds'):>10.1f}"
                         f"{med(new, 'seconds'):>9.1f}{med(old, 'model_calls'):>14.1f}"
                         f"{med(new, 'model_calls'):>13.1f}{med(old, 'input_tokens'):>15.0f}"
                         f"{med(new, 'input_tokens'):>14.0f}")
    lines += ["", "Curated questions", "",
              f"{'backend':8}{'question':11}{'runs':>5}{'seconds':>9}{'model calls':>13}{'word for word':>15}"]
    for backend in BACKENDS:
        for name in CURATED:
            rows = pick(after, backend, name)
            lines.append(f"{backend:8}{name:11}{len(rows):>5}{med(rows, 'seconds'):>9.1f}"
                         f"{med(rows, 'model_calls'):>13.1f}"
                         f"{sum(r['final'] for r in rows):>12} of {len(rows)}")
    errors = [r for r in before + after if r["error"]]
    lines += ["", f"Runs with an error: {len(errors)}"]
    print("\n".join(lines))
    write_evidence(EVIDENCE / "curated-latency.txt", "\n".join(lines))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("label", choices=["before", "after", "compare"])
    parser.add_argument("--repeats", type=int, default=8)
    args = parser.parse_args()
    if args.label == "compare":
        compare()
    else:
        measure(args.label, args.repeats)
    return 0


if __name__ == "__main__":
    sys.exit(main())
