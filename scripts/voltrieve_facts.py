"""Check an answer against the Voltrieve data file. Expected values come from
data/voltrieve.yaml (and the dealer's data.json for stock) at run time, never from literals.

The checks are deliberately simple string checks. They print what they expected, so a human
reads the answer next to it; a pass means "contains the right figure" or "did not invent one".
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
DATA_FILE = ROOT / "data" / "voltrieve.yaml"
DEALER_FILE = ROOT / "services" / "dealer" / "app" / "data.json"
QUESTIONS_FILE = ROOT / "tests" / "grounding" / "questions.yaml"
GENERATOR_SRC = ROOT / "data" / "generator" / "src"

# Phrases of an answer that declines to give a figure.
NEGATIVE = (
    "don't", "do not", "doesn't", "does not", "not ", "no information", "no data", "cannot",
    "can't", "unable", "isn't", "aren't", "couldn't", "unspecified",
)


def load_data() -> dict:
    return yaml.safe_load(DATA_FILE.read_text())


def load_dealer() -> dict:
    return json.loads(DEALER_FILE.read_text())


def load_catalog():
    """The generator's typed catalog: trim, color and financing prices are computed there, so the
    checks use the same rules as the documents instead of a second copy of them."""
    import sys

    if str(GENERATOR_SRC) not in sys.path:
        sys.path.insert(0, str(GENERATOR_SRC))
    from voltrieve_data.load import load_catalog as load

    return load(DATA_FILE)


def load_questions() -> list[dict]:
    return yaml.safe_load(QUESTIONS_FILE.read_text())["questions"]


def _normal(text: str) -> str:
    text = text.replace("’", "'").lower()
    # 2 100 / 2,100 / 2 100 (nbsp) -> 2100
    return re.sub(r"(?<=\d)[ ,  ](?=\d{3}(?!\d))", "", text)


def has_number(text: str, number: int) -> bool:
    return re.search(rf"(?<![\d.]){number}(?![\d])", _normal(text)) is not None


def has_decimal(text: str, value: float) -> bool:
    """4.95 matches "4.95" and "4,95"."""
    wanted = f"{value:.2f}"
    return re.search(rf"(?<![\d.,]){re.escape(wanted).replace('\\.', '[.,]')}(?!\d)", text) is not None


def _path(obj, path: str):
    for part in path.split("."):
        obj = obj[part] if isinstance(obj, dict) else getattr(obj, part)
    return obj


def declines(text: str) -> bool:
    lowered = _normal(text)
    return any(phrase in lowered for phrase in NEGATIVE)


def _short(model: dict) -> str:
    return model["name"].removeprefix("Voltrieve ").lower()


def _model(data: dict, slug: str) -> dict:
    return next(m for m in data["models"] if m["slug"] == slug)


def _mentions(text: str, model: dict) -> bool:
    return _short(model) in text.lower()


def check(expect: dict, answer: str, data: dict | None = None, dealer: dict | None = None) -> tuple[bool, str]:
    """Return (passed, what was expected)."""
    data = data or load_data()
    kind = expect["type"]
    if kind == "value":
        model = _model(data, expect["model"])
        value = model[expect["field"]]
        return has_number(answer, value), f"{model['name']} {expect['field']} = {value}"
    if kind == "best":
        candidates = [
            m for m in data["models"]
            if all(m.get(k) == v for k, v in expect.get("where", {}).items())
            and m.get(expect["field"]) is not None
        ]
        pick = max if expect["pick"] == "max" else min
        best = pick(candidates, key=lambda m: m[expect["field"]])
        value = best[expect["field"]]
        ok = _mentions(answer, best) and has_number(answer, value)
        return ok, f"{best['name']} with {expect['field']} = {value}"
    if kind == "absent":
        model = _model(data, expect["model"])
        if model[expect["field"]] is not None:
            raise ValueError(f"{model['name']} has {expect['field']} in the data; not an absent case")
        invented = re.search(r"\d[\d ,.]*\s*kg", _normal(answer)) is not None
        return declines(answer) and not invented, f"{model['name']} has no {expect['field']}: decline, no kg figure"
    if kind == "not_documented":
        listed = [t.lower() for t in data["not_documented"]]
        if expect["topic"].lower() not in listed:
            raise ValueError(f"topic {expect['topic']!r} is not in not_documented in the data file")
        lowered = _normal(answer)
        invented = any(
            re.search(rf"{re.escape(term)}\D{{0,30}}\d", lowered) for term in expect.get("terms", [])
        )
        return declines(answer) and not invented, f"not documented ({expect['topic']}): decline, no invented value"
    if kind == "cheapest_awd":
        market = expect["market"]
        surcharge = data["awd_surcharge"][market]
        options = []
        for m in data["models"]:
            if "AWD" in m["drive"]:
                # AWD-only models include it in the price, the others add the surcharge.
                options.append((m["price"][market] + (surcharge if "RWD" in m["drive"] else 0), m))
        total, model = min(options, key=lambda o: o[0])
        return _mentions(answer, model) and has_number(answer, total), f"{model['name']} AWD at {total} ({market})"
    if kind == "stock":
        dealer = dealer or load_dealer()
        count = dealer["stock"][expect["model"]][expect["city"]]
        words = {0: "no", 1: "one", 2: "two", 3: "three", 4: "four", 5: "five"}
        lowered = _normal(answer)
        ok = has_number(answer, count) or re.search(rf"\b{words.get(count, '#')}\b", lowered) is not None
        return ok, f"{expect['model']} in {expect['city']}: {count}"
    if kind in ("trim_price", "trim_adds", "pack_trims", "financing", "fields", "wheels"):
        return _check_sales(expect, answer, load_catalog())
    raise ValueError(f"unknown expectation type {kind!r}")


def _check_sales(expect: dict, answer: str, cat) -> tuple[bool, str]:
    """Checks for the sales folder content, with values from the typed catalog."""
    kind = expect["type"]
    lowered = answer.lower()
    model = cat.by_slug(expect["model"]) if "model" in expect else None
    if kind == "trim_price":
        color = next(c for c in model.colors if c.key == expect["color"])
        base = cat.trim_price(model, expect["trim"], expect["drive"], expect["market"])
        extra = cat.color_price(color, expect["market"])
        ok = has_number(answer, base + extra) or (has_number(answer, base) and has_number(answer, extra))
        return ok, f"{model.name} {expect['trim']} {expect['drive']} in {color.name}: {base} + {extra} = {base + extra}"
    if kind == "trim_adds":
        trim = next(t for t in model.trims if t.name == expect["trim"])
        # Each added item by its first two words ("keyless entry", "360 camera"), each pack by name.
        terms = [" ".join(item.lower().split()[:2]) for item in trim.adds] + [p.lower() for p in trim.includes_packs]
        words = set(re.findall(r"[a-z0-9]+", lowered))
        ok = all(set(term.split()) <= words for term in terms)
        return ok, f"{model.name} {trim.name} adds: {', '.join(terms)}"
    if kind == "pack_trims":
        included = [t.name for t in model.trims if expect["pack"] in t.includes_packs]
        others = [t.name for t in model.trims if t.name not in included]
        # A trim that does not include the pack may be named only as not having it.
        ok = all(t.lower() in lowered for t in included) and (
            declines(answer) or "option" in lowered or not any(t.lower() in lowered for t in others))
        return ok, f"{expect['pack']} pack included on {', '.join(included)}"
    if kind == "financing":
        trim, drive = cat.financing_car(model)
        x = cat.financing_example(cat.trim_price(model, trim, drive, expect["market"]), expect["market"])
        ok = has_number(answer, x.monthly) and has_decimal(answer, x.nominal_rate * 100)
        return ok, f"{x.monthly} per month at a nominal rate of {x.nominal_rate * 100:.2f} %"
    if kind == "fields":
        targets = [cat.by_slug(slug) for slug in expect.get("models", [])] or [model or cat]
        wanted = [(t, f, _path(t, f)) for t in targets for f in expect["fields"]]
        ok = all(has_number(answer, value) for _, _, value in wanted)
        if expect.get("models"):
            ok = ok and all(t.name.removeprefix("Voltrieve ").lower() in lowered for t in targets)
        return ok, ", ".join(f"{getattr(t, 'name', 'Voltrieve')} {f} = {v}" for t, f, v in wanted)
    if kind == "wheels":
        ok = all(has_number(answer, w.inches) and w.name.lower() in lowered for w in model.wheels)
        return ok, ", ".join(f"{w.inches} inch {w.name}" for w in model.wheels)
    raise ValueError(f"unknown expectation type {kind!r}")
