"""Run the search indexer and wait for the result."""

import time
from dataclasses import dataclass, field
from datetime import UTC, datetime

from voltrieve_search.client import SearchApiError

FINISHED = {"success", "transientFailure", "persistentFailure"}


@dataclass
class IndexerRun:
    status: str
    items_processed: int
    items_failed: int
    errors: list[str] = field(default_factory=list)


class IndexerFailed(Exception):
    def __init__(self, run: IndexerRun):
        super().__init__(
            f"indexer {run.status}: {run.items_failed} failed of {run.items_processed}; "
            + "; ".join(run.errors)
        )
        self.run = run


def _started_before(last: dict, cutoff: datetime) -> bool:
    start = last.get("startTime")
    if not start:
        return False
    try:
        parsed = datetime.fromisoformat(start)
    except ValueError:
        return False
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed < cutoff


def _to_run(last: dict) -> IndexerRun:
    errors = [f"{e.get('key')}: {e.get('errorMessage')}" for e in last.get("errors") or []]
    return IndexerRun(
        status=last["status"],
        items_processed=last.get("itemsProcessed", 0),
        items_failed=last.get("itemsFailed", 0),
        errors=errors,
    )


def run_and_wait(client, name: str, timeout_s: int = 600, poll_s: int = 10) -> IndexerRun:
    requested_at: datetime | None = datetime.now(UTC)
    try:
        client.post(f"/indexers/{name}/run")
    except SearchApiError as error:
        if error.status != 409:
            raise
        # Creating an indexer auto-runs it, so a run may already be in progress.
        # Its start time predates this request, so do not treat it as stale.
        requested_at = None
    deadline = time.monotonic() + timeout_s
    while True:
        last = client.get(f"/indexers/{name}/status").get("lastResult")
        stale = last is not None and requested_at is not None and _started_before(last, requested_at)
        if last and not stale and last.get("status") in FINISHED:
            run = _to_run(last)
            if run.status != "success" or run.items_failed > 0:
                raise IndexerFailed(run)
            return run
        if time.monotonic() >= deadline:
            raise IndexerFailed(IndexerRun("timeout", 0, 0, [f"no result within {timeout_s}s"]))
        time.sleep(poll_s)
