"""Smoke test: known questions must retrieve the expected document."""

from dataclasses import dataclass

from voltrieve_search.retrieve import retrieve

TOP_N = 5


@dataclass
class SmokeQuestion:
    question: str
    expect_title_contains: str
    expect_doc_type: str


@dataclass
class SmokeOutcome:
    question: str
    passed: bool
    top_titles: list[str]


def run_smoke(client, kb_name: str, questions: list[SmokeQuestion]) -> list[SmokeOutcome]:
    outcomes = []
    for q in questions:
        result = retrieve(client, kb_name, q.question)
        refs = result.references[:TOP_N]
        sources = [r.source_data or {} for r in refs]
        passed = any(
            q.expect_title_contains in str(s.get("title", "")) and s.get("doc_type") == q.expect_doc_type
            for s in sources
        )
        outcome = SmokeOutcome(q.question, passed, [str(s.get("title", "")) for s in sources])
        print(f"{'PASS' if passed else 'FAIL'}  {q.question}  ->  {', '.join(outcome.top_titles)}")
        if result.partial:
            for activity in result.activity:
                if "error" in activity:
                    print(f"  partial result, activity error: {activity['error']}")
        outcomes.append(outcome)
    return outcomes
