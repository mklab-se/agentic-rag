"""Tool definitions and the tool set that validates, authorizes and runs them."""

import json
import logging
from collections.abc import Awaitable, Callable
from contextvars import ContextVar
from dataclasses import dataclass

from jsonschema import Draft202012Validator, FormatChecker

from voltrieve_agent.events import Emit, trace

logger = logging.getLogger(__name__)

# Set by ToolSet.execute while a handler runs, so handlers can emit trace events.
current_emit: ContextVar[Emit | None] = ContextVar("current_emit", default=None)
# Set by the loop to the turn's correlation id, sent to downstream services as X-Correlation-Id.
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
    # May run alongside other tools of the same model response. Reads may; a tool that changes
    # something waits for them and runs alone.
    concurrent: bool = True


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


def _parse_arguments(name: str, schema: dict, raw_arguments: str) -> tuple[dict, str | None]:
    """The arguments as a dict, or an error message for the model."""
    try:
        arguments = json.loads(raw_arguments or "{}")
    except ValueError as exc:
        return {}, f"Error: arguments for '{name}' are not valid JSON ({exc})."
    errors = sorted(
        Draft202012Validator(schema, format_checker=FormatChecker()).iter_errors(arguments),
        key=lambda e: list(e.path),
    )
    if errors:
        details = "; ".join(
            f"{'.'.join(str(p) for p in e.path) or 'arguments'}: {e.message}" for e in errors
        )
        return {}, f"Error: invalid arguments for '{name}': {details}"
    return arguments, None


class ToolSet:
    def __init__(self, server: list[ServerTool], client: list[ClientTool]):
        self._server = {t.name: t for t in server}
        self._client = {t.name: t for t in client}

    def definitions(self) -> list[dict]:
        # Every server tool is listed whatever the role: execute() enforces roles, so a
        # denied call is visible as an authorization_denied event (and prompt agents
        # cannot hide tools anyway).
        server = [_definition(t.name, t.description, t.parameters) for t in self._server.values()]
        client = [_definition(t.name, t.description, t.parameters) for t in self._client.values()]
        return server + client

    def is_client(self, name: str) -> bool:
        return name in self._client

    def is_concurrent(self, name: str) -> bool:
        tool = self._server.get(name)
        return tool is None or tool.concurrent

    def validate_client(self, name: str, raw_arguments: str) -> str | None:
        """The error to give the model when a client tool call has invalid arguments, else None.
        The client declared the schema, but the model is not bound to it."""
        _, error = _parse_arguments(name, self._client[name].parameters, raw_arguments)
        return error

    async def execute(self, name: str, raw_arguments: str, user: UserContext, emit: Emit) -> str:
        tool = self._server.get(name)
        if tool is None:
            return f"Error: unknown tool '{name}'."
        if tool.required_role is not None and tool.required_role not in user.roles:
            logger.warning(
                "authorization denied: tool %s requires role %s (user %s)",
                tool.name,
                tool.required_role,
                user.oid,
            )
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
        arguments, error = _parse_arguments(name, tool.parameters, raw_arguments)
        if error is not None:
            return error
        token = current_emit.set(emit)
        try:
            return await tool.handler(arguments, user)
        except Exception:  # tool failures go back to the model, not up the stack
            logger.exception("Tool %s failed", name)
            return f"Error: the tool '{name}' failed. Tell the user it is unavailable right now."
        finally:
            current_emit.reset(token)
