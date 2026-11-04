import contextvars
import json
import logging
import sys

correlation_id: contextvars.ContextVar[str] = contextvars.ContextVar("correlation_id", default="-")
# Per-request fields that appear in every log line once known.
log_context: contextvars.ContextVar[dict] = contextvars.ContextVar("log_context", default={})

_EXTRA = ("path", "status", "elapsed_ms", "step", "component", "detail")
_CONTEXT_KEYS = ("conversation_id", "turn_id", "backend", "user_oid")


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        entry = {
            "time": self.formatTime(record, "%Y-%m-%dT%H:%M:%S%z"),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "correlation_id": correlation_id.get(),
        }
        context = log_context.get()
        for key in _CONTEXT_KEYS:
            entry[key] = context.get(key)
        for key in _EXTRA:
            if hasattr(record, key):
                entry[key] = getattr(record, key)
        if record.exc_info:
            entry["exception"] = self.formatException(record.exc_info)
        return json.dumps(entry, ensure_ascii=False)


def bind_log_context(**values: str) -> None:
    """Add fields to this task's log context (copy on write, so tasks never share a dict)."""
    log_context.set({**log_context.get(), **values})


def configure_logging(level: str) -> None:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    root = logging.getLogger()
    root.handlers[:] = [handler]
    root.setLevel(level.upper())
    # The Azure SDK logs every HTTP request and response header at INFO.
    logging.getLogger("azure").setLevel(logging.WARNING)
