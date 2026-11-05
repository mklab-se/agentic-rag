# /// script
# requires-python = ">=3.12"
# dependencies = ["httpx", "pyyaml"]
# ///
"""Routing check: does each backend reach the right knowledge bases, and does it do so at once?

Each question says which sources it needs. For every backend and repeat this asks the deployed
API and reads the trace:

  right     the sources used are exactly the expected ones
  vain      a source was used that the question did not need
  missed    a needed source was not used
  together  a two source question reached both within one model step, with overlapping calls
  steps     model calls in the turn. Fewer is faster for the user.
  articles  for parts questions, every expected article number is in the answer
  invented  an article number in the answer that does not exist

    uv run tests/routing/check.py [--backends prompt,loop,hosted] [--repeats 3] [--only a,b] [--workers 1]

Writes docs/evidence/routing.txt and routing.json unless --no-save. Exits 1 when any question is
below 100 percent on routing or articles. Needs `azd env select` and `az login` with Chat.User.
"""

from __future__ import annotations

import argparse
import json
import re
import statistics
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass, field
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

from voltrieve_client import Api, ApiError, api_token, api_url, cached_token, write_evidence  # noqa: E402

QUESTIONS = Path(__file__).with_name("questions.yaml")
INDEX = ROOT / "data" / "generated" / "parts-index.json"
EVIDENCE = ROOT / "docs" / "evidence"
ARTICLE = re.compile(r"VP-\d{5}")
SOURCES = {
    "get_curated_answer": "curated",
    "search_voltrieve_docs": "docs",
    "search_spare_parts": "parts",
    "voltrieve-kb": "docs",
    "voltrieve-parts-kb": "parts",
}


@dataclass
class Run:
    backend: str
    question: str
    group: str
    repeat: int
    seconds: float = 0.0
    first_text_seconds: float | None = None
    used: list[str] = field(default_factory=list)
    calls: int = 0
    steps: int = 0
    together: bool | None = None
    saved_ms: int = 0
    articles_expected: int = 0
    articles_found: int = 0
    invented: list[str] = field(default_factory=list)
    error: str = ""
    answer: str = ""
    expected: list[str] = field(default_factory=list)
    topic: str | None = None
    expected_topic: str | None = None
    final: bool = False

    @property
    def right(self) -> bool:
        return (
            not self.error
            and sorted(self.used) == sorted(self.expected)
            and self.topic == self.expected_topic
        )

    @property
    def vain(self) -> list[str]:
        return sorted(set(self.used) - set(self.expected))

    @property
    def missed(self) -> list[str]:
        return sorted(set(self.expected) - set(self.used))


def overlap(calls: list[dict]) -> bool:
    timed = [c for c in calls if c.get("started_ms") is not None and c.get("finished_ms") is not None]
    timed.sort(key=lambda c: c["started_ms"])
    return any(b["started_ms"] < a["finished_ms"] for a, b in zip(timed, timed[1:]))


def read_trace(run: Run, turn) -> None:
    server = [c for c in turn.trace("server_tool_called") if c.get("tool") in SOURCES]
    run.topic = next((json.loads(c.get("arguments") or "{}").get("topic") for c in server
                      if SOURCES[c["tool"]] == "curated"), None)
    run.final = bool(turn.trace("final_answer_sent"))
    mcp = [c for c in turn.trace("mcp_tool_called") if c.get("server") in SOURCES]
    run.used = sorted({SOURCES[c["tool"]] for c in server} | {SOURCES[c["server"]] for c in mcp})
    run.calls = len(server) + len(mcp)
    run.steps = len(turn.trace("model_called"))
    if len(run.expected) > 1:
        if server:
            by_step: dict[int, set[str]] = {}
            for call in server:
                by_step.setdefault(call.get("iteration", 0), set()).add(SOURCES[call["tool"]])
            run.together = any(len(s) > 1 for s in by_step.values()) and bool(
                turn.trace("tools_parallel_started")
            )
        else:
            run.together = overlap(mcp)
    finished = turn.trace("tools_parallel_finished")
    run.saved_ms = sum(f.get("one_by_one_ms", 0) - f.get("wall_ms", 0) for f in finished)


def expected_articles(question: dict, index: dict) -> set[str]:
    wanted = set(index["jobs"].get(question.get("job", ""), []))
    wanted |= set(index["jobs"].get(question.get("also_job", ""), []))
    target = question.get("article")
    if target:
        wanted |= {
            p["article"] for p in index["parts"]
            if p["key"] == target["key"] and target["fits"] in p["fits"]
        }
    return wanted


def message(question: dict, index: dict) -> str:
    reverse = question.get("reverse")
    if not reverse:
        return question["ask"]
    part = next(
        p for p in index["parts"] if p["key"] == reverse["key"] and reverse["fits"] in p["fits"]
    )
    return question["ask"].format(article=part["article"])


def ask(url, token, backend: str, question: dict, repeat: int, index: dict) -> Run:
    run = Run(backend, question["id"], question["group"], repeat, expected=question["expect"],
              expected_topic=question.get("topic"))
    wanted = expected_articles(question, index)
    known = {p["article"] for p in index["parts"]}
    api = Api(url, token, backend)
    began = time.perf_counter()
    try:
        turn = api.turn(message(question, index), correlation_id=f"routing-{backend}-{question['id']}-{repeat}")
    except ApiError as exc:
        run.error = str(exc)
        return run
    finally:
        api.close()
    run.seconds = round(time.perf_counter() - began, 2)
    if turn.error:
        run.error = str(turn.error.get("code"))
    run.answer = turn.text
    read_trace(run, turn)
    mentioned = set(ARTICLE.findall(turn.text))
    run.articles_expected = len(wanted)
    run.articles_found = len(wanted & mentioned)
    run.invented = sorted(mentioned - known)
    return run


def percent(part: int, whole: int) -> str:
    return f"{100 * part // whole} %" if whole else "n/a"


def median(values: list[float]) -> float:
    return round(statistics.median(values), 1) if values else 0.0


def report(runs: list[Run], backends: list[str]) -> str:
    lines = ["Routing per backend and question group", ""]
    lines.append(f"{'backend':8}{'group':7}{'runs':>5}{'right':>7}{'vain':>6}{'missed':>8}"
                 f"{'together':>10}{'steps':>7}{'calls':>7}{'seconds':>9}")
    for backend in backends:
        for group in ("curated", "none", "docs", "parts", "both"):
            rows = [r for r in runs if r.backend == backend and r.group == group]
            if not rows:
                continue
            pairs = [r for r in rows if r.together is not None]
            lines.append(
                f"{backend:8}{group:7}{len(rows):>5}"
                f"{percent(sum(r.right for r in rows), len(rows)):>7}"
                f"{sum(bool(r.vain) for r in rows):>6}{sum(bool(r.missed) for r in rows):>8}"
                f"{percent(sum(bool(r.together) for r in pairs), len(pairs)):>10}"
                f"{median([r.steps for r in rows]):>7}{median([r.calls for r in rows]):>7}"
                f"{median([r.seconds for r in rows]):>9}"
            )
    lines += ["", "Article numbers in the answers", ""]
    for backend in backends:
        rows = [r for r in runs if r.backend == backend and r.articles_expected]
        expected = sum(r.articles_expected for r in rows)
        found = sum(r.articles_found for r in rows)
        complete = sum(r.articles_found == r.articles_expected for r in rows)
        invented = sum(len(r.invented) for r in rows)
        lines.append(f"{backend:8}{found} of {expected} found, {complete} of {len(rows)} answers "
                     f"complete, {invented} invented")
    saved = [r.saved_ms for r in runs if r.saved_ms]
    if saved:
        lines += ["", f"Parallel tool runs saved a median of {median(saved) / 1000} s "
                      f"over {len(saved)} turns (own loop and hosted agent)."]
    lines += ["", "Runs that were not right", ""]
    for r in runs:
        partial = r.articles_found != r.articles_expected
        if not r.right or r.together is False or partial or r.invented:
            lines.append(
                f"{r.backend} {r.question} #{r.repeat}: used {r.used}, expected {r.expected}, "
                f"together {r.together}, articles {r.articles_found}/{r.articles_expected}, "
                f"invented {r.invented}, error {r.error or 'none'}"
            )
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--backends", default="prompt,loop,hosted")
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--only", default="")
    parser.add_argument("--workers", type=int, default=1)
    parser.add_argument("--no-save", action="store_true")
    args = parser.parse_args()

    questions = yaml.safe_load(QUESTIONS.read_text(encoding="utf-8"))["questions"]
    if args.only:
        questions = [q for q in questions if q["id"] in args.only.split(",")]
    index = json.loads(INDEX.read_text(encoding="utf-8"))
    backends = args.backends.split(",")
    url = api_url()
    token = cached_token(api_token)
    jobs = [(b, q, r + 1) for r in range(args.repeats) for q in questions for b in backends]

    def timed(position: int, job: tuple) -> Run:
        run = ask(url, token, job[0], job[1], job[2], index)
        print(f"{position + 1}/{len(jobs)} {run.backend} {run.question} {run.seconds} s "
              f"{run.used} {run.error}", file=sys.stderr, flush=True)
        return run

    with ThreadPoolExecutor(args.workers) as pool:
        runs = list(pool.map(timed, range(len(jobs)), jobs))
    text = report(runs, backends)
    print(text)
    if not args.no_save:
        write_evidence(EVIDENCE / "routing.txt", text)
        (EVIDENCE / "routing.json").write_text(
            json.dumps([asdict(r) for r in runs], indent=1, ensure_ascii=False).replace("\u2014", "-") + "\n",
            encoding="utf-8",
        )
    failed = [r for r in runs if not r.right or r.articles_found != r.articles_expected or r.invented]
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
