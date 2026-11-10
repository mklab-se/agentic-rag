# /// script
# requires-python = ">=3.12"
# dependencies = ["httpx", "pyyaml", "pydantic>=2"]
# ///
"""Run the demo runbook (spec section 13) against the deployed API, once per backend.

    uv run scripts/runbook.py [--backends prompt,loop,hosted] [--steps 2,3,10]

Prints a pass or fail table and saves event sequences and answers as JSON evidence under
docs/evidence/<backend>.json. Evidence holds no tokens, usernames or URLs.

Step 9 as the Chat.User-only user cannot use az: run scripts/denied_demo.py for that part.
Step 12 (Application Insights) is manual; the correlation ids to search for are printed.
Needs `azd env select` (API_URL, API_CLIENT_ID) and `az login` as a user with Chat.User and
TestDrive.Book. Environment overrides: VOLTRIEVE_API_URL, VOLTRIEVE_API_CLIENT_ID.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
import time
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from trace_evidence import resource_group_app, trace_counts, write_report
from voltrieve_client import (  # noqa: E402
    Api, ApiError, Turn, api_token, api_url, booking_request, cached_token, write_evidence,
)
from voltrieve_facts import ROOT, check, load_data, load_dealer, load_questions  # noqa: E402

EVIDENCE = ROOT / "docs" / "evidence"
MAKE_NOISE = {
    "name": "make_noise",
    "description": "Ring the terminal bell on the user's machine. At most 10 times.",
    "parameters": {
        "type": "object",
        "properties": {"times": {"type": "integer", "minimum": 1, "maximum": 10}},
        "required": ["times"],
    },
}
UNSUPPORTED_TOOL = {
    "name": "read_file",
    "description": "Read a file on the user's machine.",
    "parameters": {"type": "object", "properties": {"path": {"type": "string"}}},
}


@dataclass
class Result:
    number: int
    title: str
    status: str  # PASS, FAIL, SKIP, MANUAL
    note: str = ""
    question: str = ""
    correlation_id: str = ""
    turn: Turn | None = None

    def evidence(self) -> dict:
        entry = {
            "step": self.number, "title": self.title, "status": self.status, "note": self.note,
            "question": self.question, "correlation_id": self.correlation_id,
        }
        if self.turn is not None:
            entry["event_sequence"] = [
                f"trace:{d.get('step')}" if t == "trace" else t for t, d in self.turn.events
            ]
            entry["answer"] = self.turn.text
            entry["client_tools_run"] = [{"name": n, "arguments": a, "output": o}
                                         for n, a, o in self.turn.tool_runs]
            entry["usage"] = (self.turn.done or {}).get("usage")
        return entry


def verdict(ok: bool, note: str) -> tuple[str, str]:
    return ("PASS" if ok else "FAIL"), note


def run_backend(backend: str, base: str, token, wanted: set[int]) -> list[Result]:
    api = Api(base, token, backend)
    data, dealer = load_data(), load_dealer()
    questions = {q["step"]: q for q in load_questions() if "step" in q}
    results: list[Result] = []
    conversations: dict[int, str | None] = {}

    def want(n: int) -> bool:
        return not wanted or n in wanted

    def ask(n: int, title: str, message: str, **kwargs) -> Result:
        cid = f"runbook-{backend}-{n}"
        result = Result(n, title, "FAIL", question=message, correlation_id=cid)
        try:
            result.turn = api.turn(message, correlation_id=cid, **kwargs)
        except ApiError as exc:
            result.note = str(exc)
            return result
        conversations[n] = result.turn.conversation_id
        if result.turn.error:
            result.note = f"error event: {result.turn.error.get('code')}"
        return result

    try:
        api_check = api.turn("ping", correlation_id=f"runbook-{backend}-preflight")
        if api_check.error and api_check.error.get("code") == "internal_error":
            raise ApiError(500, "backend failed on a first message")
    except ApiError as exc:
        for n in range(1, 13):
            if want(n):
                results.append(Result(n, "backend unavailable", "SKIP", note=str(exc)[:200]))
        api.close()
        return results

    # 1. Sign-in and roles, from the first trace event.
    if want(1):
        r = ask(1, "Sign in, roles in the trace", "Hello")
        if r.turn and not r.turn.error:
            validated = r.turn.trace("token_validated")
            roles = validated[0].get("roles", []) if validated else []
            r.status, r.note = verdict("Chat.User" in roles, f"roles: {', '.join(roles)}")
        results.append(r)

    # 2 to 8: the factual questions.
    titles = {2: "Grounded, single document", 3: "Shared but different", 4: "Unique feature",
              5: "Absent by design", 6: "Not in the documents", 7: "Cross-document",
              8: "Server tool to the dealer service"}
    for n in range(2, 9):
        if not want(n) and not (n == 2 and want(10)):
            continue
        q = questions[n]
        r = ask(n, titles[n], q["ask"])
        if r.turn and not r.turn.error:
            ok, expected = check(q["expect"], r.turn.text, data, dealer)
            if n == 8:
                called = "check_stock" in [d.get("tool") for d in r.turn.trace("server_tool_called")]
                ok, expected = ok and called, f"{expected}; check_stock called: {called}"
            r.status, r.note = verdict(ok, f"expected {expected}")
        if want(n):
            results.append(r)

    # 9. Booking as the full-role user.
    if want(9):
        r = ask(9, "Book a test drive (full-role user)",
                booking_request())
        if r.turn and not r.turn.error:
            booked = "book_test_drive" in [d.get("tool") for d in r.turn.trace("server_tool_returned")]
            denied = bool(r.turn.trace("authorization_denied"))
            r.status, r.note = verdict(
                booked and not denied,
                f"book_test_drive returned: {booked}, denied: {denied}. "
                "The denied case runs in scripts/denied_demo.py",
            )
        results.append(r)

    # 10. Client tool: declared on the request, answered here, turn continues.
    if want(10):
        beeps: list[str] = []

        def make_noise(arguments: str) -> str:
            beeps.append(arguments)
            return "Rang the terminal bell."

        r = ask(10, "Client tool make_noise", "What is the towing capacity of the Voltrieve Fjord? When you have the answer, beep three times.",
                conversation_id=conversations.get(2), client_tools=[MAKE_NOISE],
                handlers={"make_noise": make_noise})
        if r.turn and not r.turn.error:
            times = None
            if r.turn.tool_runs:
                try:
                    times = json.loads(r.turn.tool_runs[0][1]).get("times")
                except (ValueError, AttributeError):
                    pass
            continued = r.turn.done is not None and bool(r.turn.text)
            r.status, r.note = verdict(
                bool(beeps) and continued,
                f"make_noise requested {len(beeps)} time(s), times={times}, turn continued: {continued}",
            )
        results.append(r)

    # 11. Backend A only: a tool the agent definition lacks.
    if want(11):
        if backend != "prompt":
            results.append(Result(11, "Prompt agent rejects extra tools", "SKIP", note="backend A only"))
        else:
            r = ask(11, "Prompt agent rejects extra tools", "Read the file notes.txt",
                    client_tools=[UNSUPPORTED_TOOL])
            code = (r.turn.error or {}).get("code") if r.turn else None
            r.status, r.note = verdict(code == "unsupported_client_tool",
                                       f"error code: {code}. Foundry's own 400: agents/prompt/demo_rejection.py")
            results.append(r)

    api.close()
    return sorted(results, key=lambda r: r.number)


def save(backend: str, results: list[Result]) -> Path:
    # Model answers are saved verbatim except for the two changes write_evidence makes
    # (em-dash to " - ", absolute paths removed); see docs/evidence/README.md.
    return write_evidence(EVIDENCE / f"{backend}.json", json.dumps({
        "backend": backend,
        "run_at": dt.datetime.now(dt.UTC).isoformat(timespec="seconds"),
        "steps": [r.evidence() for r in results],
    }, indent=2, ensure_ascii=False) + "\n")


def table(all_results: dict[str, list[Result]]) -> str:
    backends = list(all_results)
    numbers = sorted({r.number for rs in all_results.values() for r in rs})
    titles = {r.number: r.title for rs in all_results.values() for r in rs if r.title != "backend unavailable"}
    header = f"{'step':<5}{'what':<54}" + "".join(f"{b:<9}" for b in backends)
    lines = [header, "-" * len(header)]
    for n in numbers:
        cells = ""
        for b in backends:
            found = next((r for r in all_results[b] if r.number == n), None)
            cells += f"{found.status if found else '-':<9}"
        lines.append(f"{n:<5}{titles.get(n, ''):<54}{cells}")
    for b, rs in all_results.items():
        for r in rs:
            if r.status in ("FAIL", "SKIP") or r.status == "MANUAL":
                lines.append(f"  [{b} step {r.number} {r.status}] {r.note}")
    return "\n".join(lines) + "\n"


REQUIRED_SERVICES = {
    "loop": {"voltrieve-api", "voltrieve-dealer"},
    "prompt": {"voltrieve-api", "voltrieve-dealer", "responsesapi"},
    "hosted": {"voltrieve-api", "voltrieve-dealer", "responsesapi", "agentsv2", "voltrieve-hosted"},
}


def check_traces(all_results: dict[str, list[Result]]) -> None:
    """Step 12: one trace id must reach every service of the backend. Ingestion takes a few minutes."""
    group, app = resource_group_app()
    counts: dict[str, list[list]] = {}
    deadline = time.monotonic() + 420
    while True:
        counts = {b: trace_counts(group, app, b, 1) for b in all_results}
        seen = {b: {row[0] for row in rows} for b, rows in counts.items()}
        if all(REQUIRED_SERVICES[b] <= seen[b] for b in all_results) or time.monotonic() > deadline:
            break
        time.sleep(30)
    write_report(counts)
    for backend, results in all_results.items():
        missing = REQUIRED_SERVICES[backend] - seen[backend]
        status = "FAIL" if missing else "PASS"
        results.append(Result(12, "Follow one trace id in Application Insights", status,
                              note=f"missing {sorted(missing)}" if missing else "all services in one trace"))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--backends", default="prompt,loop,hosted")
    parser.add_argument("--steps", default="", help="comma separated step numbers (default all)")
    args = parser.parse_args()
    wanted = {int(s) for s in args.steps.split(",") if s}

    base = api_url()
    token = cached_token(api_token)
    all_results: dict[str, list[Result]] = {}
    for backend in args.backends.split(","):
        print(f"running {backend} ...", flush=True)
        all_results[backend] = run_backend(backend, base, token, wanted)
        print(f"  evidence: {save(backend, all_results[backend]).relative_to(ROOT)}")
    if not wanted or 12 in wanted:
        check_traces(all_results)
    text = table(all_results)
    print("\n" + text)
    write_evidence(EVIDENCE / "runbook-table.txt", text)
    failed = any(r.status == "FAIL" for rs in all_results.values() for r in rs)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
