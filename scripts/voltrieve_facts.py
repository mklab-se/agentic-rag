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

# Phrases of an answer that declines to give a figure.
NEGATIVE = (
    "don't", "do not", "doesn't", "does not", "not ", "no information", "no data", "cannot",
    "can't", "unable", "isn't", "aren't", "couldn't", "unspecified",
)


def load_data() -> dict:
    return yaml.safe_load(DATA_FILE.read_text())


def load_dealer() -> dict:
    return json.loads(DEALER_FILE.read_text())


def load_questions() -> list[dict]:
    return yaml.safe_load(QUESTIONS_FILE.read_text())["questions"]


def _normal(text: str) -> str:
    # Foundry citation markers such as 【5:0†file.pdf】 are not part of the answer.
    text = re.sub(r"【[^】]*】", " ", text)
    text = text.replace("’", "'").lower()
    # 2 100 / 2,100 / 2 100 (nbsp) -> 2100
    return re.sub(r"(?<=\d)[ ,  ](?=\d{3}(?!\d))", "", text)


def has_number(text: str, number: int) -> bool:
    return re.search(rf"(?<![\d.]){number}(?![\d])", _normal(text)) is not None


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
    raise ValueError(f"unknown expectation type {kind!r}")
