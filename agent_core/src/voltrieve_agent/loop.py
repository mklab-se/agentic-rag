"""The orchestration loop: stream the model, run server tools, pause for client tools.

The loop never emits `done`: hosts do, because only they know the backend. On status
"failed" the loop has already emitted an `error` event. Hosts must use turn ids that match
`^[A-Za-z0-9._-]{1,64}$`.
"""

import logging
from dataclasses import dataclass, field
from typing import Literal

from voltrieve_agent.events import AgentEvent, Emit, trace
from voltrieve_agent.instructions import AGENT_INSTRUCTIONS
from voltrieve_agent.model import (
    Completed,
    Failed,
    FunctionCall,
    McpCall,
    ModelClient,
    TextDelta,
)
from voltrieve_agent.tools import (
    ClientTool,
    ServerTool,
    ToolSet,
    UserContext,
    current_correlation_id,
)

logger = logging.getLogger(__name__)

FAILURE_MESSAGES = {
    "model_failed": "The model could not complete the answer.",
    "model_incomplete": "The model stopped before finishing the answer.",
    "model_error": "The model call failed.",
    "too_many_iterations": "The agent did not finish within the allowed number of model calls.",
}


@dataclass
class TurnInput:
    user: UserContext
    conversation_id: str
    turn_id: str
    input: str | list[dict]
    client_tools: list[ClientTool] = field(default_factory=list)
    correlation_id: str | None = None


@dataclass
class TurnOutcome:
    status: Literal["done", "paused", "failed"]
    pending_outputs: list[dict] = field(default_factory=list)
    usage: dict = field(default_factory=dict)
    client_call_ids: list[str] = field(default_factory=list)


def _add_usage(total: dict, usage: dict) -> None:
    for key, value in usage.items():
        if isinstance(value, int | float) and not isinstance(value, bool):
            total[key] = total.get(key, 0) + value


def _output_item(call_id: str, output: str) -> dict:
    return {"type": "function_call_output", "call_id": call_id, "output": output}


async def _fail(emit: Emit, code: str, usage: dict) -> TurnOutcome:
    await emit(AgentEvent("error", {"code": code, "message": FAILURE_MESSAGES[code]}))
    return TurnOutcome("failed", [], usage)


async def run_turn(
    model: ModelClient,
    server_tools: list[ServerTool],
    turn: TurnInput,
    emit: Emit,
    max_iterations: int = 8,
) -> TurnOutcome:
    token = current_correlation_id.set(turn.correlation_id or turn.turn_id)
    try:
        return await _run(model, server_tools, turn, emit, max_iterations)
    finally:
        current_correlation_id.reset(token)


async def _run(model, server_tools, turn, emit, max_iterations) -> TurnOutcome:
    toolset = ToolSet(server_tools, turn.client_tools)
    definitions = toolset.definitions(turn.user)
    usage: dict = {}
    next_input: str | list[dict] = turn.input

    for iteration in range(max_iterations):
        await emit(trace("model_called", "model", f"iteration {iteration + 1}"))
        calls: list[FunctionCall] = []
        text_deltas = 0
        failed: Failed | None = None
        try:
            async for item in model.stream(
                instructions=AGENT_INSTRUCTIONS,
                conversation=turn.conversation_id,
                input=next_input,
                tools=definitions,
            ):
                if isinstance(item, TextDelta):
                    text_deltas += 1
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
                elif isinstance(item, Failed):
                    failed = item
                    break
        except Exception:
            logger.exception("Model stream failed")
            return await _fail(emit, "model_error", usage)

        if failed is not None:
            logger.warning("Model reported %s: %s", failed.code, failed.message)
            code = failed.code if failed.code in FAILURE_MESSAGES else "model_error"
            return await _fail(emit, code, usage)

        await emit(
            trace(
                "model_returned",
                "model",
                f"{text_deltas} text deltas, {len(calls)} tool calls",
                text_deltas=text_deltas,
                tool_calls=len(calls),
            )
        )
        if not calls:
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
            for c in client_calls:
                await emit(
                    trace("client_tool_requested", "tools", c.name, tool=c.name, call_id=c.call_id)
                )
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
            return TurnOutcome("paused", outputs, usage, [c.call_id for c in client_calls])

        if iteration == max_iterations - 1:
            # Give every function_call in the conversation an output, without offering tools.
            try:
                async for item in model.stream(
                    instructions=AGENT_INSTRUCTIONS,
                    conversation=turn.conversation_id,
                    input=outputs,
                    tools=[],
                ):
                    if isinstance(item, Completed):
                        _add_usage(usage, item.usage)
            except Exception:
                logger.exception("Closing model call failed")
            return await _fail(emit, "too_many_iterations", usage)

        next_input = outputs

    return await _fail(emit, "too_many_iterations", usage)
