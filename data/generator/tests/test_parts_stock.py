import json
from pathlib import Path

import pytest

from voltrieve_data.load import load_catalog
from voltrieve_data.parts import build_parts
from voltrieve_data.parts_stock import DEFAULT_PARTS_STOCK, build_parts_stock, dealer_cities

ROOT = Path(__file__).parents[3]
CATALOG_PATH = ROOT / "data" / "voltrieve.yaml"
DISTANCES = {("Stockholm", "Uppsala"): 70, ("Stockholm", "Göteborg"): 470, ("Stockholm", "Malmö"): 615,
             ("Uppsala", "Göteborg"): 455, ("Uppsala", "Malmö"): 680, ("Göteborg", "Malmö"): 270}


@pytest.fixture(scope="module")
def catalog():
    return load_catalog(CATALOG_PATH)


@pytest.fixture(scope="module")
def parts(catalog):
    return build_parts(catalog)


@pytest.fixture(scope="module")
def stock(catalog, parts):
    return build_parts_stock(catalog, parts, dealer_cities())


def test_cities_are_the_dealers_cities(stock):
    data = json.loads((ROOT / "services" / "dealer" / "app" / "data.json").read_text(encoding="utf-8"))
    assert stock["cities"] == data["cities"]


def test_stock_covers_every_article_and_city(stock, parts):
    assert set(stock["stock"]) == {p.article for p in parts}
    assert all(set(by_city) == set(stock["cities"]) for by_city in stock["stock"].values())
    assert all(n >= 0 for by_city in stock["stock"].values() for n in by_city.values())


def test_stock_is_the_same_on_every_run(catalog, parts, stock):
    assert build_parts_stock(catalog, parts, dealer_cities()) == stock


def test_some_parts_are_out_everywhere(stock):
    assert sum(not any(c.values()) for c in stock["stock"].values()) >= 5


def test_some_parts_are_in_one_city_only(stock):
    assert sum(sum(n > 0 for n in c.values()) == 1 for c in stock["stock"].values()) >= 20


def test_most_parts_are_in_stock_somewhere(stock):
    counts = stock["stock"].values()
    assert sum(any(c.values()) for c in counts) >= 0.8 * len(counts)


def test_spark_right_mirror_is_pinned(stock, parts):
    mirror = next(p for p in parts if p.key == "door_mirror_right" and p.fits[0].slug == "spark")
    assert stock["stock"][mirror.article] == {"Stockholm": 0, "Göteborg": 1, "Malmö": 0, "Uppsala": 2}


def test_distances_are_symmetric_and_complete(stock):
    distances = stock["distances_km"]
    for (a, b), km in DISTANCES.items():
        assert distances[a][b] == km and distances[b][a] == km
    assert all(set(distances[c]) == set(stock["cities"]) - {c} for c in stock["cities"])


def test_committed_stock_file_is_current(stock):
    """Regenerate with `voltrieve-data generate` after any change to the parts."""
    assert json.loads(DEFAULT_PARTS_STOCK.read_text(encoding="utf-8")) == stock
