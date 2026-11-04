# /// script
# requires-python = ">=3.12"
# dependencies = ["httpx"]
# ///
"""Smoke test of a deployment: is everything up and does one question get answered?

    uv run scripts/smoke.py [--backends prompt,loop,hosted]

Checks, in order:
  1. GET /healthz on the API and on the dealer service (no sign-in needed)
  2. the search indexer's last run succeeded
  3. one short turn on each backend through the API: an answer and `done`, no `error` event

Prints one line per check and exits 1 if any failed. It needs `azd env select` (API_URL,
DEALER_URL, SEARCH_ENDPOINT, API_CLIENT_ID) and `az login` as a user with Chat.User.
scripts/deploy-agents.sh runs it at the end.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent))

from voltrieve_client import Api, ApiError, api_token, api_url, azd_value, cached_token  # noqa: E402

INDEXER_NAME = "voltrieve-docs-indexer"
SEARCH_API_VERSION = "2026-08-01-preview"
QUESTION = "What is the towing capacity of the Fjord?"

Check = tuple[str, bool, str]  # name, passed, note


def check_health(name: str, base_url: str, http: httpx.Client) -> Check:
    try:
        response = http.get(f"{base_url.rstrip('/')}/healthz", timeout=60.0)
    except httpx.HTTPError as exc:
        return name, False, type(exc).__name__
    ok = response.status_code == 200 and response.json().get("status") == "ok"
    return name, ok, f"HTTP {response.status_code}"


def check_indexer(search_endpoint: str, token: str, http: httpx.Client) -> Check:
    name = "search indexer"
    try:
        response = http.get(
            f"{search_endpoint.rstrip('/')}/indexers/{INDEXER_NAME}/status",
            params={"api-version": SEARCH_API_VERSION},
            headers={"Authorization": f"Bearer {token}"},
            timeout=30.0,
        )
    except httpx.HTTPError as exc:
        return name, False, type(exc).__name__
    if response.status_code != 200:
        return name, False, f"HTTP {response.status_code}"
    last = response.json().get("lastResult") or {}
    status = last.get("status", "never ran")
    failed = last.get("itemsFailed", 0)
    return name, status == "success" and failed == 0, f"last run {status}, {failed} items failed"


def check_turn(backend: str, api: Api) -> Check:
    name = f"turn on {backend}"
    try:
        turn = api.turn(QUESTION, correlation_id=f"smoke-{backend}")
    except ApiError as exc:
        return name, False, str(exc)[:200]
    if turn.error:
        return name, False, f"error event: {turn.error.get('code')}"
    ok = turn.done is not None and bool(turn.text)
    return name, ok, f"{len(turn.text)} characters, done: {turn.done is not None}"


def run_checks(
    api_base: str,
    dealer_base: str,
    search_endpoint: str,
    search_token: Callable[[], str],
    user_token: Callable[[], str],
    backends: list[str],
    http: httpx.Client,
) -> list[Check]:
    results = [
        check_health("api /healthz", api_base, http),
        check_health("dealer /healthz", dealer_base, http),
        check_indexer(search_endpoint, search_token(), http),
    ]
    for backend in backends:
        api = Api(api_base, user_token, backend)
        try:
            results.append(check_turn(backend, api))
        finally:
            api.close()
    return results


def search_token() -> str:
    result = subprocess.run(
        ["az", "account", "get-access-token", "--scope", "https://search.azure.com/.default",
         "--query", "accessToken", "-o", "tsv"],
        capture_output=True, text=True, check=False,
    )
    token = result.stdout.strip()
    if result.returncode != 0 or not token:
        raise SystemExit("Could not get a search token from the az CLI. Run `az login`.")
    return token


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--backends", default="prompt,loop,hosted")
    args = parser.parse_args()
    with httpx.Client() as http:
        results = run_checks(
            api_url(), azd_value("DEALER_URL"), azd_value("SEARCH_ENDPOINT"), search_token,
            cached_token(api_token), [b for b in args.backends.split(",") if b], http,
        )
    for name, ok, note in results:
        print(f"{'PASS' if ok else 'FAIL'}  {name:<18}{note}")
    failed = [name for name, ok, _ in results if not ok]
    print(f"\n{len(results) - len(failed)}/{len(results)} checks passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
