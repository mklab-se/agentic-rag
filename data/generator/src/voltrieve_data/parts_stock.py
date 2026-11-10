"""Parts stock per dealer city, generated from the parts, and the distances between dealers.

The dealer service reads the file this writes. Stock is a stable hash of the article and the
city, so the same parts give the same stock on every run; a few parts are pinned in the catalog.
"""

import hashlib
import json
from pathlib import Path

from voltrieve_data.model import Catalog
from voltrieve_data.parts import Part, build_parts

DEALER_DIR = Path(__file__).parents[4] / "services" / "dealer" / "app"
DEFAULT_PARTS_STOCK = DEALER_DIR / "parts-stock.json"
# A third of the values are 0, so some parts are out in one city, a few in all of them.
PIECES = (0, 0, 0, 0, 1, 1, 2, 2, 3, 4, 6, 9)


def dealer_cities() -> list[str]:
    return json.loads((DEALER_DIR / "data.json").read_text(encoding="utf-8"))["cities"]


def _pieces(article: str, city: str) -> int:
    digest = hashlib.sha256(f"{article}|{city}".encode()).digest()
    return PIECES[int.from_bytes(digest[:8], "big") % len(PIECES)]


def _distances(catalog: Catalog, cities: list[str]) -> dict[str, dict[str, int]]:
    both = {c: {} for c in cities}
    for a, to in catalog.dealer_distances_km.items():
        for b, km in to.items():
            both[a][b] = both[b][a] = km
    return {c: {o: both[c][o] for o in cities if o != c} for c in cities}


def build_parts_stock(catalog: Catalog, parts: list[Part], cities: list[str]) -> dict:
    stock = {p.article: {c: _pieces(p.article, c) for c in cities} for p in parts}
    for pin in catalog.parts_stock_pins:
        matches = [p for p in parts if p.key == pin.key and any(f.slug == pin.model for f in p.fits)]
        if len(matches) != 1:
            raise ValueError(f"stock pin {pin.key} for {pin.model}: {len(matches)} parts")
        stock[matches[0].article] = {c: pin.stock[c] for c in cities}
    return {"cities": cities, "distances_km": _distances(catalog, cities), "stock": stock}


def write_parts_stock(catalog: Catalog, path: Path = DEFAULT_PARTS_STOCK) -> Path:
    data = build_parts_stock(catalog, build_parts(catalog), dealer_cities())
    path.write_text(json.dumps(data, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    return path
