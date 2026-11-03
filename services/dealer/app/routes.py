import datetime as dt
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, field_validator

from app.auth import AuthError, Claims
from app.data import DealerData

DATA_PATH = Path(__file__).parent / "data.json"


async def current_claims(request: Request) -> Claims:
    header = request.headers.get("Authorization", "")
    scheme, _, token = header.partition(" ")
    if scheme.lower() != "bearer" or not token.strip():
        raise HTTPException(401, "Missing bearer token")
    try:
        return await request.app.state.validator.validate(header)
    except AuthError as exc:
        raise HTTPException(exc.status_code, exc.detail) from exc


class TestDriveRequest(BaseModel):
    __test__ = False

    model: str
    city: str
    date: dt.date
    requester: str

    @field_validator("date")
    @classmethod
    def date_in_future(cls, value: dt.date) -> dt.date:
        if value <= dt.date.today():
            raise ValueError("date must be in the future")
        return value


def build_router(data: DealerData) -> APIRouter:
    router = APIRouter()

    @router.get("/healthz")
    def healthz() -> dict:
        return {"status": "ok"}

    protected = APIRouter(dependencies=[Depends(current_claims)])

    @protected.get("/stock")
    def stock(model: str | None = None, city: str | None = None) -> dict:
        try:
            rows = data.stock(model, city)
        except ValueError as exc:
            raise HTTPException(422, f"Unknown value: {exc}") from exc
        return {"rows": [r.__dict__ for r in rows]}

    @protected.get("/prices")
    def prices(market: Literal["SE", "EU"] = "SE") -> dict:
        p = data.prices(market)
        return {"market": p.market, "currency": p.currency, "prices": p.prices}

    @protected.post("/test-drives", status_code=201)
    def book(body: TestDriveRequest) -> dict:
        try:
            b = data.book(body.model, body.city, body.date, body.requester)
        except ValueError as exc:
            raise HTTPException(422, f"Invalid booking: {exc}") from exc
        return {
            "booking_id": b.booking_id,
            "model": b.model,
            "city": b.city,
            "date": b.date.isoformat(),
            "requester": b.requester,
        }

    router.include_router(protected)
    return router
