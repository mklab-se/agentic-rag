import json
from pathlib import Path

from voltrieve_data.load import load_catalog

ROOT = Path(__file__).parents[3]


def test_dealer_price_list_matches_catalog():
    cat = load_catalog(ROOT / "data" / "voltrieve.yaml")
    dealer = json.loads((ROOT / "services" / "dealer" / "app" / "data.json").read_text())
    for m in cat.models:
        for market, price in m.price.items():
            assert dealer["prices"][market][m.slug] == price
