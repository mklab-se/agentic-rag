from pathlib import Path
from voltrieve_data.load import load_catalog

CATALOG = Path(__file__).parents[2] / "voltrieve.yaml"

def test_five_models_in_spec_order():
    cat = load_catalog(CATALOG)
    assert [m.slug for m in cat.models] == ["spark", "lumen", "ragn", "fjord", "atlas"]

def test_ragn_and_fjord_share_battery_but_differ_in_towing_and_range():
    cat = load_catalog(CATALOG)
    ragn, fjord = cat.by_slug("ragn"), cat.by_slug("fjord")
    assert ragn.battery_kwh == fjord.battery_kwh == 84
    assert fjord.towing_kg == 2100 and ragn.towing_kg == 1800
    assert fjord.range_km != ragn.range_km

def test_atlas_is_the_only_320kw_charger_and_largest_battery():
    cat = load_catalog(CATALOG)
    fastest = [m.slug for m in cat.models if m.peak_charge_kw == 320]
    assert fastest == ["atlas"]
    assert max(cat.models, key=lambda m: m.battery_kwh).slug == "atlas"

def test_spark_is_not_rated_for_towing_and_has_no_standard_heat_pump():
    spark = load_catalog(CATALOG).by_slug("spark")
    assert spark.towing_kg is None
    assert spark.heat_pump_standard is False

def test_every_model_has_a_price_in_every_market():
    cat = load_catalog(CATALOG)
    for m in cat.models:
        assert set(m.price) == {mk.code for mk in cat.markets}

def test_cheapest_awd_in_sweden_is_lumen():
    cat = load_catalog(CATALOG)
    awd = [m for m in cat.models if "AWD" in m.drive]
    assert min(awd, key=lambda m: cat.awd_price(m, "SE")).slug == "lumen"

def test_not_documented_terms_absent_from_catalog_text():
    cat = load_catalog(CATALOG)
    text = cat.all_text().lower()
    for term in cat.not_documented:
        assert term.lower() not in text
