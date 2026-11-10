import datetime as dt

from httpx import ASGITransport, AsyncClient

from app.auth import TokenValidator
from app.data import today
from app.main import create_app


def client(settings, validator):
    return AsyncClient(
        transport=ASGITransport(app=create_app(settings, validator)), base_url="http://t"
    )


async def test_healthz_is_open(settings, validator):
    async with client(settings, validator) as c:
        assert (await c.get("/healthz")).status_code == 200


async def test_stock_requires_token(settings, validator):
    async with client(settings, validator) as c:
        assert (await c.get("/stock")).status_code == 401


async def test_header_without_bearer_scheme_is_rejected(settings, validator, make_token):
    async with client(settings, validator) as c:
        r = await c.get("/stock", headers={"Authorization": make_token()})
    assert r.status_code == 401


async def test_stock_for_atlas_in_goteborg(settings, validator, auth_header):
    async with client(settings, validator) as c:
        r = await c.get("/stock", params={"model": "atlas", "city": "Göteborg"}, headers=auth_header)
    assert r.status_code == 200 and r.json()["rows"][0]["in_stock"] == 3


async def test_prices_in_eur(settings, validator, auth_header):
    async with client(settings, validator) as c:
        r = await c.get("/prices", params={"market": "EU"}, headers=auth_header)
    body = r.json()
    assert body["currency"] == "EUR"
    assert {"model": "atlas", "list_price": 67900} in body["prices"]


async def test_book_test_drive(settings, validator, auth_header):
    date = (today() + dt.timedelta(days=3)).isoformat()
    async with client(settings, validator) as c:
        r = await c.post(
            "/test-drives",
            json={"model": "atlas", "city": "Göteborg", "date": date, "requester": "oid-1"},
            headers=auth_header,
        )
    assert r.status_code == 201 and r.json()["booking_id"]


async def test_booking_validation(settings, validator, auth_header):
    past = (today() - dt.timedelta(days=1)).isoformat()
    future = (today() + dt.timedelta(days=1)).isoformat()
    async with client(settings, validator) as c:
        for body in [
            {"model": "atlas", "city": "Göteborg", "date": past, "requester": "x"},
            {"model": "tesla", "city": "Göteborg", "date": future, "requester": "x"},
            {"model": "atlas", "city": "Oslo", "date": future, "requester": "x"},
        ]:
            r = await c.post("/test-drives", json=body, headers=auth_header)
            assert r.status_code == 422, body


async def test_correlation_id_echoed(settings, validator, auth_header):
    async with client(settings, validator) as c:
        r = await c.get("/stock", headers={**auth_header, "X-Correlation-Id": "abc-123"})
    assert r.headers["X-Correlation-Id"] == "abc-123"


async def test_unsafe_correlation_id_is_replaced(settings, validator, auth_header):
    async with client(settings, validator) as c:
        r = await c.get("/stock", headers={**auth_header, "X-Correlation-Id": "bad id with spaces"})
        too_long = await c.get("/stock", headers={**auth_header, "X-Correlation-Id": "a" * 65})
        docs = await c.get("/docs")
    assert r.headers["X-Correlation-Id"] != "bad id with spaces"
    assert len(too_long.headers["X-Correlation-Id"]) == 36
    assert docs.status_code == 404


async def test_invalid_token_is_rejected_and_missing_role_is_forbidden(
    settings, validator, make_token
):
    async with client(settings, validator) as c:
        bad = await c.get("/stock", headers={"Authorization": "Bearer not-a-jwt"})
        no_role = await c.get(
            "/stock", headers={"Authorization": f"Bearer {make_token(roles=['Other'])}"}
        )
    assert bad.status_code == 401
    assert no_role.status_code == 403


async def test_jwks_failure_is_passed_through_as_503(settings, tenant_id, client_id, make_token):
    def broken():
        raise RuntimeError("no network")

    broken_validator = TokenValidator(tenant_id, client_id, "Dealer.Access", jwks_fetcher=broken)
    async with client(settings, broken_validator) as c:
        r = await c.get("/stock", headers={"Authorization": f"Bearer {make_token()}"})
    assert r.status_code == 503


def test_today_is_the_dealers_date_not_the_hosts():
    import datetime as dt

    from app.data import DEALER_TIMEZONE

    assert today() == dt.datetime.now(DEALER_TIMEZONE).date()


def _parts_stock():
    import json
    from pathlib import Path

    return json.loads((Path(__file__).parents[1] / "app" / "parts-stock.json").read_text(encoding="utf-8"))


def _article_out_in(city: str) -> str:
    """An article that is out of stock in the city and in stock somewhere else."""
    stock = _parts_stock()["stock"]
    return next(a for a, by in stock.items() if by[city] == 0 and any(by.values()))


async def test_part_stock_with_city_orders_by_distance(settings, validator, auth_header):
    data = _parts_stock()
    article = _article_out_in("Stockholm")
    async with client(settings, validator) as c:
        r = await c.get("/parts/stock", params={"article": article, "city": "Stockholm"}, headers=auth_header)
    assert r.status_code == 200
    body = r.json()
    assert body["article"] == article
    cities = [row["city"] for row in body["rows"]]
    assert cities == ["Stockholm", "Uppsala", "Göteborg", "Malmö"]
    assert body["rows"][0] == {"city": "Stockholm", "in_stock": 0, "distance_km": None}
    for row in body["rows"][1:]:
        assert row["distance_km"] == data["distances_km"]["Stockholm"][row["city"]]
        assert row["in_stock"] == data["stock"][article][row["city"]]


async def test_part_stock_without_city_has_no_distances(settings, validator, auth_header):
    article = _article_out_in("Malmö")
    async with client(settings, validator) as c:
        r = await c.get("/parts/stock", params={"article": article}, headers=auth_header)
    rows = r.json()["rows"]
    assert all(row["distance_km"] is None for row in rows)
    counts = [row["in_stock"] for row in rows]
    assert counts == sorted(counts, reverse=True)


async def test_part_stock_unknown_article_is_404(settings, validator, auth_header):
    async with client(settings, validator) as c:
        r = await c.get("/parts/stock", params={"article": "VP-00001"}, headers=auth_header)
    assert r.status_code == 404
    assert "not a Voltrieve article number" in r.json()["detail"]


async def test_part_stock_unknown_city_is_422_and_names_cities(settings, validator, auth_header):
    article = _article_out_in("Stockholm")
    async with client(settings, validator) as c:
        r = await c.get("/parts/stock", params={"article": article, "city": "Gothenburg"}, headers=auth_header)
    assert r.status_code == 422
    assert all(city in r.json()["detail"] for city in ("Stockholm", "Göteborg", "Malmö", "Uppsala"))


async def test_part_stock_needs_auth(settings, validator):
    async with client(settings, validator) as c:
        assert (await c.get("/parts/stock", params={"article": "VP-10007"})).status_code == 401
