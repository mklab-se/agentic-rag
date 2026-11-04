# /// script
# requires-python = ">=3.12,<3.13"
# dependencies = ["voltrieve-api", "voltrieve-agent-core", "httpx"]
#
# [tool.uv.sources]
# voltrieve-api = { path = "../api" }
# voltrieve-agent-core = { path = "../agent_core" }
# ///
"""Runbook step 9, the denied case: a user with only the Chat.User role asks for a test drive.

    uv run scripts/denied_demo.py [--backend loop|prompt]

The tester account that holds only Chat.User cannot sign in through az, so this runs the real
API in this process with a fake token validator that returns the roles {Chat.User}, against the
real Foundry backend. Expect an authorization_denied trace event and a polite refusal, and no
call to the dealer service.

Needs `azd env select` and `az login` (the signed-in user needs access to the Foundry project;
nothing else is called). Settings come from the azd environment; no token is sent anywhere.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from voltrieve_client import azd_value, booking_request, parse_sse  # noqa: E402

AZD_SETTINGS = ("FOUNDRY_PROJECT_ENDPOINT", "CHAT_DEPLOYMENT", "SEARCH_ENDPOINT", "DEALER_URL",
                "DEALER_CLIENT_ID")


async def run(backend: str) -> int:
    import httpx
    from app.auth import Claims
    from app.main import create_app
    from app.settings import Settings

    class ChatUserOnly:
        async def validate(self, authorization):
            return Claims("00000000-0000-0000-0000-00000000dead", "chat.user@example.invalid",
                          "demo", ["Chat.User"])

    app = create_app(Settings(agent_backend=backend, log_level="WARNING"), validator=ChatUserOnly())
    try:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://demo",
                                     timeout=180.0) as client:
            response = await client.post("/chat", json={"message": booking_request()})
            response.raise_for_status()
            events = list(parse_sse(response.text.splitlines()))
    finally:
        await app.state.registry.close()

    for kind, data in events:
        if kind == "trace":
            print(f"trace  {data.get('step'):<24} {data.get('detail', '')}")
        elif kind == "error":
            print(f"error  {data}")
    answer = "".join(d.get("text", "") for k, d in events if k == "delta")
    print("\nanswer:", " ".join(answer.split()))
    denied = any(k == "trace" and d.get("step") == "authorization_denied" for k, d in events)
    print("\nPASS: authorization_denied emitted" if denied else "\nFAIL: no authorization_denied event")
    return 0 if denied else 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--backend", default="loop", choices=["loop", "prompt"])
    args = parser.parse_args()
    os.environ.setdefault("TENANT_ID", "00000000-0000-0000-0000-0000000000aa")
    os.environ.setdefault("API_CLIENT_ID", "00000000-0000-0000-0000-0000000000cc")
    for name in AZD_SETTINGS:
        os.environ.setdefault(name, azd_value(name))
    return asyncio.run(run(args.backend))


if __name__ == "__main__":
    sys.exit(main())
