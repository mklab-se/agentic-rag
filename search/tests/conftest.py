import pytest


class FakeClient:
    def __init__(self):
        self.puts: list[tuple[str, dict]] = []

    def put(self, path: str, body: dict) -> dict:
        self.puts.append((path, body))
        return body


@pytest.fixture
def fake_client():
    return FakeClient()
