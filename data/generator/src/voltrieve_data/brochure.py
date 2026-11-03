from pathlib import Path

import docx

from voltrieve_data.model import Catalog, CarModel


def _marketing_highlights(model: CarModel) -> list[str]:
    # Brochures sell the experience: charger ratings belong in the specification guide.
    return [h for h in model.highlights if "onboard charger" not in h]


def write_brochure(model: CarModel, catalog: Catalog, out_dir: Path) -> Path:
    doc = docx.Document()
    doc.add_heading(model.name, level=0)
    doc.add_paragraph(model.tagline, style="Subtitle")

    highlights = _marketing_highlights(model)
    drive = " or ".join(model.drive)

    doc.add_heading("Meet the " + model.name, level=1)
    doc.add_paragraph(
        f"The {model.name} is a {model.segment} with {drive} drive, designed around "
        f"everyday life. {model.tagline}: that is the idea behind every detail."
    )
    doc.add_paragraph(
        f"Look closer and you find what makes it special: {', '.join(highlights[:-1])} "
        f"and {highlights[-1]}. Small touches that you notice on the first drive "
        f"and appreciate on the thousandth."
    )
    doc.add_paragraph(
        f"Built on the Voltrieve {model.platform} platform, the {model.name} feels calm, "
        f"quick and confident, whether you are crossing town or heading out of it."
    )

    doc.add_heading("Voltrieve Pilot", level=1)
    doc.add_paragraph(
        f"The {model.name} comes with Voltrieve Pilot version {model.pilot_version}, "
        f"our driver assistance suite. It keeps you centred in your lane, adapts your "
        f"speed to traffic and helps you park with confidence."
    )

    doc.add_heading("Option packs", level=1)
    for pack in model.option_packs:
        doc.add_paragraph(
            f"{pack}: {catalog.option_packs[pack].description}", style="List Bullet"
        )

    doc.add_paragraph(f"Range up to {model.range_km} km (WLTP)")

    path = out_dir / f"voltrieve-{model.slug}-brochure.docx"
    doc.save(path)
    return path
