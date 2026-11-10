"""Image prompts for the Voltrieve cars, built from data/design/cars.yaml.

Every prompt repeats the car's full identity (shape, signature, paint, cladding, wheels, plate),
so an image made months later still shows the same car as its studio master.
"""

from pathlib import Path

import yaml
from pydantic import BaseModel

DEFAULT_CARS = Path(__file__).parents[3] / "design" / "cars.yaml"
REAR_SHOTS = frozenset({"master_rear", "rear_outdoor", "practical"})


class CarIdentity(BaseModel):
    slug: str
    shape: str
    front_signature: str
    rear_signature: str
    paint: str
    cladding: str
    wheels: str
    interior: str
    landscape: str
    plate: str
    common: str
    shots: dict[str, str]


def load_identities(path: Path = DEFAULT_CARS) -> dict[str, CarIdentity]:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    return {
        slug: CarIdentity(slug=slug, common=data["common"], shots=data["shots"], **car)
        for slug, car in data["cars"].items()
    }


SHOTS: dict[str, str] = yaml.safe_load(DEFAULT_CARS.read_text(encoding="utf-8"))["shots"]


def build_prompt(car: CarIdentity, shot: str) -> str:
    """Common rules, then the car, then the scene. Rear shots describe the rear signature."""
    signature = car.rear_signature if shot in REAR_SHOTS else car.front_signature
    scene = car.shots[shot].replace("{landscape}", car.landscape)
    return " ".join(
        [
            car.common,
            f"The car: {car.shape}",
            f"Signature lights: {signature}",
            f"Paint: {car.paint}",
            car.cladding,
            f"Wheels: {car.wheels}",
            f"License plate text: {car.plate}.",
            scene,
        ]
    )
