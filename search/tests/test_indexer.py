import pytest

from voltrieve_search.client import SearchApiError
from voltrieve_search.indexer import IndexerFailed, run_and_wait


class Client:
    def __init__(self, statuses, post_error=None):
        self.statuses = list(statuses)
        self.posted = []
        self.post_error = post_error

    def post(self, path, body=None):
        self.posted.append(path)
        if self.post_error:
            raise self.post_error
        return 202, {}

    def get(self, path):
        return self.statuses.pop(0)


def status(s, failed=0, errors=(), start=None):
    last = {
        "status": s,
        "itemsProcessed": 11,
        "itemsFailed": failed,
        "errors": [{"key": k, "errorMessage": "unsupported"} for k in errors],
    }
    if start:
        last["startTime"] = start
    return {"lastResult": last}


def test_success_after_polling():
    c = Client([{"lastResult": None}, {"lastResult": None}, status("inProgress"), status("success")])
    run = run_and_wait(c, "voltrieve-docs-indexer", timeout_s=5, poll_s=0)
    assert run.status == "success" and c.posted == ["/indexers/voltrieve-docs-indexer/run"]


def test_per_document_failures_raise_with_keys():
    c = Client([{"lastResult": None}, status("success", failed=1, errors=["bad.xyz"])])
    with pytest.raises(IndexerFailed) as e:
        run_and_wait(c, "x", timeout_s=5, poll_s=0)
    assert "bad.xyz" in e.value.run.errors[0]


def test_409_on_run_is_tolerated_and_polling_continues():
    c = Client(
        [
            {"lastResult": None},
            status("inProgress", start="2000-01-01T00:00:00Z"),
            status("success", start="2000-01-01T00:00:00Z"),
        ],
        post_error=SearchApiError(409, "already running"),
    )
    assert run_and_wait(c, "x", timeout_s=5, poll_s=0).status == "success"


def test_other_run_errors_propagate():
    c = Client([{"lastResult": None}], post_error=SearchApiError(500, "boom"))
    with pytest.raises(SearchApiError):
        run_and_wait(c, "x", timeout_s=5, poll_s=0)


def test_stale_finished_result_is_ignored_until_fresh_one_appears():
    c = Client(
        [
            status("success", start="2000-01-01T00:00:00Z"),
            status("success", start="2000-01-01T00:00:00Z"),
            status("success", start="2000-01-01T00:00:00Z"),
            status("transientFailure", failed=2, start="2000-01-02T00:00:00Z"),
        ]
    )
    with pytest.raises(IndexerFailed) as e:
        run_and_wait(c, "x", timeout_s=5, poll_s=0)
    assert e.value.run.status == "transientFailure"
    assert c.statuses == []


def test_timeout_raises_with_timeout_status():
    c = Client([{"lastResult": None}] + [status("inProgress")] * 50)
    with pytest.raises(IndexerFailed) as e:
        run_and_wait(c, "x", timeout_s=0, poll_s=0)
    assert e.value.run.status == "timeout"


def test_warnings_are_reported_on_success():
    last = status("success", start="2000-01-02T00:00:00Z")
    last["lastResult"]["warnings"] = [{"key": "a.md", "message": "truncated"}]
    c = Client([status("success", start="2000-01-01T00:00:00Z"), last])
    run = run_and_wait(c, "x", timeout_s=5, poll_s=0)
    assert run.warnings == ["a.md: truncated"]
