"""The spare parts catalog: every article number, derived from the car catalog.

A template says what a part is and how widely it fits. Its scope decides how many article
numbers it becomes:

  drive     one per model and drive, for parts that differ by drive
  model     one per model
  platform  one per platform, shared by the models on it
  all       one for the whole range
  wheel     one per model and tyre size, for tyres (wheels with the same size share one)

Numbers are assigned in template order, so the output is the same on every run. Article numbers
never change once published: every document has its original templates and its added ones, and
all original templates are numbered before any added template. New templates go at the end of
an added list, never among the original ones.
"""

from collections.abc import Callable
from dataclasses import dataclass
from typing import Literal

from voltrieve_data.model import CarModel, Catalog, Wheel

Scope = Literal["drive", "model", "platform", "all", "wheel"]
FIRST_ARTICLE = 10007
ARTICLE_STEP = 13
SIDES = ("left", "right")
AXLES = ("front", "rear")


@dataclass(frozen=True)
class Fit:
    slug: str
    name: str  # "Voltrieve Fjord AWD", or "Voltrieve Fjord" when every drive fits


@dataclass(frozen=True)
class Part:
    article: str
    key: str  # stable name for a job to refer to, such as brake_disc_front_left
    document: str
    system: str
    name: str
    position: str
    spec: str
    quantity: int
    fits: tuple[Fit, ...]
    wheels: tuple[str, ...] = ()  # the wheel keys a tyre is for; empty for every other part


# A spec is text, or made from the model and the drive (or, for wheel scope, the wheels).
Spec = str | Callable[[CarModel, str | None], str] | Callable[[CarModel, list[Wheel]], str]


@dataclass(frozen=True)
class Template:
    key: str
    name: str
    system: str
    scope: Scope
    spec: Spec
    position: str = "Not applicable"
    quantity: int = 1
    when: Callable[[CarModel], bool] = lambda model: True
    only_drive: str | None = None


def _sided(key: str, name: str, axle: str | None, **kwargs) -> list[Template]:
    """One template per side, or per corner when an axle is given."""
    templates = []
    for side in SIDES:
        where = f"{axle} {side}" if axle else side
        suffix = f"{axle}_{side}" if axle else side
        templates.append(
            Template(f"{key}_{suffix}", f"{name}, {where}", position=where.capitalize(), **kwargs)
        )
    return templates


def _corners(key: str, name: str, **kwargs) -> list[Template]:
    return [t for axle in AXLES for t in _sided(key, name, axle, **kwargs)]


def _front_disc(model: CarModel, drive: str | None) -> str:
    return f"{model.brakes.front_disc_mm[drive]} mm ventilated brake disc"


def _rear_disc(model: CarModel, drive: str | None) -> str:
    return f"{model.brakes.rear_disc_mm} mm ventilated brake disc"


def _front_caliper(model: CarModel, drive: str | None) -> str:
    return f"{model.brakes.front_caliper} caliper for the {model.brakes.front_disc_mm[drive]} mm disc"


def _rear_caliper(model: CarModel, drive: str | None) -> str:
    return f"{model.brakes.rear_caliper} caliper, with integrated parking brake mount"


def _front_pads(model: CarModel, drive: str | None) -> str:
    return (
        f"Set of 4 pads for the {model.brakes.front_disc_mm[drive]} mm disc, "
        "covers the left and right side of the axle"
    )


def _rear_pads(model: CarModel, drive: str | None) -> str:
    return (
        f"Set of 4 pads for the {model.brakes.rear_disc_mm} mm disc, "
        "covers the left and right side of the axle"
    )


def has_front_carrier(model: CarModel) -> bool:
    return "floating" in model.brakes.front_caliper


def has_wear_sensor(model: CarModel) -> bool:
    return model.platform == "V2"


def _v2(model: CarModel) -> bool:
    return model.platform == "V2"


def _named(*slugs: str) -> Callable[[CarModel], bool]:
    return lambda model: model.slug in slugs


def _charger(model: CarModel, drive: str | None) -> str:
    return f"{'22' if model.platform == 'V2' else '11'} kW onboard charger module"


def _traction(model: CarModel, drive: str | None) -> str:
    return f"Traction motor inverter for {model.voltage} V systems"


FRONT_BRAKES = "Front brakes"
REAR_BRAKES = "Rear brakes"
HYDRAULICS = "Brake hydraulics and control"
SUSPENSION = "Suspension"
STEERING = "Steering"
WHEEL_ENDS = "Wheel bearings and hubs"
EXTERIOR = "Body panels"
GLASS = "Glass and mirrors"
LIGHTS = "Lighting"
CHARGING = "Charging"
HIGH_VOLTAGE = "High voltage and thermal"
SENSORS = "Sensors and low voltage"
CONSUMABLES = "Fluids and filters"
WEAR = "Wear items"
TOWING = "Towing equipment"

BRAKE_TEMPLATES = [
    *_sided("brake_disc", "Brake disc", "front", system=FRONT_BRAKES, scope="drive", spec=_front_disc),
    Template("brake_pads_front", "Brake pad set, front axle", FRONT_BRAKES, "drive", _front_pads,
             position="Front axle"),
    *_sided("brake_caliper", "Brake caliper", "front", system=FRONT_BRAKES, scope="drive",
            spec=_front_caliper),
    *_sided("caliper_carrier", "Caliper carrier", "front", system=FRONT_BRAKES, scope="drive",
            spec="Carrier bracket for the floating caliper", when=has_front_carrier),
    *_sided("brake_hose", "Brake hose", "front", system=FRONT_BRAKES, scope="platform",
            spec="Reinforced flexible hose with banjo fitting"),
    *_sided("wear_sensor", "Pad wear sensor", "front", system=FRONT_BRAKES, scope="platform",
            spec="Electrical pad wear sensor", when=has_wear_sensor),
    Template("caliper_kit_front", "Caliper fitting kit, front axle", FRONT_BRAKES, "platform",
             "Slide pins, bolts and anti rattle clips for one side", position="Front axle"),
    *_sided("dust_shield", "Brake dust shield", "front", system=FRONT_BRAKES, scope="model",
            spec="Pressed steel shield"),
    *_sided("brake_disc", "Brake disc", "rear", system=REAR_BRAKES, scope="model", spec=_rear_disc),
    Template("brake_pads_rear", "Brake pad set, rear axle", REAR_BRAKES, "model", _rear_pads,
             position="Rear axle"),
    *_sided("brake_caliper", "Brake caliper", "rear", system=REAR_BRAKES, scope="model",
            spec=_rear_caliper),
    *_sided("caliper_carrier", "Caliper carrier", "rear", system=REAR_BRAKES, scope="platform",
            spec="Carrier bracket for the floating caliper"),
    *_sided("brake_hose", "Brake hose", "rear", system=REAR_BRAKES, scope="platform",
            spec="Reinforced flexible hose with banjo fitting"),
    *_sided("wear_sensor", "Pad wear sensor", "rear", system=REAR_BRAKES, scope="platform",
            spec="Electrical pad wear sensor", when=has_wear_sensor),
    Template("caliper_kit_rear", "Caliper fitting kit, rear axle", REAR_BRAKES, "platform",
             "Slide pins, bolts and anti rattle clips for one side", position="Rear axle"),
    *_sided("dust_shield", "Brake dust shield", "rear", system=REAR_BRAKES, scope="model",
            spec="Pressed steel shield"),
    *_sided("parking_motor", "Parking brake motor", "rear", system=REAR_BRAKES, scope="platform",
            spec="Electric actuator mounted on the caliper"),
    *_corners("wheel_speed_sensor", "Wheel speed sensor", system=HYDRAULICS, scope="platform",
              spec="Active wheel speed sensor with harness"),
    Template("brake_booster", "Electric brake booster", HYDRAULICS, "model",
             "Integrated booster and master cylinder unit", position="Bulkhead"),
    Template("stability_module", "Stability control module", HYDRAULICS, "platform",
             "Hydraulic control unit with ABS and regenerative blending",
             position="Front compartment"),
    Template("fluid_reservoir", "Brake fluid reservoir", HYDRAULICS, "platform",
             "Reservoir with level sensor and cap", position="Bulkhead"),
    Template("bleed_nipple_kit", "Bleed nipple kit", HYDRAULICS, "all",
             "Set of 4 bleed nipples with dust caps"),
]

SUSPENSION_TEMPLATES = [
    *_sided("strut", "Front strut", "front", system=SUSPENSION, scope="drive",
            spec="Gas pressure strut with top mount seat", when=_named("spark", "lumen", "ragn", "atlas")),
    *_sided("air_strut", "Front air strut", "front", system=SUSPENSION, scope="drive",
            spec="Air spring strut with height sensor bracket", when=_named("fjord")),
    *_sided("rear_damper", "Rear damper", "rear", system=SUSPENSION, scope="model",
            spec="Gas pressure damper", when=_named("spark", "lumen", "ragn", "atlas")),
    *_sided("rear_air_spring", "Rear air spring", "rear", system=SUSPENSION, scope="model",
            spec="Air spring with damper module", when=_named("fjord")),
    Template("air_compressor", "Air suspension compressor", SUSPENSION, "model",
             "Compressor with dryer and valve block", position="Rear underfloor", when=_named("fjord")),
    *_sided("rear_spring", "Rear coil spring", "rear", system=SUSPENSION, scope="model",
            spec="Progressive coil spring", when=_named("spark", "lumen", "ragn", "atlas")),
    *_sided("lower_arm", "Lower control arm", "front", system=SUSPENSION, scope="platform",
            spec="Forged arm with bushes and ball joint"),
    *_sided("upper_arm", "Upper control arm", "rear", system=SUSPENSION, scope="platform",
            spec="Pressed arm with bushes"),
    *_sided("trailing_arm", "Trailing arm", "rear", system=SUSPENSION, scope="platform",
            spec="Forged arm with rubber bush"),
    *_sided("stabilizer_link", "Stabilizer link", "front", system=SUSPENSION, scope="platform",
            spec="Link with ball joints at both ends"),
    *_sided("stabilizer_link", "Stabilizer link", "rear", system=SUSPENSION, scope="platform",
            spec="Link with ball joints at both ends"),
    Template("stabilizer_bar_front", "Stabilizer bar, front axle", SUSPENSION, "model",
             "Hollow bar with bushes", position="Front axle"),
    Template("stabilizer_bar_rear", "Stabilizer bar, rear axle", SUSPENSION, "model",
             "Hollow bar with bushes", position="Rear axle"),
    Template("subframe_front", "Front subframe", SUSPENSION, "platform",
             "Welded subframe with bushes", position="Front axle"),
    *_sided("tie_rod", "Tie rod end", None, system=STEERING, scope="platform",
            spec="Outer tie rod end with lock nut"),
    *_sided("inner_rod", "Inner tie rod", None, system=STEERING, scope="platform",
            spec="Inner rod with boot"),
    Template("steering_rack", "Steering rack", STEERING, "model",
             "Electric power steering rack", position="Front axle"),
    Template("steering_column", "Steering column", STEERING, "model",
             "Adjustable column with intermediate shaft", position="Cabin"),
    Template("rear_steering_actuator", "Rear wheel steering actuator", STEERING, "model",
             "Electric actuator for rear wheel steering", position="Rear axle", when=_named("atlas")),
    *_corners("wheel_bearing", "Wheel bearing and hub", system=WHEEL_ENDS, scope="platform",
              spec="Sealed hub unit with bolts"),
    *_sided("drive_shaft", "Drive shaft", "front", system=WHEEL_ENDS, scope="drive",
            spec="Constant velocity drive shaft for the front motor",
            when=lambda model: "AWD" in model.drive, only_drive="AWD"),
    *_sided("drive_shaft", "Drive shaft", "rear", system=WHEEL_ENDS, scope="model",
            spec="Constant velocity drive shaft for the rear motor"),
]

BODY_TEMPLATES = [
    Template("bumper_front", "Front bumper cover", EXTERIOR, "model", "Primed, ready for paint",
             position="Front"),
    Template("bumper_rear", "Rear bumper cover", EXTERIOR, "model", "Primed, ready for paint",
             position="Rear"),
    Template("bonnet", "Bonnet", EXTERIOR, "model", "Aluminium panel", position="Front"),
    Template("tailgate", "Tailgate", EXTERIOR, "model", "Primed, without glass", position="Rear"),
    *_sided("wing", "Front wing", "front", system=EXTERIOR, scope="model", spec="Primed steel panel"),
    *_corners("door_shell", "Door shell", system=EXTERIOR, scope="model", spec="Primed, without trim"),
    *_corners("door_handle", "Door handle", system=EXTERIOR, scope="platform",
              spec="Flush handle with presentation motor"),
    *_sided("wheel_arch_liner", "Wheel arch liner", "front", system=EXTERIOR, scope="model",
            spec="Moulded liner with clips"),
    Template("windscreen", "Windscreen", GLASS, "model", "Laminated, with camera bracket",
             position="Front"),
    Template("rear_window", "Rear window", GLASS, "model", "Heated", position="Rear"),
    *_sided("door_mirror", "Door mirror", None, system=GLASS, scope="model",
            spec="Heated, folding, with camera"),
    *_sided("mirror_glass", "Mirror glass", None, system=GLASS, scope="platform",
            spec="Heated replacement glass"),
    *_sided("headlamp", "LED headlamp", None, system=LIGHTS, scope="model",
            spec="Complete matrix LED unit"),
    *_sided("tail_lamp", "LED tail lamp", None, system=LIGHTS, scope="model",
            spec="Complete LED unit"),
    Template("high_brake_lamp", "High level brake lamp", LIGHTS, "platform", "LED strip",
             position="Rear"),
    Template("number_plate_lamp", "Number plate lamp", LIGHTS, "all", "LED module", position="Rear"),
]

ELECTRICAL_TEMPLATES = [
    Template("charge_port", "CCS2 charge port", CHARGING, "platform",
             "Inlet with latch and temperature sensors", position="Rear right"),
    Template("charge_port_door", "Charge port door", CHARGING, "model", "Motorised door",
             position="Rear right"),
    Template("onboard_charger", "Onboard charger", CHARGING, "platform", _charger,
             position="Rear underfloor"),
    Template("charge_cable_mode3", "Mode 3 charging cable", CHARGING, "all",
             "5 m cable, 32 A, type 2"),
    Template("charge_cable_mode2", "Mode 2 portable charger", CHARGING, "all",
             "Portable charger with Schuko plug"),
    Template("inverter", "Traction inverter", HIGH_VOLTAGE, "platform", _traction,
             position="Rear axle"),
    Template("dc_converter", "DC to DC converter", HIGH_VOLTAGE, "platform",
             "Converter to the 12 V system", position="Front compartment"),
    Template("heat_pump_unit", "Heat pump unit", HIGH_VOLTAGE, "platform",
             "Compressor and valve assembly", position="Front compartment"),
    Template("coolant_pump", "Battery coolant pump", HIGH_VOLTAGE, "platform", "Electric pump",
             position="Front compartment"),
    Template("hv_service_plug", "High voltage service disconnect", HIGH_VOLTAGE, "platform",
             "Service plug with interlock", position="Rear underfloor"),
    Template("battery_12v", "12 V battery", SENSORS, "model", "Lithium iron phosphate battery",
             position="Front compartment"),
    Template("front_camera", "Forward camera module", SENSORS, "platform",
             "Triple camera for Voltrieve Pilot", position="Windscreen"),
    *_corners("parking_sensor", "Parking sensor", system=SENSORS, scope="platform",
              spec="Ultrasonic sensor, primed"),
    Template("radar_front", "Front radar", SENSORS, "platform", "Long range radar", position="Front",
             when=_v2),
    Template("key_card", "Key card", SENSORS, "all", "NFC key card"),
]

SERVICE_TEMPLATES = [
    Template("brake_fluid", "Brake fluid DOT 4 LV", CONSUMABLES, "all", "1 litre bottle",
             position="Not applicable"),
    Template("coolant", "Battery coolant", CONSUMABLES, "all", "5 litre premix, blue"),
    Template("washer_fluid", "Washer fluid concentrate", CONSUMABLES, "all", "3 litre bottle"),
    Template("cabin_filter", "Cabin air filter", CONSUMABLES, "platform", "Activated carbon filter",
             position="Passenger footwell"),
    Template("reduction_oil", "Reduction gear oil", CONSUMABLES, "all", "1 litre bottle"),
    Template("wiper_blade_front", "Wiper blade set, front", WEAR, "model", "Pair of flat blades",
             position="Front"),
    Template("wiper_blade_rear", "Wiper blade, rear", WEAR, "model", "Single blade", position="Rear"),
    Template("wheel_bolt_set", "Wheel bolt set", WEAR, "platform", "Set of 20 bolts"),
    Template("locking_bolt_set", "Locking wheel bolt set", WEAR, "platform", "Set of 4 with adapter"),
    Template("tyre_valve_set", "Tyre pressure sensor set", WEAR, "platform", "Set of 4 sensors"),
    Template("tyre_repair_kit", "Tyre repair kit", WEAR, "all", "Sealant and 12 V compressor"),
    Template("floor_mats", "All weather floor mats", WEAR, "model", "Set of 4 mats", position="Cabin"),
    Template("tow_bar", "Electric tow bar", TOWING, "model", "Electrically deployable tow bar",
             position="Rear", when=lambda model: model.towing_kg is not None and "Tow" in model.option_packs),
    Template("tow_harness", "Tow bar harness", TOWING, "platform", "13 pin harness with control unit",
             position="Rear", when=_v2),
]

TYRES = "Tyres"


def _tyre(kind: str) -> Callable[[CarModel, list[Wheel]], str]:
    def spec(model: CarModel, wheels: list[Wheel]) -> str:
        short = model.name.removeprefix("Voltrieve ")
        names = " and ".join(dict.fromkeys(w.name for w in wheels))
        trims = [t.name for t in model.trims if t.wheel in {w.key for w in wheels}]
        listed = trims[0] if len(trims) == 1 else ", ".join(trims[:-1]) + " and " + trims[-1]
        return (f"{kind} {wheels[0].tyre_size}, for the {wheels[0].inches} inch {names} wheels "
                f"({short} {listed}). Sold one at a time")
    return spec


TYRE_TEMPLATES = [
    Template("tyre_summer", "Summer tyre", TYRES, "wheel", _tyre("Summer tyre"), position="Any wheel"),
    Template("tyre_winter_studless", "Winter tyre, studless", TYRES, "wheel",
             _tyre("Nordic studless winter tyre"), position="Any wheel"),
    Template("tyre_winter_studded", "Winter tyre, studded", TYRES, "wheel",
             _tyre("Nordic studded winter tyre"), position="Any wheel"),
]

# File name: (title, original templates, templates added after the first edition).
DOCUMENTS: dict[str, tuple[str, list[Template], list[Template]]] = {
    "voltrieve-parts-brakes.md": ("Brake system", BRAKE_TEMPLATES, []),
    "voltrieve-parts-suspension-steering.md": ("Suspension and steering", SUSPENSION_TEMPLATES, []),
    "voltrieve-parts-body-glass-lighting.md": ("Body, glass and lighting", BODY_TEMPLATES, []),
    "voltrieve-parts-electrical-charging.md": ("Electrical and charging", ELECTRICAL_TEMPLATES, []),
    "voltrieve-parts-service-items.md": ("Service items and accessories", SERVICE_TEMPLATES, []),
    "voltrieve-parts-wheels-tyres.md": ("Wheels and tyres", [], TYRE_TEMPLATES),
}


def _tyre_groups(fitting: list[CarModel]) -> list[tuple[list[CarModel], None, list[Wheel]]]:
    groups = []
    for m in fitting:
        sizes = dict.fromkeys(w.tyre_size for w in m.wheels)
        groups += [([m], None, [w for w in m.wheels if w.tyre_size == size]) for size in sizes]
    return groups


def _groups(template: Template, models: list[CarModel]) -> list[tuple[list[CarModel], str | None, list[Wheel]]]:
    """The models, drive and wheels each article number of a template covers."""
    fitting = [m for m in models if template.when(m)]
    if template.scope == "wheel":
        return _tyre_groups(fitting)
    return [(group, drive, []) for group, drive in _plain_groups(template, fitting)]


def _plain_groups(template: Template, fitting: list[CarModel]) -> list[tuple[list[CarModel], str | None]]:
    if template.scope == "drive":
        return [
            ([m], d) for m in fitting for d in m.drive if template.only_drive in (None, d)
        ]
    if template.scope == "model":
        return [([m], None) for m in fitting]
    if template.scope == "platform":
        platforms = dict.fromkeys(m.platform for m in fitting)
        return [([m for m in fitting if m.platform == p], None) for p in platforms]
    return [(fitting, None)] if fitting else []


def _fit(model: CarModel, drive: str | None) -> Fit:
    # A model with one drive has nothing to tell apart, so the drive is left out.
    if drive is None or len(model.drive) == 1:
        return Fit(model.slug, model.name)
    return Fit(model.slug, f"{model.name} {drive}")


def build_parts(catalog: Catalog) -> list[Part]:
    parts: list[Part] = []
    originals = [(doc, t) for doc, (_, templates, _) in DOCUMENTS.items() for t in templates]
    added = [(doc, t) for doc, (_, _, templates) in DOCUMENTS.items() for t in templates]
    for document, template in originals + added:
        for models, drive, wheels in _groups(template, catalog.models):
            spec = template.spec
            if callable(spec):
                spec = spec(models[0], wheels if template.scope == "wheel" else drive)
            article = f"VP-{FIRST_ARTICLE + ARTICLE_STEP * len(parts)}"
            parts.append(
                Part(
                    article, template.key, document, template.system, template.name,
                    template.position, spec, template.quantity,
                    tuple(_fit(m, drive) for m in models),
                    tuple(w.key for w in wheels),
                )
            )
    return parts


def fits_vehicle(part: Part, model: CarModel, drive: str) -> bool:
    return any(f.name in (model.name, f"{model.name} {drive}") for f in part.fits)


def job_keys(model: CarModel, axle: str, side: str) -> list[str]:
    """The parts of a complete brake replacement on one corner of a model."""
    keys = [f"brake_disc_{axle}_{side}", f"brake_pads_{axle}", f"brake_caliper_{axle}_{side}"]
    if axle == "rear" or has_front_carrier(model):
        keys.append(f"caliper_carrier_{axle}_{side}")
    keys.append(f"brake_hose_{axle}_{side}")
    if has_wear_sensor(model):
        keys.append(f"wear_sensor_{axle}_{side}")
    keys += [f"caliper_kit_{axle}", f"dust_shield_{axle}_{side}", "brake_fluid"]
    return keys


def job_parts(parts: list[Part], model: CarModel, drive: str, axle: str, side: str) -> list[Part]:
    found = []
    for key in job_keys(model, axle, side):
        matches = [p for p in parts if p.key == key and fits_vehicle(p, model, drive)]
        if len(matches) != 1:
            raise ValueError(f"{key} for {model.slug} {drive}: {len(matches)} matches")
        found.append(matches[0])
    return found
