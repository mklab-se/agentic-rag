"""Run the search indexer and wait for the result."""

import time
from dataclasses import dataclass, field

from voltrieve_search.client import SearchApiError

FINISHED = {"success", "transientFailure", "persistentFailure"}


@dataclass
class IndexerRun:
    status: str
    items_processed: int
    items_failed: int
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


class IndexerFailed(Exception):
    def __init__(self, run: IndexerRun):
        super().__init__(
            f"indexer {run.status}: {run.items_failed} failed of {run.items_processed}; "
            + "; ".join(run.errors)
        )
        self.run = run


def _to_run(last: dict) -> IndexerRun:
    errors = [f"{e.get('key')}: {e.get('errorMessage')}" for e in last.get("errors") or []]
    warnings = [f"{w.get('key')}: {w.get('message')}" for w in last.get("warnings") or []]
    return IndexerRun(
        status=last["status"],
        items_processed=last.get("itemsProcessed", 0),
        items_failed=last.get("itemsFailed", 0),
        errors=errors,
        warnings=warnings,
    )


def run_and_wait(client, name: str, timeout_s: int = 600, poll_s: int = 10) -> IndexerRun:
    # A result is fresh when its start time differs from the one read before the run request,
    # which avoids comparing the local clock with the service clock.
    before = (client.get(f"/indexers/{name}/status").get("lastResult") or {}).get("startTime")
    try:
        client.post(f"/indexers/{name}/run")
    except SearchApiError as error:
        if error.status != 409:
            raise
        # Creating an indexer auto-runs it, so a run may already be in progress.
        # Whatever result appears is the one to wait for.
        before = None
    deadline = time.monotonic() + timeout_s
    while True:
        last = client.get(f"/indexers/{name}/status").get("lastResult")
        stale = last is not None and before is not None and last.get("startTime") == before
        if last and not stale and last.get("status") in FINISHED:
            run = _to_run(last)
            if run.status != "success" or run.items_failed > 0:
                raise IndexerFailed(run)
            return run
        if time.monotonic() >= deadline:
            raise IndexerFailed(IndexerRun("timeout", 0, 0, [f"no result within {timeout_s}s"]))
        time.sleep(poll_s)
