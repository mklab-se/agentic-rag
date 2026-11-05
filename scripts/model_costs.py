# /// script
# requires-python = ">=3.12"
# dependencies = ["httpx"]
# ///
"""Compare the labelled routing runs in docs/evidence/models/: speed, quality and estimated cost.

    uv run scripts/model_costs.py

Cost is estimated from the tokens each turn reported and list prices in USD per million tokens,
Global Standard, Sweden Central, read from the Azure retail prices API on 2026-11-05. Cache write
charges are left out, because the runs did not record those tokens. The prompt
agent does not report planning tokens, so its searches borrow the own loop's average per search.
Writes docs/evidence/model-comparison.txt.
"""

import json
import statistics
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from voltrieve_client import write_evidence

EVIDENCE = Path(__file__).parent.parent / "docs" / "evidence"
# input, cached input, output
PRICES = {
    "gpt-5.4-mini": (0.75, 0.075, 4.50),
    "gpt-5.4-nano": (0.20, 0.02, 1.25),
    "gpt-5.6-terra": (2.00, 0.20, 12.00),
    "gpt-6-luna": (0.10, 0.01, 0.50),
    "gpt-6.1-sol": (2.00, 0.10, 10.00),
    "gpt-6.1-terra": (1.00, 0.05, 5.00),  # from the Azure OpenAI pricing page, not in the API
}
SEARCH_REASONING_PER_MILLION = 0.022


def turn_cost(run: dict, agent: str, planner: str, borrowed: dict) -> float | None:
    if agent not in PRICES or planner not in PRICES:
        return None
    price_in, price_cached, price_out = PRICES[agent]
    cached = run.get("cached_tokens", 0)
    cost = (run["input_tokens"] - cached) * price_in + cached * price_cached
    cost += run["output_tokens"] * price_out
    planning_in = run.get("planning_input_tokens", 0)
    planning_out = run.get("planning_output_tokens", 0)
    reasoning = run.get("search_reasoning_tokens", 0)
    if run["backend"] == "prompt":
        planning_in = run.get("searches", 0) * borrowed["in"]
        planning_out = run.get("searches", 0) * borrowed["out"]
        reasoning = run.get("searches", 0) * borrowed["reasoning"]
    cost += planning_in * PRICES[planner][0] + planning_out * PRICES[planner][2]
    cost += reasoning * SEARCH_REASONING_PER_MILLION
    return cost / 1_000_000


def main() -> int:
    runs_by_label = {
        p.stem: json.loads(p.read_text()) for p in sorted((EVIDENCE / "models").glob("*.json"))
    }
    loop = [r for runs in runs_by_label.values() for r in runs if r.get("searches") and r["backend"] == "loop"]
    searches = sum(r["searches"] for r in loop) or 1
    borrowed = {
        "in": sum(r["planning_input_tokens"] for r in loop) / searches,
        "out": sum(r["planning_output_tokens"] for r in loop) / searches,
        "reasoning": sum(r["search_reasoning_tokens"] for r in loop) / searches,
    }
    head = (f"{'run':34}{'turns':>6}{'right':>7}{'in vain':>8}{'articles':>10}{'errors':>7}"
            f"{'median s':>9}{'simple s':>9}{'jobs s':>8}{'USD/1000':>10}")
    lines = ["Speed, quality and estimated cost per run", "", head]
    for label, runs in runs_by_label.items():
        if label.startswith("arch-"):
            continue
        parts = label.split("-", 1)
        kind, rest = parts[0], parts[1]
        agent, planner = rest, "gpt-5.4-mini"
        if kind == "planner":
            agent, planner = "gpt-5.4-mini", rest
        if kind == "arch":
            agent = rest.split("-", 1)[1]
        if "+" in rest:
            agent, planner = rest.split("+")
            agent = agent.removeprefix("loop-").removeprefix("prompt-").removeprefix("hosted-")
        costs = [turn_cost(r, agent, planner, borrowed) for r in runs]
        known = [c for c in costs if c is not None]
        jobs = [r["seconds"] for r in runs if r["group"] == "both" and not r["error"]]
        simple = [r["seconds"] for r in runs if r["group"] in ("none", "curated") and not r["error"]]
        everything = [r["seconds"] for r in runs if not r["error"]] or [0]
        found = sum(r["articles_found"] for r in runs)
        wanted = sum(r["articles_expected"] for r in runs)
        price = f"{1000 * statistics.mean(known):>10.2f}" if known else f"{'n/a':>10}"
        lines.append(
            f"{label:34}{len(runs):>6}{sum(not r['error'] and sorted(r['used']) == sorted(r['expected']) and r.get('topic') == r.get('expected_topic') for r in runs):>7}"
            f"{sum(bool(set(r['used']) - set(r['expected'])) for r in runs):>8}{f'{found}/{wanted}':>10}"
            f"{sum(bool(r['error']) for r in runs):>7}{statistics.median(everything):>9.1f}"
            f"{statistics.median(simple or [0]):>9.1f}{statistics.median(jobs or [0]):>8.1f}{price}"
        )
    lines += ["", "Each architecture and model. TTFT is time to first token, total is time to last.",
              "", f"{'backend':8}{'model':16}{'turns':>6}{'right':>7}{'articles':>10}{'TTFT med':>9}"
              f"{'TTFT max':>9}{'over 10s':>9}{'jobs TTFT':>10}{'total med':>10}{'jobs total':>11}{'USD/1000':>10}"]
    for label, runs in runs_by_label.items():
        if not label.startswith("arch-"):
            continue
        model = label.removeprefix("arch-")
        for backend in ("loop", "prompt", "hosted"):
            rows = [r for r in runs if r["backend"] == backend]
            good = [r for r in rows if not r["error"]]
            if not good:
                continue
            first = [r["first_text_seconds"] for r in good if r.get("first_text_seconds") is not None]
            jobs = [r for r in good if r["group"] == "both"]
            job_first = [r["first_text_seconds"] for r in jobs if r.get("first_text_seconds") is not None]
            costs = [c for c in (turn_cost(r, model, "gpt-5.4-mini", borrowed) for r in rows) if c is not None]
            right = sum(sorted(r["used"]) == sorted(r["expected"]) and r.get("topic") == r.get("expected_topic") for r in good)
            found = sum(r["articles_found"] for r in rows)
            wanted = sum(r["articles_expected"] for r in rows)
            price = f"{1000 * statistics.mean(costs):>10.2f}" if costs else f"{'n/a':>10}"
            lines.append(
                f"{backend:8}{model:16}{len(rows):>6}{right:>7}{f'{found}/{wanted}':>10}"
                f"{statistics.median(first or [0]):>9.1f}{max(first or [0]):>9.1f}"
                f"{sum(t > 10 for t in first):>9}{statistics.median(job_first or [0]):>10.1f}"
                f"{statistics.median(r['seconds'] for r in good):>10.1f}"
                f"{statistics.median([r['seconds'] for r in jobs] or [0]):>11.1f}{price}"
            )
    lines += ["", "USD/1000 is the estimated model and retrieval cost of 1000 turns of this question mix.",
              "It leaves out fixed costs such as Search Basic, and hosted agent session charges."]
    text = "\n".join(lines)
    print(text)
    write_evidence(EVIDENCE / "model-comparison.txt", text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
