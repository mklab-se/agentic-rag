"""The sales folder as Markdown: one template per document, every number from the catalog.

Tables name the model in each row where a row could be read on its own, because search returns
chunks and a row has to make sense without the heading above it.
"""

import math
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, StrictUndefined

from voltrieve_data.formatting import fmt_int
from voltrieve_data.model import CarModel, Catalog
from voltrieve_data.parts import build_parts
from voltrieve_data.pilot import pilot_features

DOC_TYPES_PER_MODEL = ("brochure", "price_list", "specifications", "accessories")
BRAND_DOC_TYPES = ("warranty", "charging_guide", "buyers_guide")
FINANCING_TRIM = "Plus"  # the trim the worked financing example uses
PAGE_BREAK = "\n---\n"  # a thematic break; the PDF stylesheet starts a new page there
CATEGORIES = ("Charging", "Carrying and towing", "Wheels and tyres", "Protection and safety")
MARKET_NAMES = {"SE": "Sweden", "EU": "the EU"}
DRIVE_WORDS = {"RWD": "rear wheel drive", "AWD": "all wheel drive"}

_ENV = Environment(
    loader=FileSystemLoader(Path(__file__).parent / "templates"),
    undefined=StrictUndefined,
    trim_blocks=True,
    lstrip_blocks=True,
    keep_trailing_newline=True,
)
_ENV.filters["n"] = fmt_int
_ENV.filters["and_join"] = lambda items: (
    " and ".join(items) if len(items) < 3 else ", ".join(items[:-1]) + " and " + items[-1]
)
_ENV.filters["a"] = lambda word: ("an " if str(word)[0] in "aeiou8" else "a ") + str(word)
_ENV.tests["contains"] = lambda seq, item: item in seq


def image_ref(slug: str, shot: str) -> str:
    """Path of an image relative to data/design/images; the PDF step resolves it."""
    return f"{slug}/{shot}.png"


def short_name(model: CarModel) -> str:
    return model.name.removeprefix("Voltrieve ")


def onboard_charger_kw(model: CarModel) -> int:
    return 22 if model.platform == "V2" else 11


def charge_minutes_10_80(model: CarModel) -> int:
    """DC time from 10 to 80 %, with the charge power linear between the curve points."""
    minutes = 0.0
    for (soc1, kw1), (soc2, kw2) in zip(model.charging_curve, model.charging_curve[1:]):
        energy = model.battery_kwh * (soc2 - soc1) / 100
        mean = kw1 if kw1 == kw2 else (kw2 - kw1) / math.log(kw2 / kw1)
        minutes += 60 * energy / mean
    return round(minutes)


def ac_hours(model: CarModel) -> str:
    """Empty to full on AC at the onboard charger's rating, one decimal."""
    return f"{model.battery_kwh / onboard_charger_kw(model):.1f}"


def kwh_per_100km(model: CarModel) -> float:
    return round(model.battery_kwh / model.range_km * 100, 1)


def _money(value: float, currency: str) -> str:
    if currency == "SEK":
        return f"{fmt_int(round(value))} SEK"
    return f"{value:.2f} EUR" if value < 100 else f"{fmt_int(round(value))} EUR"


def _price_rows(catalog: Catalog, model: CarModel) -> list[dict]:
    return [
        {
            "label": f"{short_name(model)} {trim.name}",
            "drive": drive,
            "se": catalog.trim_price(model, trim.name, drive, "SE"),
            "eu": catalog.trim_price(model, trim.name, drive, "EU"),
        }
        for trim in model.trims
        for drive in model.drive
    ]


def _equipment(catalog: Catalog, model: CarModel) -> list[dict]:
    """Rows of the equipment matrix: each trim item, then each option pack."""
    wheels = {w.key: w for w in model.wheels}
    interiors = {i.key: i for i in model.interiors}
    rows = [
        {"item": "Wheels", "cells": [f"{wheels[t.wheel].inches} inch {wheels[t.wheel].name}" for t in model.trims]},
        {"item": "Interior", "cells": [interiors[t.interior].name for t in model.trims]},
    ]
    for level, trim in enumerate(model.trims):
        for item in trim.adds:
            rows.append({
                "item": item,
                "cells": ["Standard" if i >= level else "Not available" for i in range(3)],
            })
    for name in model.option_packs:
        pack = catalog.option_packs[name]
        optional = f"Optional, {fmt_int(pack.price['SE'])} SEK / {fmt_int(pack.price['EU'])} EUR"
        rows.append({
            "item": f"{name} pack: {pack.description}",
            "cells": ["Included" if name in t.includes_packs else optional for t in model.trims],
        })
    return rows


def _accessories(catalog: Catalog, model: CarModel) -> list[dict]:
    parts = build_parts(catalog)
    groups = []
    for category in CATEGORIES:
        rows = []
        for key in model.accessories:
            accessory = catalog.accessories[key]
            if accessory.category != category:
                continue
            article = accessory.article or next(
                p.article for p in parts
                if p.key == accessory.part and any(f.slug == model.slug for f in p.fits)
            )
            rows.append({"article": article, "a": accessory})
        if rows:
            groups.append({"name": category, "rows": rows})
    return groups


def _financing(catalog: Catalog, model: CarModel) -> list[dict]:
    drive = "RWD" if "RWD" in model.drive else "AWD"
    examples = []
    for market in catalog.markets:
        price = catalog.trim_price(model, FINANCING_TRIM, drive, market.code)
        examples.append({
            "market": MARKET_NAMES[market.code],
            "currency": market.currency,
            "trim": f"{short_name(model)} {FINANCING_TRIM} {drive}",
            "terms": catalog.financing[market.code],
            "x": catalog.financing_example(price, market.code),
        })
    return examples


def _context(catalog: Catalog, model: CarModel | None) -> dict:
    ctx = {
        "cat": catalog,
        "PAGE_BREAK": PAGE_BREAK.strip(),
        "short_name": short_name,
        "onboard_kw": onboard_charger_kw,
        "c1080": charge_minutes_10_80,
        "ac_hours": ac_hours,
        "kwh_100": kwh_per_100km,
        "money": _money,
        "pilot_features": pilot_features,
        "drive_words": lambda drives: " or ".join(DRIVE_WORDS[d] for d in drives),
        "markets": [(m.code, m.currency, MARKET_NAMES[m.code]) for m in catalog.markets],
    }
    if model is not None:
        best = max(model.performance.values(), key=lambda p: p.power_kw)
        ctx |= {
            "m": model,
            "short": short_name(model),
            "img": lambda shot: image_ref(model.slug, shot),
            "best": best,
            "hero": next(c for c in model.colors if c.hero),
            "wheel": {w.key: w for w in model.wheels},
            "interior": {i.key: i for i in model.interiors},
            "price_rows": _price_rows(catalog, model),
            "equipment": _equipment(catalog, model),
            "accessory_groups": _accessories(catalog, model),
            "financing": _financing(catalog, model),
        }
    return ctx


def render_markdown(doc_type: str, catalog: Catalog, model: CarModel | None) -> str:
    if doc_type in DOC_TYPES_PER_MODEL and model is None:
        raise ValueError(f"{doc_type} needs a model")
    if doc_type in BRAND_DOC_TYPES and model is not None:
        raise ValueError(f"{doc_type} is a brand document")
    if doc_type not in DOC_TYPES_PER_MODEL + BRAND_DOC_TYPES:
        raise ValueError(f"unknown document type {doc_type!r}")
    text = _ENV.get_template(f"{doc_type}.md.j2").render(_context(catalog, model))
    while "\n\n\n" in text:
        text = text.replace("\n\n\n", "\n\n")
    return text
