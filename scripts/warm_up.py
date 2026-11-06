# /// script
# requires-python = ">=3.12"
# dependencies = ["httpx"]
# ///
"""Wake everything that scales to zero, so that a demo does not pay for the cold starts.

    uv run scripts/warm_up.py                once, then exit
    uv run scripts/warm_up.py --keep-warm    then ping the services until Ctrl-C

The Container Apps scale to zero after 5 idle minutes, so warm up right before a demo or use
--keep-warm during it. The first pass asks a real question on each backend, which costs a few
tokens and starts the hosted agent's session. Pings only call /healthz, so they cost nothing.
"""

from __future__ import annotations

import argparse
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).parent))

from voltrieve_client import Api, ApiError, api_token, api_url, azd_value, cached_token

BACKENDS = ("loop", "prompt", "hosted")
SEARCH_QUESTION = "What is the towing capacity of the Fjord?"
STOCK_QUESTION = "How many Ragn are in stock in Stockholm?"
PING_SECONDS = 120
TIMEOUT = 120.0


def ping(name: str, url: str) -> bool:
    began = time.perf_counter()
    try:
        ok = httpx.get(url, timeout=TIMEOUT, follow_redirects=True).is_success
    except httpx.HTTPError:
        ok = False
    print(f"{'ok  ' if ok else 'FAIL'}  {name:26}{time.perf_counter() - began:6.1f} s", flush=True)
    return ok


def turn(url: str, token, backend: str, label: str, question: str) -> bool:
    api = Api(url, token, backend)
    began = time.perf_counter()
    try:
        result = api.turn(question)
        problem = (result.error or {}).get("code") or ("no answer" if not result.text else "")
    except ApiError as exc:
        problem = str(exc)
    finally:
        api.close()
    state = "FAIL" if problem else "ok  "
    print(f"{state}  {backend + ' ' + label:26}{time.perf_counter() - began:6.1f} s  {problem}", flush=True)
    return not problem


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--keep-warm", action="store_true", help="keep pinging until Ctrl-C")
    args = parser.parse_args()
    url = api_url()
    dealer = azd_value("DEALER_URL").rstrip("/")
    services = {"API": f"{url}/healthz", "dealer": f"{dealer}/healthz"}
    token = cached_token(api_token)
    token()  # one sign-in, before the threads need it
    began = time.perf_counter()

    def backend_turns(backend: str) -> bool:
        searched = turn(url, token, backend, "search", SEARCH_QUESTION)
        return turn(url, token, backend, "dealer", STOCK_QUESTION) and searched

    # The services wake on their own, so nothing here has to wait for anything else. The
    # questions wait for the pings only to keep the timings readable.
    targets = {**services, "web client": azd_value("WEB_URL")}
    with ThreadPoolExecutor(len(targets)) as pool:
        results = list(pool.map(ping, targets, targets.values()))
    with ThreadPoolExecutor(len(BACKENDS)) as pool:
        results += pool.map(backend_turns, BACKENDS)
    print(f"Took {time.perf_counter() - began:.1f} s.", flush=True)
    print("All warm." if all(results) else "Something is not healthy: see the lines above.", flush=True)
    if not args.keep_warm:
        return 0 if all(results) else 1
    print(f"Pinging every {PING_SECONDS} s. Press Ctrl-C when the demo is over.", flush=True)
    try:
        while True:
            time.sleep(PING_SECONDS)
            for name, target in services.items():
                ping(name, target)
    except KeyboardInterrupt:
        print("Stopped. The services scale to zero again after 5 idle minutes.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
