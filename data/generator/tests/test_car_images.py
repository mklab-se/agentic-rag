from pathlib import Path

from voltrieve_data.car_images import SHOTS, build_prompt, load_identities

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
