import json

from voltrieve_agent.events import AgentEvent

# An SSE comment: ignored by clients, but keeps idle connections open.
KEEPALIVE = b": keep-alive\n\n"


def format_event(event: AgentEvent) -> bytes:
    """One server-sent event: `event:` is the type, `data:` a single line of JSON."""
    data = json.dumps(event.data, ensure_ascii=False, separators=(",", ":"))
    return f"event: {event.type}\ndata: {data}\n\n".encode()
