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


# Trims, colors, wheels, financing and warranty (plan 3, task 3)

import pytest
import yaml
from pydantic import ValidationError

from voltrieve_data.model import Catalog
from voltrieve_data.parts import build_parts

cat = load_catalog(CATALOG)


def cheapest_drive(model):
    return "RWD" if "RWD" in model.drive else "AWD"


def test_three_trims_per_model():
    for m in cat.models:
        assert [t.name for t in m.trims] == ["Pure", "Plus", "Prime"]


def test_pure_price_is_todays_price():
    for m in cat.models:
        for market in m.price:
            assert cat.trim_price(m, "Pure", cheapest_drive(m), market) == m.price[market]


def test_trim_steps():
    f = cat.by_slug("fjord")
    assert cat.trim_price(f, "Plus", "RWD", "SE") == 571000
    assert cat.trim_price(f, "Prime", "RWD", "SE") == 614000


def test_awd_surcharge_applies_per_trim():
    f = cat.by_slug("fjord")
    assert cat.trim_price(f, "Plus", "AWD", "SE") == 611000
    assert cat.trim_price(f, "Plus", "AWD", "EU") == 55300


def test_awd_only_models_have_no_surcharge():
    ragn = cat.by_slug("ragn")
    assert cat.trim_price(ragn, "Pure", "AWD", "SE") == ragn.price["SE"]


def test_drive_the_model_lacks_is_rejected():
    with pytest.raises(ValueError):
        cat.trim_price(cat.by_slug("spark"), "Pure", "AWD", "SE")


def test_color_prices():
    def color(slug, key):
        return next(c for c in cat.by_slug(slug).colors if c.key == key)

    assert cat.color_price(color("fjord", "glacier_blue"), "SE") == 0
    assert cat.color_price(color("spark", "graphite"), "SE") == 0
    assert cat.color_price(color("fjord", "heath"), "SE") == 9900
    assert cat.color_price(color("ragn", "granite"), "SE") == 14900
    assert cat.color_price(color("lumen", "pearl"), "EU") == 900


def test_four_colors_and_one_hero_per_model():
    for m in cat.models:
        assert len(m.colors) == 4
        assert sum(c.hero for c in m.colors) == 1


def test_hero_colors_match_the_design():
    heroes = {m.slug: next(c.name for c in m.colors if c.hero) for m in cat.models}
    assert heroes == {
        "spark": "Saffron", "lumen": "Coral", "ragn": "Moss", "fjord": "Glacier Blue",
        "atlas": "Glacier White",
    }


def test_every_reference_exists():
    for m in cat.models:
        wheels = {w.key for w in m.wheels}
        interiors = {i.key for i in m.interiors}
        for t in m.trims:
            assert t.wheel in wheels and t.interior in interiors
            assert set(t.includes_packs) <= set(m.option_packs)
        assert set(m.accessories) <= set(cat.accessories)


def test_wheels_per_trim_match_the_design():
    wheel = {m.slug: {t.name: next(w for w in m.wheels if w.key == t.wheel) for t in m.trims}
             for m in cat.models}
    assert (wheel["fjord"]["Pure"].name, wheel["fjord"]["Pure"].inches) == ("Birch", 19)
    assert (wheel["fjord"]["Plus"].name, wheel["fjord"]["Plus"].inches) == ("Fern", 20)
    assert (wheel["lumen"]["Prime"].name, wheel["lumen"]["Prime"].inches) == ("Turbine", 19)
    assert wheel["atlas"]["Prime"].inches == 22 and wheel["ragn"]["Prime"].inches == 20


def raw_catalog():
    return yaml.safe_load(CATALOG.read_text(encoding="utf-8"))


def test_unknown_wheel_key_fails_loading():
    data = raw_catalog()
    data["models"][0]["trims"][0]["wheel"] = "no_such_wheel"
    with pytest.raises(ValidationError):
        Catalog.model_validate(data)


def test_unknown_pack_fails_loading():
    data = raw_catalog()
    data["models"][0]["trims"][2]["includes_packs"] = ["Tow"]  # the Spark has no Tow pack
    with pytest.raises(ValidationError):
        Catalog.model_validate(data)


def test_heat_pump_consistent():
    for m in cat.models:
        pure = m.trims[0]
        listed = any("heat pump" in item.lower() for item in pure.adds)
        if not m.heat_pump_standard:
            assert not listed and "Winter" not in pure.includes_packs


def test_premium_trims_include_packs_the_model_offers():
    for m in cat.models:
        prime = m.trims[2]
        assert "Sound" in prime.includes_packs
        if "Pilot Plus" in m.option_packs:
            assert "Pilot Plus" in prime.includes_packs


def test_dimensions_agree_with_highlights():
    assert cat.by_slug("fjord").dimensions.boot_l == 640
    assert cat.by_slug("lumen").dimensions.frunk_l == 45
    assert cat.by_slug("ragn").dimensions.ground_clearance_mm == 205
    lengths = [m.dimensions.length_mm for m in cat.models]
    assert lengths == sorted(lengths)


def test_company_car_benefit_per_trim():
    for m in cat.models:
        assert set(m.company_car_benefit_sek) == {"Pure", "Plus", "Prime"}


def test_accessories_resolve_to_article_numbers():
    parts = {p.key for p in build_parts(cat)}
    for key, accessory in cat.accessories.items():
        assert (accessory.part is None) != (accessory.article is None), key
        if accessory.part:
            assert accessory.part in parts, key


def test_financing_example_math():
    example = cat.financing_example(500000, "SE")
    assert example.deposit == 100000 and example.residual == 250000
    assert example.monthly == 5583
    assert example.total_cost == 551683
    assert round(example.effective_rate * 100, 2) == 5.37


def test_warranty_no_longer_undocumented():
    assert "warranty" not in cat.not_documented and "Euro NCAP" in cat.not_documented
    assert cat.warranty.battery_years == 8


def test_accessory_parts_fit_the_models_that_list_them():
    parts = build_parts(cat)
    for m in cat.models:
        for key in m.accessories:
            part = cat.accessories[key].part
            if part:
                assert any(p.key == part and any(f.slug == m.slug for f in p.fits) for p in parts), (
                    m.slug, key)
