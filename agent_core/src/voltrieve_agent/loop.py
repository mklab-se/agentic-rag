"""The orchestration loop: stream the model, run server tools, pause for client tools."""

from dataclasses import dataclass, field
from typing import Literal

from voltrieve_agent.events import AgentEvent, Emit, trace
from voltrieve_agent.instructions import AGENT_INSTRUCTIONS
from voltrieve_agent.model import Completed, FunctionCall, McpCall, ModelClient, TextDelta
from voltrieve_agent.tools import ClientTool, ServerTool, ToolSet, UserContext, current_correlation_id


@dataclass
class TurnInput:
    user: UserContext
    conversation_id: str
    turn_id: str
    input: str | list[dict]
    client_tools: list[ClientTool] = field(default_factory=list)


@dataclass
class TurnOutcome:
    status: Literal["done", "paused"]
    pending_outputs: list[dict] = field(default_factory=list)
    usage: dict = field(default_factory=dict)


def _add_usage(total: dict, usage: dict) -> None:
    for key, value in usage.items():
        if isinstance(value, int | float) and not isinstance(value, bool):
            total[key] = total.get(key, 0) + value


def _output_item(call_id: str, output: str) -> dict:
    return {"type": "function_call_output", "call_id": call_id, "output": output}


async def run_turn(
    model: ModelClient,
    server_tools: list[ServerTool],
    turn: TurnInput,
    emit: Emit,
    max_iterations: int = 8,
) -> TurnOutcome:
    toolset = ToolSet(server_tools, turn.client_tools)
    definitions = toolset.definitions(turn.user)
    current_correlation_id.set(turn.turn_id)
    usage: dict = {}
    next_input: str | list[dict] = turn.input

    for _ in range(max_iterations):
        calls: list[FunctionCall] = []
        async for item in model.stream(
            instructions=AGENT_INSTRUCTIONS,
            conversation=turn.conversation_id,
            input=next_input,
            tools=definitions,
        ):
            if isinstance(item, TextDelta):
                await emit(AgentEvent("delta", {"text": item.text}))
            elif isinstance(item, FunctionCall):
                calls.append(item)
            elif isinstance(item, McpCall):
                await emit(
                    trace(
                        "mcp_tool_called",
                        "model",
                        item.name,
                        server=item.server,
                        output_preview=item.output_preview,
                    )
                )
            elif isinstance(item, Completed):
                _add_usage(usage, item.usage)

        if not calls:
            await emit(AgentEvent("done", {"turn_id": turn.turn_id, "usage": usage}))
            return TurnOutcome("done", [], usage)

        outputs: list[dict] = []
        client_calls: list[FunctionCall] = []
        for call in calls:
            if toolset.is_client(call.name):
                client_calls.append(call)
                continue
            await emit(
                trace(
                    "server_tool_called",
                    "tools",
                    call.name,
                    tool=call.name,
                    arguments=call.arguments,
                )
            )
            output = await toolset.execute(call.name, call.arguments, turn.user, emit)
            await emit(
                trace(
                    "server_tool_returned",
                    "tools",
                    call.name,
                    tool=call.name,
                    output_preview=output[:500],
                )
            )
            outputs.append(_output_item(call.call_id, output))

        if client_calls:
            await emit(
                AgentEvent(
                    "client_tool_calls",
                    {
                        "turn_id": turn.turn_id,
                        "calls": [
                            {"call_id": c.call_id, "name": c.name, "arguments": c.arguments}
                            for c in client_calls
                        ],
                    },
                )
            )
            return TurnOutcome("paused", outputs, usage)

        next_input = outputs

    await emit(
        AgentEvent(
            "error",
            {
                "code": "too_many_iterations",
                "message": f"The agent did not finish within {max_iterations} model calls.",
            },
        )
    )
    return TurnOutcome("done", [], usage)
