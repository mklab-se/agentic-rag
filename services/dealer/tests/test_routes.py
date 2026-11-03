import datetime as dt

from httpx import ASGITransport, AsyncClient

from app.auth import TokenValidator
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
    date = (dt.date.today() + dt.timedelta(days=3)).isoformat()
    async with client(settings, validator) as c:
        r = await c.post(
            "/test-drives",
            json={"model": "atlas", "city": "Göteborg", "date": date, "requester": "oid-1"},
            headers=auth_header,
        )
    assert r.status_code == 201 and r.json()["booking_id"]


async def test_booking_validation(settings, validator, auth_header):
    past = (dt.date.today() - dt.timedelta(days=1)).isoformat()
    future = (dt.date.today() + dt.timedelta(days=1)).isoformat()
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
