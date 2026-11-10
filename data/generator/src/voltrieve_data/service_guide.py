"""The workshop guide: what each job consists of. It holds no article numbers: those are in
the spare parts catalog, so a question about the parts for a job needs both."""

from pathlib import Path

from voltrieve_data.model import CarModel, Catalog
from voltrieve_data.parts import has_front_carrier, has_wear_sensor


def _front_discs(model: CarModel) -> str:
    return ", ".join(f"{mm} mm on {drive}" for drive, mm in model.brakes.front_disc_mm.items())


def _components(model: CarModel, axle: str) -> list[str]:
    side = "the side being worked on"
    items = [
        f"1 brake disc for {side}",
        f"1 brake pad set for the {axle} axle. The set covers both sides of the axle",
        f"1 brake caliper for {side}",
    ]
    if axle == "rear" or has_front_carrier(model):
        items.append(f"1 caliper carrier for {side}")
    items.append(f"1 brake hose for {side}")
    if has_wear_sensor(model):
        items.append(f"1 pad wear sensor for {side}")
    items += [
        f"1 caliper fitting kit for the {axle} axle",
        f"1 brake dust shield for {side}",
        "1 bottle of brake fluid DOT 4 LV, for bleeding the circuit afterwards",
    ]
    return items


def write_service_guide(catalog: Catalog, out_dir: Path) -> Path:
    lines = [
        f"# {catalog.company.name} service guide",
        "",
        "This guide describes what each workshop job consists of on every Voltrieve model. It "
        "names the components a job needs. Article numbers are not listed here: they are in "
        "the spare parts catalog.",
        "",
        "## Fluids and oil",
        "",
        "Voltrieve cars are electric and have no engine, so they need no engine oil and no oil "
        "change. The only oil is the reduction gear oil in the drive unit, checked at the "
        "scheduled service. The other fluids are brake fluid, battery coolant and washer fluid.",
        "",
        "## Before any work under the car",
        "",
        "Put the car in service mode from the centre screen. This releases the electric parking "
        "brake, stops regenerative braking and keeps the high voltage system asleep. Never open "
        "orange high voltage cables. Left and right are seen from the driver's seat.",
        "",
        "## Brake system overview",
        "",
        "| Model | Front discs | Front caliper | Rear discs | Rear caliper |",
        "|---|---|---|---|---|",
    ]
    for m in catalog.models:
        lines.append(
            f"| {m.name} | {_front_discs(m)} | {m.brakes.front_caliper} "
            f"| {m.brakes.rear_disc_mm} mm | {m.brakes.rear_caliper} |"
        )
    lines += [""]
    for axle in ("front", "rear"):
        lines += [f"## Complete {axle} brake replacement on one side", ""]
        lines += [
            f"A complete {axle} brake replacement renews every wearing and hydraulic part of the "
            "brake on one corner of the car. Pads are always renewed as an axle set, even when "
            "only one side is being worked on. The other side of the axle keeps its disc and "
            "caliper unless they are worn too.",
            "",
        ]
        for m in catalog.models:
            lines += [f"### {m.name}: complete {axle} brake replacement on one side", ""]
            drives = " and ".join(m.drive)
            lines.append(f"Applies to the {m.name} ({drives}). The job needs:")
            lines += ["", *[f"- {item}" for item in _components(m, axle)], ""]
            if axle == "front" and not has_front_carrier(m):
                lines += [f"The {m.name} has a fixed caliper, so there is no caliper carrier.", ""]
            if not has_wear_sensor(m):
                lines += [f"The {m.name} has no electrical pad wear sensor.", ""]
            if axle == "front" and len(m.brakes.front_disc_mm) > 1:
                lines += [
                    f"Front brake parts differ between drives on the {m.name}: "
                    f"{_front_discs(m)}. Check the drive before ordering.",
                    "",
                ]
    lines += [
        "## Wheel bearing replacement",
        "",
        "The wheel bearing and hub is one sealed unit. Renew it per corner. The job needs 1 wheel "
        "bearing and hub for that corner, and the brake disc must come off to reach it. On AWD "
        "cars the front drive shaft nut is renewed at the same time.",
        "",
        "## Cabin air filter",
        "",
        "The cabin air filter sits behind the passenger footwell trim and is changed every two "
        "years. No tools are needed apart from a trim tool.",
        "",
        "## Air suspension on the Voltrieve Fjord",
        "",
        "The Voltrieve Fjord has air suspension. Before lifting the car, turn off automatic "
        "levelling from the centre screen. A front air strut or rear air spring is renewed one "
        "corner at a time.",
        "",
    ]
    path = out_dir / "voltrieve-service-guide.md"
    path.write_text("\n".join(lines), encoding="utf-8")
    return path
