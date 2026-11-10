from typing import Literal

from pydantic import BaseModel, model_validator

TRIM_NAMES = ("Pure", "Plus", "Prime")


FINANCING_TRIM = "Plus"  # the trim the worked financing example uses


class Company(BaseModel):
    name: str
    tagline: str


class Market(BaseModel):
    code: str
    currency: str
    price_rounding: int  # trim prices are rounded to this many currency units


class Trim(BaseModel):
    name: Literal["Pure", "Plus", "Prime"]
    adds: list[str]
    includes_packs: list[str] = []
    wheel: str
    interior: str


class Color(BaseModel):
    key: str
    name: str
    finish: Literal["solid", "metallic", "pearl", "satin"]
    description: str
    hex: str  # swatch color in the price list
    hero: bool = False


class Wheel(BaseModel):
    key: str
    name: str
    inches: int
    description: str
    tyre_size: str  # such as 245/45 R20; tyres are sold per size


class Interior(BaseModel):
    key: str
    name: str
    description: str


class Dimensions(BaseModel):
    length_mm: int
    width_mm: int
    height_mm: int
    wheelbase_mm: int
    kerb_weight_kg: int
    boot_l: int
    boot_folded_l: int
    frunk_l: int | None
    ground_clearance_mm: int
    roof_load_kg: int


class Performance(BaseModel):
    power_kw: int
    torque_nm: int
    zero_to_100_s: float
    top_speed_kmh: int


class Copy(BaseModel):
    """Brochure text per model. Words only: every number comes from the fields."""

    intro: str
    design: str
    interior: str
    drive: str
    practical: str


class Electricity(BaseModel):
    home_per_kwh: float
    public_ac_per_kwh: float
    public_dc_per_kwh: float


class Accessory(BaseModel):
    """Sold by the dealer. Points at a spare part, or carries its own article number."""

    name: str
    category: Literal["Charging", "Carrying and towing", "Wheels and tyres", "Protection and safety"]
    description: str
    price: dict[str, int]
    part: str | None = None
    article: str | None = None


class Warranty(BaseModel):
    vehicle_years: int
    vehicle_km: int
    battery_years: int
    battery_km: int
    battery_min_capacity_percent: int
    paint_years: int
    corrosion_years: int
    roadside_years: int
    service_interval_months: int
    service_interval_km: int
    notes: list[str]


class ServicePlan(BaseModel):
    name: str
    years: int
    km: int
    includes: list[str]
    price_per_month: dict[str, int]


class FinancingTerms(BaseModel):
    nominal_rate: float
    deposit_share: float
    residual_share: float
    months: int
    setup_fee: int
    monthly_admin_fee: int


class FinancingExample(BaseModel):
    market: str
    price: int
    deposit: int
    loan: int
    residual: int
    months: int
    nominal_rate: float
    effective_rate: float
    setup_fee: int
    monthly_admin_fee: int
    monthly: int
    total_cost: int


class OptionPack(BaseModel):
    description: str
    price: dict[str, int]


class Brakes(BaseModel):
    front_disc_mm: dict[str, int]
    rear_disc_mm: int
    front_caliper: str
    rear_caliper: str


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
    brakes: Brakes
    trims: list[Trim]
    colors: list[Color]
    wheels: list[Wheel]
    interiors: list[Interior]
    dimensions: Dimensions
    accessories: list[str]
    company_car_benefit_sek: dict[str, int]  # fictional monthly example, Sweden only
    performance: dict[str, Performance]  # per drive
    accent: str  # document accent color, readable on white
    copy_text: Copy
    drive_selector: Literal["stalk", "rotary"]  # how the driver picks drive, reverse and park
    rear_quarter_glass: bool  # a fixed side window behind the rear doors

    @model_validator(mode="after")
    def _references_exist(self) -> "CarModel":
        if tuple(t.name for t in self.trims) != TRIM_NAMES:
            raise ValueError(f"{self.slug}: trims must be {TRIM_NAMES}")
        wheels = {w.key for w in self.wheels}
        interiors = {i.key for i in self.interiors}
        for trim in self.trims:
            if trim.wheel not in wheels:
                raise ValueError(f"{self.slug} {trim.name}: unknown wheel {trim.wheel!r}")
            if trim.interior not in interiors:
                raise ValueError(f"{self.slug} {trim.name}: unknown interior {trim.interior!r}")
            unknown = set(trim.includes_packs) - set(self.option_packs)
            if unknown:
                raise ValueError(f"{self.slug} {trim.name}: packs not offered {sorted(unknown)}")
        if sum(c.hero for c in self.colors) != 1:
            raise ValueError(f"{self.slug}: exactly one hero color")
        if set(self.performance) != set(self.drive):
            raise ValueError(f"{self.slug}: performance must cover every drive")
        return self


class StockPin(BaseModel):
    """Fixed parts stock for one part, so a demo question always has the same answer."""
    key: str
    model: str  # model slug
    stock: dict[str, int]  # city -> pieces


class Catalog(BaseModel):
    company: Company
    markets: list[Market]
    option_packs: dict[str, OptionPack]
    models: list[CarModel]
    awd_surcharge: dict[str, int]
    trim_steps: dict[str, float]  # share above the Pure price
    color_prices: dict[str, dict[str, int]]  # finish -> market -> price; the hero color is free
    accessories: dict[str, Accessory]
    warranty: Warranty
    service_plans: list[ServicePlan]
    financing: dict[str, FinancingTerms]
    electricity: dict[str, Electricity]  # example prices per market for the charging guide
    price_list_valid_from: str
    not_documented: list[str]
    dealer_distances_km: dict[str, dict[str, int]]  # road distance, each pair listed once
    parts_stock_pins: list[StockPin]

    @model_validator(mode="after")
    def _accessories_exist(self) -> "Catalog":
        for model in self.models:
            unknown = set(model.accessories) - set(self.accessories)
            if unknown:
                raise ValueError(f"{model.slug}: unknown accessories {sorted(unknown)}")
        return self

    def market(self, code: str) -> Market:
        return next(m for m in self.markets if m.code == code)

    def trim_price(self, model: CarModel, trim: str, drive: str, market: str) -> int:
        """Pure is the model's list price; Plus and Prime are steps above it, then AWD on top."""
        if drive not in model.drive:
            raise ValueError(f"{model.name} has no {drive}")
        step = self.market(market).price_rounding
        price = round(model.price[market] * (1 + self.trim_steps[trim]) / step) * step
        if drive == "AWD" and len(model.drive) > 1:
            price += self.awd_surcharge[market]
        return price

    def color_price(self, color: Color, market: str) -> int:
        return 0 if color.hero else self.color_prices[color.finish][market]

    def financing_car(self, model: CarModel) -> tuple[str, str]:
        """The trim and drive of the worked financing example: Plus, RWD where it is offered."""
        return FINANCING_TRIM, "RWD" if "RWD" in model.drive else "AWD"

    def financing_example(self, price: int, market: str) -> FinancingExample:
        """A loan with a deposit and a balloon (residual) payment at the end."""
        terms = self.financing[market]
        deposit = round(price * terms.deposit_share)
        residual = round(price * terms.residual_share)
        loan = price - deposit
        r, n = terms.nominal_rate / 12, terms.months
        annuity = (loan - residual / (1 + r) ** n) * r / (1 - (1 + r) ** -n)
        monthly = round(annuity + terms.monthly_admin_fee)
        return FinancingExample(
            market=market, price=price, deposit=deposit, loan=loan, residual=residual,
            months=n, nominal_rate=terms.nominal_rate,
            effective_rate=_effective_rate(loan - terms.setup_fee, monthly, residual, n),
            setup_fee=terms.setup_fee, monthly_admin_fee=terms.monthly_admin_fee,
            monthly=monthly, total_cost=deposit + monthly * n + residual + terms.setup_fee,
        )

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


def _effective_rate(received: float, monthly: int, residual: int, months: int) -> float:
    """Yearly rate at which the payments are worth what the buyer received (bisection)."""

    def value(i: float) -> float:
        return sum(monthly / (1 + i) ** k for k in range(1, months + 1)) + residual / (1 + i) ** months

    low, high = 0.0, 0.05
    for _ in range(100):
        mid = (low + high) / 2
        low, high = (mid, high) if value(mid) > received else (low, mid)
    return (1 + low) ** 12 - 1
