"""Show that a prompt agent refuses per-request tools.

    uv run demo_rejection.py

Sends `tools` together with an agent reference and prints the 400 Foundry answers with
("Not allowed when agent is specified."). This is why backend A needs the client tools in the
agent definition. Reads FOUNDRY_PROJECT_ENDPOINT (and optionally PROMPT_AGENT_WEB) from the
environment; calls only the project, with Entra credentials.
"""

import os
import sys


def main() -> int:
    endpoint = os.environ.get("FOUNDRY_PROJECT_ENDPOINT", "").strip()
    if not endpoint:
        print("Missing environment variable FOUNDRY_PROJECT_ENDPOINT.", file=sys.stderr)
        return 2
    agent = os.environ.get("PROMPT_AGENT_WEB") or "voltrieve-prompt-web"

    import openai
    from azure.ai.projects import AIProjectClient
    from azure.identity import DefaultAzureCredential

    tool = {
        "type": "function",
        "name": "make_noise",
        "description": "Ring the terminal bell.",
        "parameters": {"type": "object", "properties": {}},
        "strict": False,
    }
    with DefaultAzureCredential() as credential, AIProjectClient(
        endpoint=endpoint, credential=credential
    ) as project:
        client = project.get_openai_client()
        try:
            client.responses.create(
                input="Hello",
                tools=[tool],
                extra_body={"agent_reference": {"name": agent, "type": "agent_reference"}},
            )
        except openai.BadRequestError as exc:
            print(f"{exc.status_code} invalid_payload: {exc.message}")
            return 0
    print("Unexpected: the request was accepted.", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
