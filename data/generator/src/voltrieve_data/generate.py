import json
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from voltrieve_data.brochure import write_brochure
from voltrieve_data.buyers_guide import write_buyers_guide
from voltrieve_data.load import load_catalog
from voltrieve_data.parts_catalog import write_parts_documents, write_parts_index
from voltrieve_data.service_guide import write_service_guide
from voltrieve_data.spec_guide import write_spec_guide


@dataclass(frozen=True)
class GeneratedDoc:
    path: Path
    model_slug: str | None
    doc_type: Literal["brochure", "spec", "guide", "service", "parts"]
    collection: Literal["docs", "parts"] = "docs"


def generate_all(catalog_path: Path, out_dir: Path) -> list[GeneratedDoc]:
    catalog = load_catalog(catalog_path)
    out_dir.mkdir(parents=True, exist_ok=True)

    docs: list[GeneratedDoc] = []
    for model in catalog.models:
        docs.append(GeneratedDoc(write_brochure(model, catalog, out_dir), model.slug, "brochure"))
        docs.append(GeneratedDoc(write_spec_guide(model, catalog, out_dir), model.slug, "spec"))
    docs.append(GeneratedDoc(write_buyers_guide(catalog, out_dir), None, "guide"))
    docs.append(GeneratedDoc(write_service_guide(catalog, out_dir), None, "service"))
    docs += [GeneratedDoc(p, None, "parts", "parts") for p in write_parts_documents(catalog, out_dir)]
    write_parts_index(catalog, out_dir)

    manifest = [
        {
            "file": d.path.name,
            "model_slug": d.model_slug,
            "doc_type": d.doc_type,
            "collection": d.collection,
        }
        for d in docs
    ]
    (out_dir / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return docs
