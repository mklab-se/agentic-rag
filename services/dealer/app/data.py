import datetime as dt
import json
import uuid
from dataclasses import dataclass
from pathlib import Path
from zoneinfo import ZoneInfo

DEALER_TIMEZONE = ZoneInfo("Europe/Stockholm")


def today() -> dt.date:
    """Today at the dealer, whatever the timezone of the host (containers run in UTC)."""
    return dt.datetime.now(DEALER_TIMEZONE).date()


class UnknownModel(ValueError):
    pass


class UnknownCity(ValueError):
    pass


class UnknownMarket(ValueError):
    pass


class DateNotInFuture(ValueError):
    pass


@dataclass(frozen=True)
class StockRow:
    model: str
    city: str
    in_stock: int


@dataclass(frozen=True)
class PriceList:
    market: str
    currency: str
    prices: list[dict]


@dataclass(frozen=True)
class Booking:
    booking_id: str
    model: str
    city: str
    date: dt.date
    requester: str


class DealerData:
    def __init__(self, raw: dict):
        self._cities: list[str] = raw["cities"]
        self._stock: dict[str, dict[str, int]] = raw["stock"]
        self._prices: dict[str, dict[str, int]] = raw["prices"]
        self._currencies: dict[str, str] = raw["currencies"]

    @classmethod
    def load(cls, path: Path) -> "DealerData":
        return cls(json.loads(Path(path).read_text(encoding="utf-8")))

    def _check(self, model: str | None, city: str | None) -> None:
        if model is not None and model not in self._stock:
            raise UnknownModel(model)
        if city is not None and city not in self._cities:
            raise UnknownCity(city)

    def stock(self, model: str | None, city: str | None) -> list[StockRow]:
        self._check(model, city)
        return [
            StockRow(m, c, n)
            for m, by_city in self._stock.items()
            if model is None or m == model
            for c, n in by_city.items()
            if city is None or c == city
        ]

    def prices(self, market: str) -> PriceList:
        if market not in self._prices:
            raise UnknownMarket(market)
        return PriceList(
            market,
            self._currencies[market],
            [{"model": m, "list_price": p} for m, p in self._prices[market].items()],
        )

    def book(self, model: str, city: str, date: dt.date, requester: str) -> Booking:
        self._check(model, city)
        if date <= today():
            raise DateNotInFuture(date.isoformat())
        return Booking(str(uuid.uuid4()), model, city, date, requester)
