from typing import Literal

from pydantic import BaseModel


class Company(BaseModel):
    name: str
    tagline: str


class Market(BaseModel):
    code: str
    currency: str


class OptionPack(BaseModel):
    description: str
    price: dict[str, int]


class CarModel(BaseModel):
    name: str
    slug: str
    segment: str
    platform: Literal["V1", "V2"]
    voltage: int
    battery_kwh: int
    range_km: int
    peak_charge_kw: int
    towing_kg: int | None
    drive: list[str]
    heat_pump_standard: bool
    pilot_version: int
    option_packs: list[str]
    price: dict[str, int]
    charging_curve: list[tuple[int, int]]
    tagline: str
    highlights: list[str]


class Catalog(BaseModel):
    company: Company
    markets: list[Market]
    option_packs: dict[str, OptionPack]
    models: list[CarModel]
    awd_surcharge: dict[str, int]
    not_documented: list[str]

    def by_slug(self, slug: str) -> CarModel:
        for model in self.models:
            if model.slug == slug:
                return model
        raise KeyError(slug)

    def awd_price(self, model: CarModel, market: str) -> int:
        """Price with AWD: base plus surcharge when AWD is optional, base when AWD is the only drive."""
        if "AWD" in model.drive and len(model.drive) > 1:
            return model.price[market] + self.awd_surcharge[market]
        return model.price[market]

    def all_text(self) -> str:
        """Every string field joined, excluding the not_documented list itself."""
        parts: list[str] = []

        def walk(value: object) -> None:
            if isinstance(value, str):
                parts.append(value)
            elif isinstance(value, dict):
                for key, item in value.items():
                    if isinstance(key, str):
                        parts.append(key)
                    walk(item)
            elif isinstance(value, (list, tuple)):
                for item in value:
                    walk(item)

        walk(self.model_dump(exclude={"not_documented"}))
        return "\n".join(parts)
