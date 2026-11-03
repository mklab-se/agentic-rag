import json
import logging

from app.logging_setup import JsonFormatter, bind_log_context, correlation_id, log_context


def test_json_log_has_correlation_fields_and_no_token():
    token = correlation_id.set("cid-1")
    ctx_token = log_context.set({})
    try:
        bind_log_context(conversation_id="c", turn_id="t", backend="loop", user_oid="o")
        record = logging.LogRecord("x", logging.INFO, "f", 1, "hello", None, None)
        entry = json.loads(JsonFormatter().format(record))
    finally:
        correlation_id.reset(token)
        log_context.reset(ctx_token)
    assert entry["correlation_id"] == "cid-1"
    assert {k: entry[k] for k in ("conversation_id", "turn_id", "backend", "user_oid")} == {
        "conversation_id": "c", "turn_id": "t", "backend": "loop", "user_oid": "o"
    }
