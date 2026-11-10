from pathlib import Path

from voltrieve_data.formatting import fmt_int
from voltrieve_data.load import load_catalog
from voltrieve_data.parts import build_parts
from voltrieve_data.sales.render import (
    BRAND_DOC_TYPES,
    DOC_TYPES_PER_MODEL,
    FINANCING_TRIM,
    PAGE_BREAK,
    charge_minutes_10_80,
    image_ref,
    render_markdown,
    short_name,
)

CATALOG = Path(__file__).parents[2] / "voltrieve.yaml"
EM_DASH = chr(0x2014)
cat = load_catalog(CATALOG)
fjord = cat.by_slug("fjord")


def all_documents():
    for model in cat.models:
        for doc_type in DOC_TYPES_PER_MODEL:
            yield doc_type, model.slug, render_markdown(doc_type, cat, model)
    for doc_type in BRAND_DOC_TYPES:
        yield doc_type, "brand", render_markdown(doc_type, cat, None)


def cheapest_drive(model):
    return "RWD" if "RWD" in model.drive else "AWD"


def test_price_list_has_every_trim_and_drive_row():
    assert "| Fjord Plus | AWD | 611 000 SEK | 55 300 EUR |" in render_markdown("price_list", cat, fjord)
    for m in cat.models:
        text = render_markdown("price_list", cat, m)
        for trim in m.trims:
            for drive in m.drive:
                se = fmt_int(cat.trim_price(m, trim.name, drive, "SE"))
                eu = fmt_int(cat.trim_price(m, trim.name, drive, "EU"))
                assert f"| {short_name(m)} {trim.name} | {drive} | {se} SEK | {eu} EUR |" in text


def test_price_list_has_colors_wheels_packs_financing():
    text = render_markdown("price_list", cat, fjord)
    lines = text.splitlines()
    for color in fjord.colors:
        price = cat.color_price(color, "SE")
        shown = "Included" if price == 0 else f"{fmt_int(price)} SEK"
        assert any(color.name in line and shown in line for line in lines), color.name
    for pack in fjord.option_packs:
        assert any(pack in line and fmt_int(cat.option_packs[pack].price["SE"]) in line for line in lines)
    for wheel in fjord.wheels:
        assert f"{wheel.inches} inch {wheel.name}" in text
    for market, currency in (("SE", "SEK"), ("EU", "EUR")):
        price = cat.trim_price(fjord, FINANCING_TRIM, cheapest_drive(fjord), market)
        example = cat.financing_example(price, market)
        assert f"{fmt_int(example.monthly)} {currency} per month" in text


def test_company_car_row_only_in_swedish_column():
    for m in cat.models:
        lines = render_markdown("price_list", cat, m).splitlines()
        for trim, value in m.company_car_benefit_sek.items():
            rows = [line for line in lines if f"{fmt_int(value)} SEK per month" in line]
            assert rows, (m.slug, trim)
            assert all("EUR" not in row for row in rows)
        company = [line for line in lines if "company car" in line.lower()]
        assert company and all("EUR" not in line for line in company)


def test_brochure_and_specs_have_no_prices():
    for m in cat.models:
        for doc_type in ("brochure", "specifications"):
            text = render_markdown(doc_type, cat, m)
            assert "SEK" not in text and "EUR" not in text, (m.slug, doc_type)


def test_specs_have_exact_numbers():
    text = render_markdown("specifications", cat, fjord)
    for expected in ("84 kWh", "575 km", "240 kW", "640 litres", "1 720 litres", "2 100 kg",
                     "4 900 mm", "| 10 % | 240 kW |", "| 50 % | 200 kW |", "| 80 % | 95 kW |"):
        assert expected in text, expected
    for drive, perf in fjord.performance.items():
        assert any(drive in line and f"{perf.power_kw} kW" in line for line in text.splitlines())


def test_spark_still_not_rated_for_towing():
    spark = cat.by_slug("spark")
    for doc_type in ("brochure", "specifications"):
        assert "not rated for towing" in render_markdown(doc_type, cat, spark)


def test_no_undocumented_topic_anywhere():
    for doc_type, owner, text in all_documents():
        lowered = text.lower()
        for term in cat.not_documented:
            assert term.lower() not in lowered, (doc_type, owner, term)


def test_no_em_dash():
    for doc_type, owner, text in all_documents():
        assert EM_DASH not in text, (doc_type, owner)


def test_warranty_doc_has_battery_terms():
    text = render_markdown("warranty", cat, None)
    for expected in ("8 years", "160 000 km", "70 %", "Voltrieve Care Plus", "549 SEK"):
        assert expected in text, expected


def test_accessories_have_article_numbers_and_prices():
    parts = build_parts(cat)
    tow_bar = next(p for p in parts if p.key == "tow_bar" and any(f.slug == "fjord" for f in p.fits))
    text = render_markdown("accessories", cat, fjord)
    assert any(tow_bar.article in line and "16 900 SEK" in line for line in text.splitlines())
    assert any("VA-9021" in line and "7 990 SEK" in line for line in text.splitlines())
    assert "tow bar" not in render_markdown("accessories", cat, cat.by_slug("lumen")).lower()


def test_buyers_guide_keeps_the_old_facts():
    text = render_markdown("buyers_guide", cat, None)
    assert "749 000 SEK" in text and "67 900 EUR" in text
    assert "not rated for towing" in text
    for pack in cat.option_packs:
        assert pack in text


def test_brochure_pages_images_and_headline():
    text = render_markdown("brochure", cat, fjord)
    assert 9 <= text.count(PAGE_BREAK) <= 11  # 10 to 12 pages
    assert image_ref("fjord", "hero") in text
    perf = fjord.performance["AWD"]
    for expected in ("575 km", f"{charge_minutes_10_80(fjord)} min", f"{perf.power_kw} kW",
                     f"{perf.zero_to_100_s} s", "Room for the whole weekend"):
        assert expected in text, expected


def test_charge_time_is_plausible():
    for m in cat.models:
        assert 15 <= charge_minutes_10_80(m) <= 40, m.slug
    assert charge_minutes_10_80(cat.by_slug("atlas")) < charge_minutes_10_80(cat.by_slug("spark"))


def test_image_ref_is_relative():
    assert image_ref("fjord", "hero") == "fjord/hero.jpg"


def test_price_list_shows_wheels_and_optional_colors():
    from voltrieve_data.sales.render import image_ref

    m = cat.by_slug("fjord")
    md = render_markdown("price_list", cat, m)
    for w in m.wheels:
        assert image_ref("fjord", f"wheel_{w.key}") in md
    for c in m.colors:
        assert (image_ref("fjord", f"color_{c.key}") in md) is (not c.hero)


def test_dealer_prices_agree_with_the_price_lists():
    """get_prices answers from the dealer's data.json; it must say what the price lists say."""
    import json

    dealer = json.loads((Path(__file__).parents[3] / "services" / "dealer" / "app" / "data.json").read_text())
    for m in cat.models:
        md = render_markdown("price_list", cat, m)
        for market in ("SE", "EU"):
            pure = cat.trim_price(m, "Pure", "RWD" if "RWD" in m.drive else "AWD", market)
            assert dealer["prices"][market][m.slug] == pure, (m.slug, market)
            assert fmt_int(pure) in md
