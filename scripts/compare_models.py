# /// script
# requires-python = ">=3.12"
# ///
"""Run the routing questions on the own loop with several agent models, one after the other.

    uv run scripts/compare_models.py gpt-5.4-mini gpt-6-luna [--repeats 2]

Each model must have a deployment of the same name. This changes CHAT_DEPLOYMENT on the API
container app for the length of the run, and restores gpt-5.4-mini at the end. Results land in
docs/evidence/models/agent-<model>.json. Needs azd env values and `az login`.
"""

import argparse
import os
import subprocess
import sys
import time
import urllib.request

APP = "ca-api-voltrieve-dev"
DEFAULT = "gpt-5.4-mini"


def set_model(model: str) -> None:
    subprocess.run(
        ["az", "containerapp", "update", "-g", os.environ["AZURE_RESOURCE_GROUP"], "-n", APP,
         "--set-env-vars", f"CHAT_DEPLOYMENT={model}", "--only-show-errors", "-o", "none"],
        check=True,
    )
    time.sleep(45)  # the old revision serves until the new one is ready
    urllib.request.urlopen(f"{os.environ['API_URL']}/healthz", timeout=120).read()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("models", nargs="+")
    parser.add_argument("--repeats", type=int, default=2)
    args = parser.parse_args()
    failures = 0
    try:
        for model in args.models:
            print(f"== {model}", flush=True)
            set_model(model)
            result = subprocess.run(
                ["uv", "run", "tests/routing/check.py", "--backends", "loop",
                 "--repeats", str(args.repeats), "--label", f"agent-{model}"],
                stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True,
            )
            print("\n".join(result.stdout.splitlines()[:16]), flush=True)
            failures += result.returncode != 0
    finally:
        set_model(DEFAULT)
        print(f"restored {DEFAULT}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
