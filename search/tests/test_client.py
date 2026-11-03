import httpx
import pytest
import respx

from voltrieve_search.client import SearchApiError, SearchRestClient


@respx.mock
def test_put_sends_bearer_and_api_version():
    route = respx.put("https://s.search.windows.net/indexes/i?api-version=2026-04-01").mock(
        return_value=httpx.Response(201, json={"name": "i"})
    )
    c = SearchRestClient("https://s.search.windows.net", lambda: "tok")
    assert c.put("/indexes/i", {"name": "i"}) == {"name": "i"}
    assert route.calls.last.request.headers["Authorization"] == "Bearer tok"
    assert route.calls.last.request.headers["Prefer"] == "return=representation"


@respx.mock
def test_error_raises_with_message():
    respx.put("https://s.search.windows.net/indexes/i?api-version=2026-04-01").mock(
        return_value=httpx.Response(400, json={"error": {"message": "bad field"}})
    )
    c = SearchRestClient("https://s.search.windows.net", lambda: "tok")
    with pytest.raises(SearchApiError) as e:
        c.put("/indexes/i", {})
    assert "bad field" in str(e.value)
    assert e.value.status == 400


@respx.mock
def test_post_returns_status_and_body_and_get_returns_body():
    respx.post("https://s.search.windows.net/indexers/x/run?api-version=2026-04-01").mock(
        return_value=httpx.Response(409, json={"error": {"message": "busy"}})
    )
    respx.post("https://s.search.windows.net/indexers/y/run?api-version=2026-04-01").mock(
        return_value=httpx.Response(202)
    )
    respx.get("https://s.search.windows.net/indexers/y/status?api-version=2026-04-01").mock(
        return_value=httpx.Response(200, json={"status": "running"})
    )
    c = SearchRestClient("https://s.search.windows.net", lambda: "tok")
    assert c.post("/indexers/y/run") == (202, {})
    assert c.get("/indexers/y/status") == {"status": "running"}
    with pytest.raises(SearchApiError) as e:
        c.post("/indexers/x/run")
    assert e.value.status == 409


def test_cli_search_api_error_exits_1_with_status(monkeypatch, capsys):
    import voltrieve_search.cli as cli

    def boom(args):
        raise cli.SearchApiError(403, "forbidden")

    monkeypatch.setitem(cli.SUBCOMMANDS, "index", (boom, "x"))
    assert cli.main(["index"]) == 1
    assert "403" in capsys.readouterr().err
