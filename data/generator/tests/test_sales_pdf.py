import shutil
from pathlib import Path

import pypdf

from voltrieve_data.load import load_catalog
from voltrieve_data.sales.pdf import INK, markdown_to_html, write_pdf
from voltrieve_data.sales.render import render_markdown

CATALOG = Path(__file__).parents[2] / "voltrieve.yaml"
IMAGES = Path(__file__).parents[2] / "design" / "images"
SHOTS = ("hero", "front_outdoor", "rear_outdoor", "light_detail", "interior", "charging",
         "side_studio", "practical", "master_front")
cat = load_catalog(CATALOG)
fjord = cat.by_slug("fjord")


def pdf_text(path):
    return "\n".join(page.extract_text() for page in pypdf.PdfReader(path).pages)


def full_image_set(tmp_path):
    """Every shot the brochure uses, all copies of the real master, as the worst case for size."""
    images = tmp_path / "images"
    (images / "fjord").mkdir(parents=True)
    for shot in SHOTS:
        shutil.copy(IMAGES / "fjord" / "master_front.png", images / "fjord" / f"{shot}.png")
    return images


def test_price_rows_survive_extraction(tmp_path):
    out = write_pdf(render_markdown("price_list", cat, fjord), tmp_path / "p.pdf", fjord.accent, IMAGES, False)
    lines = pdf_text(out).splitlines()
    assert any("Fjord Plus" in line and "AWD" in line and "611 000" in line for line in lines)


def test_brochure_is_landscape_and_has_pages(tmp_path):
    out = write_pdf(render_markdown("brochure", cat, fjord), tmp_path / "b.pdf", fjord.accent,
                    full_image_set(tmp_path), True)
    reader = pypdf.PdfReader(out)
    box = reader.pages[0].mediabox
    assert box.width > box.height
    assert 10 <= len(reader.pages) <= 12


def test_portrait_documents_are_portrait(tmp_path):
    out = write_pdf(render_markdown("specifications", cat, fjord), tmp_path / "s.pdf", fjord.accent, IMAGES, False)
    box = pypdf.PdfReader(out).pages[0].mediabox
    assert box.height > box.width


def test_pdf_under_10_mb(tmp_path):
    out = write_pdf(render_markdown("brochure", cat, fjord), tmp_path / "b.pdf", fjord.accent,
                    full_image_set(tmp_path), True)
    assert out.stat().st_size < 10 * 1024 * 1024


def test_missing_image_uses_placeholder(tmp_path):
    empty = tmp_path / "none"
    empty.mkdir()
    html = markdown_to_html(render_markdown("brochure", cat, fjord), fjord.accent, empty)
    assert 'class="placeholder"' in html and "fjord/hero" in html
    out = write_pdf(render_markdown("brochure", cat, fjord), tmp_path / "b.pdf", fjord.accent, empty, True)
    assert out.exists()


def test_images_are_cached_as_jpeg_next_to_the_master(tmp_path):
    images = full_image_set(tmp_path)
    markdown_to_html(render_markdown("brochure", cat, fjord), fjord.accent, images)
    cached = images / "fjord" / "hero.jpg"
    assert cached.exists()
    from PIL import Image
    with Image.open(cached) as image:
        assert image.width == 1600


def test_html_carries_accent_and_embedded_font():
    html = markdown_to_html(render_markdown("warranty", cat, None), INK, IMAGES)
    assert INK in html and "@font-face" in html and "data:font/ttf;base64," in html
    assert "file://" not in html


def test_text_is_extractable_with_swedish_letters(tmp_path):
    out = write_pdf(render_markdown("price_list", cat, fjord), tmp_path / "p.pdf", fjord.accent, IMAGES, False)
    assert "förmånsvärde" in pdf_text(out)
