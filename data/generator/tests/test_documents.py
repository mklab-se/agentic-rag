import json
from pathlib import Path

import docx
import pypdf

from voltrieve_data.generate import generate_all
from voltrieve_data.load import load_catalog

CATALOG = Path(__file__).parents[2] / "voltrieve.yaml"
EM_DASH = chr(0x2014)


def docx_text(p):
    return "\n".join(par.text for par in docx.Document(p).paragraphs)


def pdf_text(p):
    return "\n".join(page.extract_text() for page in pypdf.PdfReader(p).pages)


def test_generates_all_documents_and_manifest(tmp_path):
    docs = generate_all(CATALOG, tmp_path)
    assert len(docs) == 17
    manifest = json.loads((tmp_path / "manifest.json").read_text())
    assert {d["doc_type"] for d in manifest} == {"brochure", "spec", "guide", "service", "parts"}
    assert sum(d["collection"] == "parts" for d in manifest) == 5
    assert sum(d["collection"] == "docs" for d in manifest) == 12


def test_spec_guide_has_exact_numbers(tmp_path):
    generate_all(CATALOG, tmp_path)
    text = pdf_text(tmp_path / "voltrieve-fjord-specifications.pdf")
    assert "2 100 kg" in text and "84 kWh" in text and "575 km" in text


def test_brochure_sells_without_towing_or_price_numbers(tmp_path):
    generate_all(CATALOG, tmp_path)
    text = docx_text(tmp_path / "voltrieve-fjord-brochure.docx")
    assert "Room for the whole weekend" in text
    assert "2 100 kg" not in text and "SEK" not in text


def test_spark_spec_says_not_rated_for_towing(tmp_path):
    generate_all(CATALOG, tmp_path)
    assert "not rated for towing" in pdf_text(tmp_path / "voltrieve-spark-specifications.pdf")


def test_prices_only_in_buyers_guide(tmp_path):
    generate_all(CATALOG, tmp_path)
    guide = (tmp_path / "voltrieve-buyers-guide.md").read_text()
    assert "749 000 SEK" in guide and "67 900 EUR" in guide
    for slug in ["spark", "lumen", "ragn", "fjord", "atlas"]:
        assert "SEK" not in pdf_text(tmp_path / f"voltrieve-{slug}-specifications.pdf")


def test_no_document_mentions_undocumented_topics(tmp_path):
    generate_all(CATALOG, tmp_path)
    cat = load_catalog(CATALOG)
    blobs = [docx_text(p) for p in tmp_path.glob("*.docx")] + \
            [pdf_text(p) for p in tmp_path.glob("*.pdf")] + \
            [(tmp_path / "voltrieve-buyers-guide.md").read_text()]
    for text in blobs:
        for term in cat.not_documented:
            assert term.lower() not in text.lower()


def test_no_em_dash_in_any_document(tmp_path):
    generate_all(CATALOG, tmp_path)
    texts = [docx_text(p) for p in tmp_path.glob("*.docx")] + \
            [pdf_text(p) for p in tmp_path.glob("*.pdf")] + \
            [p.read_text() for p in tmp_path.glob("*.md")]
    assert all(EM_DASH not in t for t in texts)


def test_pilot_features_follow_pilot_version(tmp_path):
    generate_all(CATALOG, tmp_path)
    assert "traffic jam assist" in pdf_text(tmp_path / "voltrieve-ragn-specifications.pdf")
    assert "traffic jam assist" not in pdf_text(tmp_path / "voltrieve-spark-specifications.pdf")
    assert "traffic jam assist" in docx_text(tmp_path / "voltrieve-ragn-brochure.docx")
    for p in list(tmp_path.glob("*.docx")) + list(tmp_path.glob("*.pdf")):
        text = docx_text(p) if p.suffix == ".docx" else pdf_text(p)
        assert "parking" not in text.lower()
