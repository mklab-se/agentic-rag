# /// script
# requires-python = ">=3.12"
# dependencies = ["httpx"]
# ///
"""A client declares a tool the server has never seen, as a thermal camera would.

    uv run scripts/new_client_tool_demo.py

Nothing about `set_emissivity` exists in the API, the agents or Foundry: it is declared only here,
in the request. Backends loop and hosted must relay the call to this script and finish the turn.
Backend prompt must refuse it, since a prompt agent's tools are fixed in its definition.
No camera is involved; the handler stands in for one. Writes docs/evidence/new-client-tool.txt.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from voltrieve_client import Api, api_token, api_url, cached_token, write_evidence

SET_EMISSIVITY = {
    "name": "set_emissivity",
    "description": "Set the emissivity used by the camera for temperature measurement.",
    "parameters": {
        "type": "object",
        "properties": {"value": {"type": "number", "minimum": 0.01, "maximum": 1.0}},
        "required": ["value"],
        "additionalProperties": False,
    },
}
EVIDENCE = Path(__file__).parent.parent / "docs" / "evidence" / "new-client-tool.txt"


def main() -> int:
    token = cached_token(api_token)
    url = api_url()
    lines = []
    passed = True
    for backend in ("loop", "hosted", "prompt"):
        api = Api(url, token, backend)
        received: list[float] = []

        def camera(arguments: str) -> str:
            received.append(json.loads(arguments)["value"])
            return f"Emissivity is now {received[-1]}."

        turn = api.turn("Set the emissivity on my camera to 0.95.",
                        client_tools=[SET_EMISSIVITY], handlers={"set_emissivity": camera})
        api.close()
        if backend == "prompt":
            code = (turn.error or {}).get("code")
            ok = code == "unsupported_client_tool" and not received
            lines.append(f"{'PASS' if ok else 'FAIL'}  prompt  refused as expected, error: {code}")
        else:
            ok = received == [0.95] and turn.done is not None
            lines.append(f"{'PASS' if ok else 'FAIL'}  {backend}  tool received {received}, "
                         f"answer: {turn.text[:90]!r}")
        passed &= ok
        print(lines[-1], flush=True)
    write_evidence(EVIDENCE, "\n".join(lines) + "\n")
    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(main())
