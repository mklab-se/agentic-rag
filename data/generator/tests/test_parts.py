import json
import re
from pathlib import Path

import pytest

from voltrieve_data.generate import generate_all
from voltrieve_data.load import load_catalog
from voltrieve_data.parts import build_parts, job_keys, job_parts

CATALOG_PATH = Path(__file__).parents[2] / "voltrieve.yaml"
ARTICLE = re.compile(r"VP-\d{5}")


@pytest.fixture(scope="module")
def catalog():
    return load_catalog(CATALOG_PATH)


@pytest.fixture(scope="module")
def parts(catalog):
    return build_parts(catalog)


def test_article_numbers_are_unique(parts):
    articles = [p.article for p in parts]
    assert len(articles) == len(set(articles))
    assert all(ARTICLE.fullmatch(a) for a in articles)


def test_numbers_are_stable_between_runs(catalog, parts):
    assert [p.article for p in build_parts(catalog)] == [p.article for p in parts]


def test_every_part_fits_something(parts):
    assert all(p.fits for p in parts)


def test_front_brake_parts_differ_by_drive_only_where_the_disc_does(catalog, parts):
    discs = [p for p in parts if p.key == "brake_disc_front_left"]
    assert {f.name for p in discs for f in p.fits} == {
        "Voltrieve Spark", "Voltrieve Lumen RWD", "Voltrieve Lumen AWD", "Voltrieve Ragn",
        "Voltrieve Fjord RWD", "Voltrieve Fjord AWD", "Voltrieve Atlas",
    }
    fjord = {p.fits[0].name: p for p in discs if p.fits[0].slug == "fjord"}
    assert "345 mm" in fjord["Voltrieve Fjord RWD"].spec
    assert "370 mm" in fjord["Voltrieve Fjord AWD"].spec


def test_shared_parts_list_every_model_on_the_platform(parts):
    hose = next(p for p in parts if p.key == "brake_hose_front_left" and len(p.fits) == 3)
    assert {f.slug for f in hose.fits} == {"ragn", "fjord", "atlas"}


def test_rwd_cars_have_no_front_drive_shaft(parts):
    shafts = {f.name for p in parts if p.key == "drive_shaft_front_left" for f in p.fits}
    assert "Voltrieve Lumen AWD" in shafts and "Voltrieve Fjord AWD" in shafts
    assert not [name for name in shafts if name.endswith("RWD") or "Spark" in name]


def test_every_vehicle_can_complete_every_brake_job(catalog, parts):
    for model in catalog.models:
        for drive in model.drive:
            for axle in ("front", "rear"):
                for side in ("left", "right"):
                    assert job_parts(parts, model, drive, axle, side)


def test_job_follows_the_hardware_of_the_model(catalog):
    atlas = job_keys(catalog.by_slug("atlas"), "front", "left")
    spark = job_keys(catalog.by_slug("spark"), "front", "left")
    assert "caliper_carrier_front_left" not in atlas and "wear_sensor_front_left" in atlas
    assert "caliper_carrier_front_left" in spark and "wear_sensor_front_left" not in spark


def test_catalog_documents_are_long_and_self_describing(tmp_path):
    generate_all(CATALOG_PATH, tmp_path)
    brakes = (tmp_path / "voltrieve-parts-brakes.md").read_text(encoding="utf-8")
    rows = [line for line in brakes.splitlines() if line.startswith("| VP-")]
    assert len(rows) > 150
    assert all("Voltrieve " in row for row in rows)
    for name in ("spark", "lumen", "ragn", "fjord", "atlas"):
        assert f"Voltrieve {name.capitalize()}" in brakes


def test_only_the_catalog_has_article_numbers(tmp_path):
    generate_all(CATALOG_PATH, tmp_path)
    guide = (tmp_path / "voltrieve-service-guide.md").read_text(encoding="utf-8")
    assert not ARTICLE.search(guide)
    assert "Complete front brake replacement" in guide
    catalog_text = (tmp_path / "voltrieve-parts-brakes.md").read_text(encoding="utf-8")
    assert "Complete front brake replacement" not in catalog_text


def test_catalog_does_not_invent_undocumented_topics(tmp_path, catalog):
    generate_all(CATALOG_PATH, tmp_path)
    for file in ["voltrieve-service-guide.md", *sorted(p.name for p in tmp_path.glob("voltrieve-parts-*"))]:
        text = (tmp_path / file).read_text(encoding="utf-8").lower()
        assert not [t for t in catalog.not_documented if t.lower() in text], file


def test_index_records_the_expected_articles_of_each_job(tmp_path):
    generate_all(CATALOG_PATH, tmp_path)
    index = json.loads((tmp_path / "parts-index.json").read_text())
    job = index["jobs"]["fjord/AWD/front/left"]
    assert len(job) == 9
    assert len(index["parts"]) == index["count"]
