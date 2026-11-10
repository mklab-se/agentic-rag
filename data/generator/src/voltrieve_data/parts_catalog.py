"""The spare parts documents: one long Markdown catalog per area of the car.

Every row names its vehicle, because search returns chunks: a row has to make sense without
the heading above it.
"""

import json
from pathlib import Path

from voltrieve_data.model import CarModel, Catalog
from voltrieve_data.parts import AXLES, DOCUMENTS, SIDES, Part, build_parts, job_parts

HEADER = "| Article number | Part | Position | Description | Qty | Fits |"
RULE = "|---|---|---|---|---|---|"
# Listed again where a job needs them. A search for brake parts reaches the brake catalog, and
# the model left out brake fluid when it lived only among the service items.
CROSS_REFERENCES = {"voltrieve-parts-brakes.md": ("Consumables for brake work", ("brake_fluid",))}


def _row(part: Part) -> str:
    fits = ", ".join(f.name for f in part.fits)
    return (
        f"| {part.article} | {part.name} | {part.position} | {part.spec} "
        f"| {part.quantity} | {fits} |"
    )


def _fits(part: Part, model: CarModel) -> bool:
    return any(f.slug == model.slug for f in part.fits)


def write_parts_documents(catalog: Catalog, out_dir: Path) -> list[Path]:
    parts = build_parts(catalog)
    paths = []
    for file_name, (title, _, _) in DOCUMENTS.items():
        in_document = [p for p in parts if p.document == file_name]
        lines = [
            f"# Voltrieve spare parts catalog: {title.lower()}",
            "",
            "Each row gives the article number, the part, where it sits on the car, a short "
            "description, the quantity supplied and the vehicles it fits. Left and right are "
            "seen from the driver's seat. A row that names a drive, such as AWD, fits only that "
            "drive. A part shared between models has the same article number in every section.",
            "",
        ]
        for model in catalog.models:
            rows = [p for p in in_document if _fits(p, model)]
            if not rows:
                continue
            lines += [f"## {title}: {model.name}", ""]
            for system in dict.fromkeys(p.system for p in rows):
                lines += [f"### {model.name}: {system.lower()}", "", HEADER, RULE]
                lines += [_row(p) for p in rows if p.system == system]
                lines.append("")
            if file_name in CROSS_REFERENCES:
                heading, keys = CROSS_REFERENCES[file_name]
                lines += [f"### {model.name}: {heading.lower()}", "", HEADER, RULE]
                lines += [_row(p) for p in parts if p.key in keys and _fits(p, model)]
                lines.append("")
        path = out_dir / file_name
        path.write_text("\n".join(lines), encoding="utf-8")
        paths.append(path)
    return paths


def write_parts_index(catalog: Catalog, out_dir: Path) -> Path:
    """What the checks compare answers with. Not uploaded: the agent never sees this file."""
    parts = build_parts(catalog)
    jobs = {}
    for model in catalog.models:
        for drive in model.drive:
            for axle in AXLES:
                for side in SIDES:
                    jobs[f"{model.slug}/{drive}/{axle}/{side}"] = [
                        p.article for p in job_parts(parts, model, drive, axle, side)
                    ]
    path = out_dir / "parts-index.json"
    index = {
        "count": len(parts),
        "jobs": jobs,
        "parts": [
            {"article": p.article, "key": p.key, "name": p.name, "document": p.document,
             "fits": [f.name for f in p.fits], "wheels": list(p.wheels)}
            for p in parts
        ],
    }
    path.write_text(json.dumps(index, indent=2) + "\n", encoding="utf-8")
    return path
