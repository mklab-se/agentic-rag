from voltrieve_agent.events import KEEPALIVE, AgentEvent, format_event


def test_event_is_one_sse_block_with_a_single_line_of_ascii_json():
    wire = format_event(AgentEvent("delta", {"text": "a b c\u0085d ö"}))
    text = wire.decode()
    assert text.startswith("event: delta\ndata: ") and text.endswith("\n\n")
    assert text.count("\n") == 3
    for ch in "  \u0085ö":
        assert ch not in text


def test_keepalive_is_an_sse_comment():
    assert KEEPALIVE.startswith(b":") and KEEPALIVE.endswith(b"\n\n")
