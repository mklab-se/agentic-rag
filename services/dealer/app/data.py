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


class UnknownArticle(ValueError):
    pass


@dataclass(frozen=True)
class PartStockRow:
    city: str
    in_stock: int
    distance_km: int | None  # from the city asked about; None for that city, or without a city


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
    def __init__(self, raw: dict, parts: dict | None = None):
        self._cities: list[str] = raw["cities"]
        self._stock: dict[str, dict[str, int]] = raw["stock"]
        self._prices: dict[str, dict[str, int]] = raw["prices"]
        self._currencies: dict[str, str] = raw["currencies"]
        parts = parts or {"stock": {}, "distances_km": {}}
        self._part_stock: dict[str, dict[str, int]] = parts["stock"]
        self._distances: dict[str, dict[str, int]] = parts["distances_km"]

    @classmethod
    def load(cls, path: Path, parts_path: Path | None = None) -> "DealerData":
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
        parts = json.loads(Path(parts_path).read_text(encoding="utf-8")) if parts_path else None
        return cls(raw, parts)

    @property
    def cities(self) -> list[str]:
        return list(self._cities)

    def part_stock(self, article: str, city: str | None) -> list[PartStockRow]:
        """Every city's stock of one article: the city asked about first, then the others by
        distance from it. Without a city, the cities with the most pieces come first."""
        if article not in self._part_stock:
            raise UnknownArticle(article)
        if city is not None and city not in self._cities:
            raise UnknownCity(city)
        by_city = self._part_stock[article]
        if city is None:
            order = sorted(self._cities, key=lambda c: -by_city[c])
            return [PartStockRow(c, by_city[c], None) for c in order]
        others = sorted((c for c in self._cities if c != city), key=lambda c: self._distances[city][c])
        return [PartStockRow(city, by_city[city], None)] + [
            PartStockRow(c, by_city[c], self._distances[city][c]) for c in others
        ]

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
