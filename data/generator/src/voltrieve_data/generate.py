import json
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from voltrieve_data.load import load_catalog
from voltrieve_data.parts_catalog import write_parts_documents, write_parts_index
from voltrieve_data.parts_stock import write_parts_stock
from voltrieve_data.sales.pdf import INK, write_pdf
from voltrieve_data.sales.render import BRAND_DOC_TYPES, DOC_TYPES_PER_MODEL, render_markdown
from voltrieve_data.service_guide import write_service_guide

DEFAULT_IMAGES = Path(__file__).parents[3] / "design" / "images"
DocType = Literal["brochure", "price_list", "specifications", "accessories", "warranty",
                  "charging_guide", "buyers_guide", "service", "parts"]


@dataclass(frozen=True)
class GeneratedDoc:
    path: Path
    model_slug: str | None
    doc_type: DocType
    collection: Literal["docs", "parts"] = "docs"


def _file_name(owner: str | None, doc_type: str) -> str:
    kind = doc_type.replace("_", "-")
    return f"voltrieve-{owner}-{kind}" if owner else f"voltrieve-{kind}"


def _write_sales(catalog, out_dir: Path, images_dir: Path) -> list[GeneratedDoc]:
    from playwright.sync_api import sync_playwright

    jobs = [(m, d) for m in catalog.models for d in DOC_TYPES_PER_MODEL] + [(None, d) for d in BRAND_DOC_TYPES]
    docs = []
    with sync_playwright() as p:
        browser = p.chromium.launch()
        try:
            for model, doc_type in jobs:
                folder = out_dir / "sales" / (model.slug if model else "brand")
                folder.mkdir(parents=True, exist_ok=True)
                base = folder / _file_name(model.slug if model else None, doc_type)
                md = render_markdown(doc_type, catalog, model)
                base.with_suffix(".md").write_text(md, encoding="utf-8")
                pdf = write_pdf(md, base.with_suffix(".pdf"), model.accent if model else INK, images_dir,
                                doc_type == "brochure", browser)
                docs.append(GeneratedDoc(pdf, model.slug if model else None, doc_type))
        finally:
            browser.close()
    return docs


def generate_all(
    catalog_path: Path, out_dir: Path, images_dir: Path = DEFAULT_IMAGES,
    parts_stock_path: Path | None = None,
) -> list[GeneratedDoc]:
    """With parts_stock_path, also write the dealer's parts stock there (the CLI does)."""
    catalog = load_catalog(catalog_path)
    out_dir.mkdir(parents=True, exist_ok=True)

    docs = _write_sales(catalog, out_dir, images_dir)
    docs.append(GeneratedDoc(write_service_guide(catalog, out_dir), None, "service"))
    docs += [GeneratedDoc(p, None, "parts", "parts") for p in write_parts_documents(catalog, out_dir)]
    write_parts_index(catalog, out_dir)
    if parts_stock_path is not None:
        write_parts_stock(catalog, parts_stock_path)

    manifest = [
        {
            "file": d.path.relative_to(out_dir).as_posix(),
            "model_slug": d.model_slug,
            "doc_type": d.doc_type,
            "collection": d.collection,
        }
        for d in docs
    ]
    (out_dir / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return docs
