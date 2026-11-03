# /// script
# requires-python = ">=3.12"
# dependencies = ["httpx", "pyyaml"]
# ///
"""Grounding check: ask each backend the factual questions through the deployed API and compare
the answers with data/voltrieve.yaml. Not-documented questions pass when the answer does not
invent a value. Prints every answer. Exits 1 on any miss.

    uv run tests/grounding/check.py [--backends prompt,loop,hosted] [--only id,id]

Needs `azd env select` (API_URL, API_CLIENT_ID) and `az login` as a user with Chat.User.
Environment overrides: VOLTRIEVE_API_URL, VOLTRIEVE_API_CLIENT_ID.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))

from voltrieve_client import Api, ApiError, api_token, api_url, cached_token  # noqa: E402
from voltrieve_facts import check, load_data, load_dealer, load_questions  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--backends", default="prompt,loop,hosted")
    parser.add_argument("--only", default="", help="comma separated question ids")
    args = parser.parse_args()

    questions = load_questions()
    if args.only:
        wanted = set(args.only.split(","))
        questions = [q for q in questions if q["id"] in wanted]
    data, dealer = load_data(), load_dealer()
    base = api_url()
    token = cached_token(api_token)

    misses = 0
    for backend in args.backends.split(","):
        print(f"\n== backend: {backend}")
        api = Api(base, token, backend)
        try:
            for q in questions:
                try:
                    turn = api.turn(q["ask"], correlation_id=f"grounding-{backend}-{q['id']}")
                except ApiError as exc:
                    print(f"MISS {q['id']}: {exc}")
                    misses += 1
                    continue
                if turn.error:
                    ok, expected = False, f"no error event, got {turn.error.get('code')}"
                else:
                    ok, expected = check(q["expect"], turn.text, data, dealer)
                misses += not ok
                print(f"{'PASS' if ok else 'MISS'} {q['id']}: {q['ask']}")
                print(f"     expected: {expected}")
                print(f"     answer:   {' '.join(turn.text.split())[:400]}")
        finally:
            api.close()
    print(f"\n{misses} miss(es)")
    return 1 if misses else 0


if __name__ == "__main__":
    sys.exit(main())
