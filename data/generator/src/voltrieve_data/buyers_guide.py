from pathlib import Path

from voltrieve_data.formatting import fmt_int
from voltrieve_data.model import Catalog, CarModel


def _towing(model: CarModel) -> str:
    return "not rated" if model.towing_kg is None else f"{fmt_int(model.towing_kg)} kg"


def _paragraph(model: CarModel) -> str:
    drive = " or ".join(model.drive)
    towing = (
        "It is not rated for towing, so it suits drivers who travel light."
        if model.towing_kg is None
        else f"It tows up to {fmt_int(model.towing_kg)} kg."
    )
    return (
        f"### {model.name}\n\n"
        f"{model.tagline}. Segment: {model.segment}. Platform: {model.platform}. "
        f"Drive: {drive}. Battery: {model.battery_kwh} kWh, with up to {model.range_km} km "
        f"of WLTP range. Peak charging is {model.peak_charge_kw} kW. {towing}"
    )


def write_buyers_guide(catalog: Catalog, out_dir: Path) -> Path:
    lines = [f"# {catalog.company.name} buyer's guide", "", catalog.company.tagline, ""]

    lines += ["## Model comparison", ""]
    lines += ["| Model | Battery | Range | Peak charge | Towing | Drive |",
              "|---|---|---|---|---|---|"]
    for m in catalog.models:
        lines.append(
            f"| {m.name} | {m.battery_kwh} kWh | {m.range_km} km | {m.peak_charge_kw} kW "
            f"| {_towing(m)} | {', '.join(m.drive)} |"
        )

    lines += ["", "## Prices", ""]
    for market in catalog.markets:
        c = market.currency
        lines += [f"### {market.code} ({c})", "", f"| Model | Base price | Price with AWD |", "|---|---|---|"]
        for m in catalog.models:
            awd = (
                f"{fmt_int(catalog.awd_price(m, market.code))} {c}"
                if "AWD" in m.drive
                else "not available"
            )
            lines.append(f"| {m.name} | {fmt_int(m.price[market.code])} {c} | {awd} |")
        lines.append("")
    lines += ["Where AWD is an option next to RWD, the price with AWD includes a surcharge of "
              f"{fmt_int(catalog.awd_surcharge['SE'])} SEK or "
              f"{fmt_int(catalog.awd_surcharge['EU'])} EUR.", ""]

    lines += ["## Option packs", ""]
    codes = [m.code for m in catalog.markets]
    currencies = {m.code: m.currency for m in catalog.markets}
    lines += ["| Pack | Contents | " + " | ".join(codes) + " |",
              "|---|---|" + "---|" * len(codes)]
    for name, pack in catalog.option_packs.items():
        prices = " | ".join(f"{fmt_int(pack.price[c])} {currencies[c]}" for c in codes)
        lines.append(f"| {name} | {pack.description} | {prices} |")

    lines += ["", "## Which Voltrieve is for you", ""]
    for m in catalog.models:
        lines += [_paragraph(m), ""]

    path = out_dir / "voltrieve-buyers-guide.md"
    path.write_text("\n".join(lines), encoding="utf-8")
    return path
