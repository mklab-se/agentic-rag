"""Tool definitions and the tool set that validates, authorizes and runs them."""

import json
from collections.abc import Awaitable, Callable
from contextvars import ContextVar
from dataclasses import dataclass

from jsonschema import Draft202012Validator

from voltrieve_agent.events import Emit, trace

# Set by ToolSet.execute while a handler runs, so handlers can emit trace events.
current_emit: ContextVar[Emit | None] = ContextVar("current_emit", default=None)
# Set by the loop to the turn id, sent to downstream services as X-Correlation-Id.
current_correlation_id: ContextVar[str | None] = ContextVar("current_correlation_id", default=None)


@dataclass(frozen=True)
class UserContext:
    oid: str
    username: str
    roles: frozenset[str]


@dataclass(frozen=True)
class ServerTool:
    name: str
    description: str
    parameters: dict
    handler: Callable[[dict, UserContext], Awaitable[str]]
    required_role: str | None = None


@dataclass(frozen=True)
class ClientTool:
    name: str
    description: str
    parameters: dict


def _definition(name: str, description: str, parameters: dict) -> dict:
    return {
        "type": "function",
        "name": name,
        "description": description,
        "parameters": parameters,
        "strict": False,
    }


class ToolSet:
    def __init__(self, server: list[ServerTool], client: list[ClientTool]):
        self._server = {t.name: t for t in server}
        self._client = {t.name: t for t in client}

    def definitions(self, user: UserContext) -> list[dict]:
        server = [
            _definition(t.name, t.description, t.parameters)
            for t in self._server.values()
            if t.required_role is None or t.required_role in user.roles
        ]
        client = [_definition(t.name, t.description, t.parameters) for t in self._client.values()]
        return server + client

    def is_client(self, name: str) -> bool:
        return name in self._client

    async def execute(self, name: str, raw_arguments: str, user: UserContext, emit: Emit) -> str:
        tool = self._server.get(name)
        if tool is None:
            return f"Error: unknown tool '{name}'."
        if tool.required_role is not None and tool.required_role not in user.roles:
            await emit(
                trace(
                    "authorization_denied",
                    "tools",
                    f"{tool.name} requires role {tool.required_role}",
                    tool=tool.name,
                    required_role=tool.required_role,
                )
            )
            return (
                f"Refused: the signed-in user is not allowed to use '{tool.name}' "
                f"(requires role {tool.required_role})."
            )
        try:
            arguments = json.loads(raw_arguments or "{}")
        except ValueError as exc:
            return f"Error: arguments for '{name}' are not valid JSON ({exc})."
        errors = sorted(
            Draft202012Validator(tool.parameters).iter_errors(arguments),
            key=lambda e: list(e.path),
        )
        if errors:
            details = "; ".join(
                f"{'.'.join(str(p) for p in e.path) or 'arguments'}: {e.message}" for e in errors
            )
            return f"Error: invalid arguments for '{name}': {details}"
        token = current_emit.set(emit)
        try:
            return await tool.handler(arguments, user)
        except Exception as exc:  # tool failures go back to the model, not up the stack
            return f"Error: '{name}' failed ({type(exc).__name__}: {exc})."
        finally:
            current_emit.reset(token)
