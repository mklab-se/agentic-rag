"""A used-up search allowance is reported as such, not as a generic tool failure."""

import pytest
from voltrieve_search.client import SearchApiError

from voltrieve_agent.knowledge import QUOTA_MESSAGE, KnowledgeBase
from voltrieve_agent.tools import current_emit


class Credential:
    def get_token(self, scope):
        raise AssertionError("not used")


def base(monkeypatch, status):
    def refuse(*args, **kwargs):
        raise SearchApiError(status, "refused")

    monkeypatch.setattr("voltrieve_agent.knowledge.retrieve", refuse)
    return KnowledgeBase("https://search", Credential())


@pytest.mark.asyncio
async def test_a_used_up_allowance_tells_the_model_what_happened(monkeypatch):
    events = []

    async def emit(event):
        events.append(event)

    token = current_emit.set(emit)
    try:
        output = await base(monkeypatch, 402).search("brakes")
    finally:
        current_emit.reset(token)
    assert output == QUOTA_MESSAGE
    assert [e.data["step"] for e in events] == ["search_quota_exhausted"]


@pytest.mark.asyncio
async def test_other_search_errors_still_raise(monkeypatch):
    with pytest.raises(SearchApiError):
        await base(monkeypatch, 500).search("brakes")
