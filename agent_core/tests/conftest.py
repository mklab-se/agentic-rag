import pytest

from voltrieve_agent.tools import UserContext


@pytest.fixture
def user():
    return UserContext("oid-1", "anna@example.com", frozenset())


@pytest.fixture
def events():
    collected = []

    async def emit(event):
        collected.append(event)

    emit.events = collected
    return emit
