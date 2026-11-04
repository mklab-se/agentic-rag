import json

from voltrieve_agent.events import AgentEvent

# An SSE comment: ignored by clients, but keeps idle connections open.
KEEPALIVE = b": keep-alive\n\n"


def format_event(event: AgentEvent) -> bytes:
    """One server-sent event: `event:` is the type, `data:` a single line of JSON.

    ASCII only: U+2028, U+2029 and U+0085 would be taken as line breaks by readers that split
    lines on them (httpx does), which would corrupt the event."""
    data = json.dumps(event.data, ensure_ascii=True, separators=(",", ":"))
    return f"event: {event.type}\ndata: {data}\n\n".encode()
