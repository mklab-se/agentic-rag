"""What control does a caller have over parallel tool calls? Asks Foundry directly.

    uv run --project agents/prompt agents/prompt/demo_parallel_setting.py

Sends the Responses API's `parallel_tool_calls` and `tool_choice` with a prompt agent reference,
and `parallel_tool_calls` with a plain model for comparison. Reads FOUNDRY_PROJECT_ENDPOINT,
CHAT_DEPLOYMENT and PROMPT_AGENT_WEB (optional) from the environment. Writes
docs/evidence/parallel-setting.txt.
"""

import os
from pathlib import Path

from azure.ai.projects import AIProjectClient
from azure.identity import DefaultAzureCredential

AGENT = os.environ.get("PROMPT_AGENT_WEB") or "voltrieve-prompt-web"
EVIDENCE = Path(__file__).parents[2] / "docs" / "evidence" / "parallel-setting.txt"
QUESTION = "Tell me the stock in Stockholm and also in Malmö."
TOOL = {
    "type": "function",
    "name": "lookup",
    "description": "Look up the stock in one city. One city per call.",
    "parameters": {"type": "object", "properties": {"city": {"type": "string"}}, "required": ["city"]},
}


def attempt(label: str, call) -> str:
    try:
        response = call()
    except Exception as exc:
        return f"{label}: refused, {str(exc)[:160]}"
    names = [i.type for i in response.output if i.type in ("function_call", "mcp_call")]
    return f"{label}: accepted, {len(names)} tool calls in one response"


def main() -> None:
    agent = {"agent_reference": {"name": AGENT, "type": "agent_reference"}}
    with DefaultAzureCredential() as credential, AIProjectClient(
        endpoint=os.environ["FOUNDRY_PROJECT_ENDPOINT"], credential=credential
    ) as project, project.get_openai_client() as client:
        model = os.environ["CHAT_DEPLOYMENT"]
        lines = [
            attempt("agent, parallel_tool_calls=True", lambda: client.responses.create(
                input=QUESTION, parallel_tool_calls=True, extra_body=agent)),
            attempt("agent, parallel_tool_calls=False", lambda: client.responses.create(
                input=QUESTION, parallel_tool_calls=False, extra_body=agent)),
            attempt("agent, tool_choice=required", lambda: client.responses.create(
                input=QUESTION, tool_choice="required", extra_body=agent)),
            attempt("model, parallel_tool_calls=True", lambda: client.responses.create(
                model=model, input=QUESTION, tools=[TOOL], parallel_tool_calls=True)),
            attempt("model, parallel_tool_calls=False", lambda: client.responses.create(
                model=model, input=QUESTION, tools=[TOOL], parallel_tool_calls=False)),
        ]
    text = "\n".join(lines) + "\n"
    print(text)
    EVIDENCE.write_text(text, encoding="utf-8")


if __name__ == "__main__":
    main()
