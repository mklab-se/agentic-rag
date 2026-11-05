"""The chat view: bubbles in the scrollback, one status line, a trace only on request."""

import io

from rich.console import Console

from voltrieve_cli.render import ChatView, bubble_width, split_sources


def terminal(width=100, height=30):
    return Console(file=io.StringIO(), force_terminal=True, width=width, height=height,
                   color_system=None, legacy_windows=False)


def strip_ansi(text):
    import re

    return re.sub(r"\x1b\[[0-9;?]*[A-Za-z]", "", text)


def output(console):
    return strip_ansi(console.file.getvalue())


def test_your_message_sits_on_the_right_and_the_answer_on_the_left():
    console = terminal()
    view = ChatView(console)
    view.user("Hi")
    with view:
        view.on_event("delta", {"text": "Hello there"})
    lines = output(console).splitlines()
    mine = next(line for line in lines if "Hi" in line and "│" in line)
    theirs = next(line for line in reversed(lines) if "Hello there" in line)
    assert mine.index("│") > 60
    assert theirs.index("│") < 3


def test_markdown_is_rendered_and_not_shown_as_codes():
    console = terminal()
    view = ChatView(console)
    with view:
        view.on_event("delta", {"text": "**Lumen** is good\n\n- one\n- two"})
    text = output(console)
    assert "Lumen" in text and "**" not in text and "• one" in text


def test_sources_move_under_the_bubble():
    console = terminal()
    view = ChatView(console)
    with view:
        view.on_event("delta", {"text": "It is 419,000 SEK.\n\nSource: **voltrieve-buyers-guide.md**"})
    lines = output(console).splitlines()
    # The stream also holds earlier frames of the live region, so read the last occurrence.
    source = max(i for i, line in enumerate(lines) if "voltrieve-buyers-guide.md" in line)
    assert "│" not in lines[source] and lines[source - 1].lstrip().startswith("╰")


def test_split_sources_handles_a_sentence_inside_a_paragraph():
    text = "The figures are maximums. Sources: *Buyer's guide*, *Ragn brochure* and *Atlas specs*.\n\nWhich size?"
    body, sources = split_sources(text)
    assert sources == ["Buyer's guide", "Ragn brochure", "Atlas specs"]
    assert body == "The figures are maximums.\n\nWhich size?"


def test_a_source_in_brackets_moves_too():
    body, sources = split_sources("Its range is 530 km. (Source: Voltrieve Ragn specifications)\n\nWhich terrain?")
    assert sources == ["Voltrieve Ragn specifications"]
    assert body == "Its range is 530 km.\n\nWhich terrain?"


def test_a_title_holding_and_stays_whole():
    _, sources = split_sources("Source: Voltrieve spare parts catalog: suspension and steering")
    assert sources == ["Voltrieve spare parts catalog: suspension and steering"]


def test_a_source_in_the_middle_of_a_sentence_stays_there():
    text = "See it. (Source: guide) says more here."
    assert split_sources(text) == (text, [])


def test_a_short_answer_gets_a_small_bubble():
    console = terminal()
    view = ChatView(console)
    with view:
        view.on_event("delta", {"text": "Hi there"})
    last_top = [line for line in output(console).splitlines() if "╭" in line][-1]
    assert len(last_top.strip()) == len("Hi there") + 4


def test_an_answer_without_sources_is_left_alone():
    assert split_sources("No sources here.") == ("No sources here.", [])


def test_a_new_status_replaces_the_old_one_and_none_stays_behind():
    view = ChatView(terminal())
    with view:
        view.on_event("status", {"code": "a", "message": "Searching the documents"})
        view.on_event("status", {"code": "b", "message": "Reading the results"})
        assert view._status == "Reading the results"
        view.on_event("delta", {"text": "Done"})
        assert view._status is None
    assert view._status is None


def test_the_status_line_shows_a_running_timer():
    console = terminal()
    view = ChatView(console)
    view.on_event("status", {"code": "a", "message": "Thinking"})
    with console.capture() as capture:
        console.print(view.renderable())
    assert "Thinking · 0 s" in strip_ansi(capture.get())


def test_the_trace_stays_hidden_until_asked_for():
    console = terminal()
    view = ChatView(console)
    with view:
        view.on_event("turn_started", {"correlation_id": "abc-123"})
        view.on_event("trace", {"step": "model_called", "component": "model", "detail": "x", "elapsed_ms": 1})
    assert "model_called" not in output(console)
    view.print_trace()
    text = output(console)
    assert "model_called" in text and "abc-123" in text


def test_print_trace_only_holds_the_last_turn():
    view = ChatView(terminal())
    view.on_event("turn_started", {"correlation_id": "first"})
    view.on_event("turn_started", {"correlation_id": "second"})
    assert len(view.trace) == 1 and "second" in view.trace[0]


def test_a_long_answer_streams_its_tail_and_prints_in_full_at_the_end():
    console = terminal(height=12)
    view = ChatView(console)
    text = "\n\n".join(f"Line {n}" for n in range(40))
    view._answer = text
    with console.capture() as capture:
        console.print(view.renderable())
    live = strip_ansi(capture.get())
    assert "Line 39" in live and "Line 0\n" not in live and len(live.splitlines()) <= 12
    with view:
        view.on_event("delta", {"text": text})
    final = output(console)
    assert "Line 0 " in final and "Line 39" in final


def test_output_that_is_not_a_terminal_stays_plain():
    console = Console(file=io.StringIO(), force_terminal=False, width=80)
    view = ChatView(console)
    view.user("Hi")
    with view:
        view.on_event("status", {"code": "a", "message": "Thinking"})
        view.on_event("delta", {"text": "**Hello**"})
    text = console.file.getvalue()
    assert text == "you: Hi\nagent: **Hello**\n"


def test_model_text_cannot_inject_terminal_codes():
    console = terminal()
    view = ChatView(console)
    with view:
        view.on_event("delta", {"text": "safe\x1b]0;pwned\x07 text"})
    assert "\x1b]0;" not in console.file.getvalue()


def test_bubbles_leave_room_in_any_width():
    assert bubble_width(100) == 70
    assert bubble_width(50) == 46
    assert bubble_width(20) <= 20
