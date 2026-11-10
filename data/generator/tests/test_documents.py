import json
from pathlib import Path

import pypdf
import pytest

from voltrieve_data.generate import generate_all
from voltrieve_data.load import load_catalog

CATALOG = Path(__file__).parents[2] / "voltrieve.yaml"
EM_DASH = chr(0x2014)
SLUGS = ["spark", "lumen", "ragn", "fjord", "atlas"]
cat = load_catalog(CATALOG)


def pdf_text(p):
    return "\n".join(page.extract_text() for page in pypdf.PdfReader(p).pages)


@pytest.fixture(scope="module")
def out(tmp_path_factory):
    """One generator run for the whole module: printing 23 PDFs takes a while."""
    out_dir = tmp_path_factory.mktemp("generated")
    generate_all(CATALOG, out_dir)
    return out_dir


def sales(out, slug, doc):
    return out / "sales" / slug / f"voltrieve-{slug}-{doc}.pdf"


def test_generates_all_documents_and_manifest(out):
    manifest = json.loads((out / "manifest.json").read_text())
    from voltrieve_data.parts import DOCUMENTS

    assert len(manifest) == 23 + 1 + len(DOCUMENTS)  # sales folders, service guide, parts catalogs
    assert {d["doc_type"] for d in manifest} == {
        "brochure", "price_list", "specifications", "accessories", "warranty", "charging_guide",
        "buyers_guide", "service", "parts"}
    assert sum(d["collection"] == "parts" for d in manifest) == len(DOCUMENTS)
    for entry in manifest:
        assert (out / entry["file"]).exists(), entry["file"]
    sales_entries = [d for d in manifest if d["file"].startswith("sales/")]
    assert len(sales_entries) == 23 and all(d["file"].endswith(".pdf") for d in sales_entries)
    assert {d["model_slug"] for d in sales_entries if d["doc_type"] == "brochure"} == set(SLUGS)
    assert all(d["model_slug"] is None for d in sales_entries if d["file"].startswith("sales/brand/"))


def test_markdown_sits_next_to_each_sales_pdf(out):
    for pdf in (out / "sales").rglob("*.pdf"):
        assert pdf.with_suffix(".md").exists(), pdf


def test_old_word_brochures_and_spec_sheets_are_gone(out):
    assert not list(out.glob("*.docx"))
    assert not list(out.glob("voltrieve-*-specifications.pdf"))


def test_spec_pdf_has_exact_numbers(out):
    text = pdf_text(sales(out, "fjord", "specifications"))
    assert "2 100 kg" in text and "84 kWh" in text and "575 km" in text


def test_no_prices_in_brochures_or_specifications(out):
    for slug in SLUGS:
        for doc in ("brochure", "specifications"):
            text = pdf_text(sales(out, slug, doc))
            assert "SEK" not in text and "EUR" not in text, (slug, doc)


def test_prices_in_price_list_and_buyers_guide(out):
    assert "611 000" in pdf_text(sales(out, "fjord", "price-list"))
    assert "749 000 SEK" in pdf_text(out / "sales" / "brand" / "voltrieve-buyers-guide.pdf")


def test_spark_spec_says_not_rated_for_towing(out):
    assert "not rated for towing" in pdf_text(sales(out, "spark", "specifications"))


def test_no_document_mentions_undocumented_topics(out):
    texts = [pdf_text(p) for p in out.rglob("*.pdf")] + [p.read_text() for p in out.rglob("*.md")]
    for text in texts:
        for term in cat.not_documented:
            assert term.lower() not in text.lower(), term


def test_no_em_dash_in_any_document(out):
    texts = [pdf_text(p) for p in out.rglob("*.pdf")] + [p.read_text() for p in out.rglob("*.md")]
    assert all(EM_DASH not in t for t in texts)


def test_pilot_features_follow_pilot_version(out):
    assert "traffic jam assist" in pdf_text(sales(out, "ragn", "specifications"))
    assert "traffic jam assist" not in pdf_text(sales(out, "spark", "specifications"))
    assert "traffic jam assist" in pdf_text(sales(out, "ragn", "brochure"))
    for slug in SLUGS:
        for doc in ("brochure", "specifications"):
            assert "parking" not in pdf_text(sales(out, slug, doc)).lower()


def test_service_guide_says_there_is_no_engine_oil(out):
    text = (out / "voltrieve-service-guide.md").read_text(encoding="utf-8").lower()
    assert "no engine oil" in text and "reduction gear oil" in text
