from pathlib import Path

from fpdf import FPDF
from fpdf.enums import XPos, YPos

from voltrieve_data.formatting import fmt_int
from voltrieve_data.pilot import pilot_features
from voltrieve_data.model import Catalog, CarModel


def _heading(pdf: FPDF, text: str) -> None:
    pdf.ln(3)
    pdf.set_font("Helvetica", "B", 13)
    pdf.cell(0, 8, text, new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    pdf.set_font("Helvetica", "", 10)


def _table(pdf: FPDF, rows: list[tuple[str, str]]) -> None:
    with pdf.table(col_widths=(60, 120), first_row_as_headings=False) as table:
        for label, value in rows:
            row = table.row()
            row.cell(label)
            row.cell(value)


def _line(pdf: FPDF, text: str) -> None:
    pdf.multi_cell(0, 6, text, new_x=XPos.LMARGIN, new_y=YPos.NEXT)


def write_spec_guide(model: CarModel, catalog: Catalog, out_dir: Path) -> Path:
    pdf = FPDF()
    pdf.set_auto_page_break(auto=True, margin=15)
    pdf.add_page()
    pdf.set_font("Helvetica", "B", 20)
    pdf.cell(0, 12, f"{model.name} specifications", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    pdf.set_font("Helvetica", "", 10)

    _heading(pdf, "Overview")
    _table(pdf, [
        ("Segment", model.segment),
        ("Platform", model.platform),
        ("System voltage", f"{model.voltage} V"),
    ])

    _heading(pdf, "Battery and range")
    _table(pdf, [
        ("Battery capacity", f"{model.battery_kwh} kWh"),
        ("Range (WLTP)", f"{model.range_km} km"),
    ])

    _heading(pdf, "Charging")
    _table(pdf, [("Peak charging power", f"{model.peak_charge_kw} kW")])
    pdf.ln(2)
    with pdf.table(col_widths=(60, 120)) as table:
        header = table.row()
        header.cell("State of charge")
        header.cell("Charge power")
        for soc, kw in model.charging_curve:
            row = table.row()
            row.cell(f"{soc} %")
            row.cell(f"{kw} kW")
    charger = [h for h in model.highlights if "onboard charger" in h]
    if charger:
        pdf.ln(2)
        _line(pdf, f"Onboard charger: {charger[0].replace(' onboard charger', '')}")

    _heading(pdf, "Towing")
    if model.towing_kg is None:
        _line(pdf, f"The {model.name} is not rated for towing.")
    else:
        _line(pdf, f"Towing capacity: {fmt_int(model.towing_kg)} kg (braked)")

    _heading(pdf, "Drive and chassis")
    _table(pdf, [("Drive", ", ".join(model.drive))])
    others = [h for h in model.highlights if "onboard charger" not in h]
    if others:
        pdf.ln(2)
        _line(pdf, "Features: " + ", ".join(others))

    _heading(pdf, "Climate")
    if model.heat_pump_standard:
        _line(pdf, "Heat pump: standard")
    else:
        _line(pdf, "Heat pump: available with the Winter pack")

    _heading(pdf, "Software")
    _line(pdf, f"Voltrieve Pilot version {model.pilot_version}")
    _line(pdf, "Features: " + ", ".join(pilot_features(model.pilot_version)))

    _heading(pdf, "Option pack availability")
    for pack in model.option_packs:
        _line(pdf, f"- {pack}")

    path = out_dir / f"voltrieve-{model.slug}-specifications.pdf"
    pdf.output(str(path))
    return path
