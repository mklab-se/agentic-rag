"""Image prompts for the Voltrieve cars, built from data/design/cars.yaml.

Every prompt repeats the car's full identity (shape, signature, paint, cladding, wheels, plate),
so an image made months later still shows the same car as its studio master.
"""

import json
import subprocess
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path

import yaml
from pydantic import BaseModel

DEFAULT_CARS = Path(__file__).parents[3] / "design" / "cars.yaml"
REAR_SHOTS = frozenset({"master_rear", "rear_outdoor", "practical"})
_LOG_LOCK = threading.Lock()
RATE_LIMIT_WAITS = (30, 60, 90, 120, 180)  # seconds; a refused (HTTP 429) call is not billed


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
    color: str  # catalog key of the hero color that `paint` describes
    wheel: str  # catalog key of the wheel that `wheels` describes
    common: str
    shots: dict[str, str]
    paint_for: dict[str, str] = {}  # variant shot -> paint text that replaces the car's own
    wheels_for: dict[str, str] = {}  # variant shot -> wheel text that replaces the car's own


def load_identities(path: Path = DEFAULT_CARS, catalog=None) -> dict[str, CarIdentity]:
    """The cars from cars.yaml. With the catalog, each car also gets its variant shots:
    color_<key> for every optional color and wheel_<key> for every wheel, named from voltrieve.yaml."""
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    cars = {}
    for slug, car in data["cars"].items():
        shots, paint_for, wheels_for = dict(data["shots"]), {}, {}
        if catalog is not None:
            model = catalog.by_slug(slug)
            hero = next(c.key for c in model.colors if c.hero)
            if car["color"] != hero:
                raise ValueError(f"{slug}: color {car['color']!r} is not the catalog hero color {hero!r}")
            if car["wheel"] not in {w.key for w in model.wheels}:
                raise ValueError(f"{slug}: wheel {car['wheel']!r} is not a {model.name} wheel in the catalog")
            for color in model.colors:
                if not color.hero:
                    shot = f"color_{color.key}"
                    shots[shot] = data["variants"]["color"]
                    paint_for[shot] = f"{color.description} {color.finish} paint."
            for wheel in model.wheels:
                shot = f"wheel_{wheel.key}"
                shots[shot] = data["variants"]["wheel"]
                wheels_for[shot] = f"{wheel.inches} inch alloy wheels with {wheel.description}."
        cars[slug] = CarIdentity(slug=slug, common=data["common"], shots=shots,
                                 paint_for=paint_for, wheels_for=wheels_for, **car)
    return cars


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
            f"Paint: {car.paint_for.get(shot, car.paint)}",
            car.cladding,
            f"Wheels: {car.wheels_for.get(shot, car.wheels)}",
            f"License plate text: {car.plate}.",
            scene,
        ]
    )


def _refs(slug: str, shot: str, out_dir: Path) -> list[Path]:
    """Masters: the front is made from text; everything else is edited from the masters."""
    if shot == "master_front":
        return []
    refs = [out_dir / slug / "master_front.png"]
    if shot in REAR_SHOTS and shot != "master_rear":
        refs.append(out_dir / slug / "master_rear.png")
    return refs


def _generate_car(car: CarIdentity, shots: list[str] | None, out_dir: Path, run, wait) -> list[Path]:
    created = []
    (out_dir / car.slug).mkdir(parents=True, exist_ok=True)
    for shot in shots or list(car.shots):
        target = out_dir / car.slug / f"{shot}.png"
        if target.exists():
            continue
        refs = _refs(car.slug, shot, out_dir)
        cmd = ["ailloy", "image", build_prompt(car, shot), "-o", str(target)]
        cmd += ["--size", "1536x1024", "--quality", "high", "--raw"]
        for ref in refs:
            cmd += ["--ref", str(ref)]
        result = run(cmd, capture_output=True, text=True)
        for delay in RATE_LIMIT_WAITS:
            if result.returncode == 0 or "HTTP 429" not in (result.stderr or ""):
                break
            wait(delay)
            result = run(cmd, capture_output=True, text=True)
        ok = result.returncode == 0 and target.exists()
        _log(out_dir, car.slug, shot, refs, ok, "" if ok else (result.stderr or "").strip()[:300])
        if ok:
            created.append(target)
    return created


def _log(out_dir: Path, slug: str, shot: str, refs: list[Path], ok: bool, error: str) -> None:
    entry = {
        "time": datetime.now(UTC).isoformat(timespec="seconds"),
        "slug": slug,
        "shot": shot,
        "refs": [ref.name for ref in refs],
        "ok": ok,
    }
    if error:
        entry["error"] = error
    with _LOG_LOCK, (out_dir / "generation-log.jsonl").open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(entry) + "\n")


def generate_images(
    cars: dict[str, CarIdentity], shots: list[str] | None, out_dir: Path, run=subprocess.run,
    wait=time.sleep,
) -> list[Path]:
    """Generate missing images, one car per thread (shots in order, so masters come first).

    With no shot list, each car gets every shot it has, its variant shots included.
    A rate-limited call waits and is retried (RATE_LIMIT_WAITS).

    Existing files are skipped, so a rerun never pays for an image twice.
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    with ThreadPoolExecutor(max_workers=len(cars) or 1) as pool:
        results = pool.map(lambda car: _generate_car(car, shots, out_dir, run, wait), cars.values())
    return [path for created in results for path in created]


def contact_sheet(slug: str, out_dir: Path) -> Path:
    """A labelled grid of one car's images, for review."""
    from PIL import Image, ImageDraw

    files = sorted((out_dir / slug).glob("*.png"))
    thumb_w, thumb_h, label_h = 768, 512, 36
    cols = 2
    rows = max(1, -(-len(files) // cols))
    sheet = Image.new("RGB", (cols * thumb_w, rows * (thumb_h + label_h)), "white")
    draw = ImageDraw.Draw(sheet)
    for i, file in enumerate(files):
        x, y = (i % cols) * thumb_w, (i // cols) * (thumb_h + label_h)
        with Image.open(file) as image:
            sheet.paste(image.convert("RGB").resize((thumb_w, thumb_h)), (x, y))
        draw.text((x + 12, y + thumb_h + 8), f"{slug} / {file.stem}", fill="black")
    target = out_dir / f"contact-{slug}.jpg"
    sheet.save(target, quality=85)
    return target
