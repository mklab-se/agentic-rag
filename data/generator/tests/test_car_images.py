from pathlib import Path

from voltrieve_data.car_images import SHOTS, build_prompt, generate_images, load_identities

CARS = Path(__file__).parents[2] / "design" / "cars.yaml"
EM_DASH = chr(0x2014)


def test_all_five_cars_present():
    assert set(load_identities(CARS)) == {"spark", "lumen", "ragn", "fjord", "atlas"}


def test_every_prompt_repeats_identity():
    for car in load_identities(CARS).values():
        for shot in SHOTS:
            prompt = build_prompt(car, shot)
            assert car.plate in prompt
            assert car.wheels in prompt
            assert car.paint in prompt


def test_front_shots_use_front_signature_and_rear_shots_rear():
    fjord = load_identities(CARS)["fjord"]
    assert fjord.front_signature in build_prompt(fjord, "master_front")
    assert fjord.rear_signature in build_prompt(fjord, "master_rear")
    assert fjord.front_signature not in build_prompt(fjord, "master_rear")


def test_fjord_rear_has_no_pillar_lights():
    assert "pillar" not in load_identities(CARS)["fjord"].rear_signature.lower()


def test_lumen_is_a_compact_hatchback():
    shape = load_identities(CARS)["lumen"].shape.lower()
    assert "compact" in shape and "hatchback" in shape


def test_no_em_dash_in_prompts():
    cars = load_identities(CARS).values()
    assert all(EM_DASH not in build_prompt(car, shot) for car in cars for shot in SHOTS)


FJORD = load_identities(CARS)["fjord"]


def fake(calls):
    """A stand-in for subprocess.run that records the ailloy command and writes the output file."""

    def run(cmd, **kwargs):
        calls.append(cmd)
        Path(cmd[cmd.index("-o") + 1]).write_bytes(b"png")

        class Done:
            returncode = 0
            stderr = ""

        return Done()

    return run


def test_skips_existing_files(tmp_path):
    (tmp_path / "fjord").mkdir()
    (tmp_path / "fjord" / "master_front.png").write_bytes(b"x")
    calls = []
    generate_images({"fjord": FJORD}, ["master_front"], tmp_path, run=fake(calls))
    assert calls == []


def test_master_front_is_text_only(tmp_path):
    calls = []
    generate_images({"fjord": FJORD}, ["master_front"], tmp_path, run=fake(calls))
    assert "--ref" not in calls[0] and calls[0][:2] == ["ailloy", "image"]


def test_rear_master_edits_from_front(tmp_path):
    calls = []
    generate_images({"fjord": FJORD}, ["master_front", "master_rear"], tmp_path, run=fake(calls))
    rear = calls[1]
    assert rear[rear.index("--ref") + 1].endswith("fjord/master_front.png")
    assert "--fidelity" not in rear


def test_every_call_is_logged(tmp_path):
    generate_images({"fjord": FJORD}, ["master_front"], tmp_path, run=fake([]))
    assert len((tmp_path / "generation-log.jsonl").read_text().splitlines()) == 1


from voltrieve_data.load import load_catalog  # noqa: E402

CATALOG = load_catalog(Path(__file__).parents[2] / "voltrieve.yaml")
WITH_VARIANTS = load_identities(CARS, CATALOG)


def test_color_variant_names_catalog_color():
    fjord = WITH_VARIANTS["fjord"]
    heath = next(c for c in CATALOG.by_slug("fjord").colors if c.key == "heath")
    prompt = build_prompt(fjord, "color_heath")
    assert f"{heath.description} {heath.finish} paint" in prompt
    assert fjord.paint not in prompt
    assert fjord.plate in prompt and fjord.wheels in prompt


def test_wheel_variant_names_catalog_wheel():
    fjord = WITH_VARIANTS["fjord"]
    birch = next(w for w in CATALOG.by_slug("fjord").wheels if w.key == "birch_19")
    prompt = build_prompt(fjord, "wheel_birch_19")
    assert f"{birch.inches} inch alloy wheels with {birch.description}" in prompt
    assert fjord.wheels not in prompt
    assert fjord.paint in prompt


def test_variant_shots_follow_the_catalog():
    for slug, car in WITH_VARIANTS.items():
        model = CATALOG.by_slug(slug)
        expected = {f"color_{c.key}" for c in model.colors if not c.hero} | {f"wheel_{w.key}" for w in model.wheels}
        variants = {shot for shot in car.shots if shot.startswith(("color_", "wheel_"))}
        assert variants == expected


def test_variants_edit_from_the_front_master(tmp_path):
    calls = []
    generate_images({"fjord": WITH_VARIANTS["fjord"]}, ["color_heath"], tmp_path, run=fake(calls))
    assert calls[0][calls[0].index("--ref") + 1].endswith("fjord/master_front.png")


def test_without_a_catalog_there_are_no_variants():
    assert not any(shot.startswith(("color_", "wheel_")) for shot in load_identities(CARS)["fjord"].shots)


def test_no_shot_list_means_every_shot_of_each_car(tmp_path):
    calls = []
    fjord = WITH_VARIANTS["fjord"]
    generate_images({"fjord": fjord}, None, tmp_path, run=fake(calls))
    made = [Path(cmd[cmd.index("-o") + 1]).stem for cmd in calls]
    assert made == list(fjord.shots) and made[:2] == ["master_front", "master_rear"]


def test_rate_limited_calls_wait_and_retry(tmp_path):
    calls, waits = [], []
    ok = fake(calls)

    def limited(cmd, **kwargs):
        if len(calls) < 2:
            calls.append(cmd)

            class Limited:
                returncode = 1
                stderr = "Error: Microsoft Foundry API error (HTTP 429): rate limit"

            return Limited()
        return ok(cmd, **kwargs)

    created = generate_images({"fjord": FJORD}, ["master_front"], tmp_path, run=limited, wait=waits.append)
    assert len(created) == 1 and len(calls) == 3 and len(waits) == 2
    log = (tmp_path / "generation-log.jsonl").read_text().splitlines()
    assert len(log) == 1  # one image, one log line


def test_each_car_names_its_catalog_hero_color_and_wheel():
    for slug, car in WITH_VARIANTS.items():
        model = CATALOG.by_slug(slug)
        assert car.color == next(c.key for c in model.colors if c.hero)
        assert car.wheel in {w.key for w in model.wheels}
        wheel = next(w for w in model.wheels if w.key == car.wheel)
        assert car.wheels.startswith(f"{wheel.inches} inch")


def test_an_unknown_wheel_key_fails_loading(tmp_path):
    import pytest

    text = CARS.read_text(encoding="utf-8").replace("wheel: fern_20", "wheel: fern_99")
    bad = tmp_path / "cars.yaml"
    bad.write_text(text, encoding="utf-8")
    with pytest.raises(ValueError, match="fern_99"):
        load_identities(bad, CATALOG)
