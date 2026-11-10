"""Markdown to PDF: HTML with the shared stylesheet, printed by headless Chromium.

Fonts and images are embedded in the page as data URIs, so the page needs no file access.
Images are embedded as 1600 px JPEG, cached next to the PNG master: Chromium keeps JPEG data as
it is, but stores any other format losslessly, which would make a brochure far too large.
"""

import base64
import html
import re
from pathlib import Path

from markdown_it import MarkdownIt

from voltrieve_data.sales.render import PAGE_BREAK

HERE = Path(__file__).parent
INK = "#16181d"  # Voltrieve ink black, the accent of the brand documents
IMAGE_WIDTH = 1600
FONT_WEIGHTS = {"Light": (300, "normal"), "Regular": (400, "normal"), "Medium": (500, "normal"),
                "Italic": (400, "italic")}
EMBLEM = (
    '<svg class="emblem" viewBox="0 0 24 16" aria-hidden="true">'
    '<polyline points="2,2 12,14 22,2" fill="none" stroke="currentColor" stroke-width="3" '
    'stroke-linejoin="round" stroke-linecap="round"/></svg>'
)

_MD = MarkdownIt("commonmark", {"html": False}).enable("table")
_IMG = re.compile(r'<p>\s*<img src="([^"]+)" alt="([^"]*)"\s*/?>\s*</p>')


def _fonts_css() -> str:
    faces = []
    for style, (weight, slant) in FONT_WEIGHTS.items():
        data = base64.b64encode((HERE / "fonts" / f"HankenGrotesk-{style}.ttf").read_bytes()).decode()
        faces.append(
            "@font-face { font-family: 'Hanken Grotesk'; "
            f"src: url(data:font/ttf;base64,{data}) format('truetype'); "
            f"font-weight: {weight}; font-style: {slant}; }}"
        )
    return "\n".join(faces)


def _cached_jpeg(png: Path) -> Path:
    jpg = png.with_suffix(".jpg")
    if not jpg.exists() or jpg.stat().st_mtime < png.stat().st_mtime:
        from PIL import Image

        with Image.open(png) as image:
            rgb = image.convert("RGB")
            height = round(rgb.height * IMAGE_WIDTH / rgb.width)
            rgb.resize((IMAGE_WIDTH, height), Image.LANCZOS).save(
                jpg, "JPEG", quality=84, optimize=True, progressive=True
            )
    return jpg


def _figure(ref: str, alt: str, images_dir: Path) -> str:
    png = images_dir / ref
    if not png.exists():
        label = html.escape(ref.removesuffix(".png"))
        return f'<figure class="placeholder"><span>Image: {label}</span></figure>'
    data = base64.b64encode(_cached_jpeg(png).read_bytes()).decode()
    return f'<figure><img src="data:image/jpeg;base64,{data}" alt="{alt}"></figure>'


def _section(md: str, images_dir: Path, index: int, brochure: bool) -> str:
    body = _MD.render(md)
    figures = [_figure(ref, alt, images_dir) for ref, alt in _IMG.findall(body)]
    text = _IMG.sub("", body)
    if not brochure:
        return f'<section class="flow">{text.replace("</h1>", "</h1>" + "".join(figures[:1]), 1)}' \
               f'{"".join(figures[1:])}</section>'
    if index == 0:
        return f'<section class="page cover">{"".join(figures[:1])}<div class="cover-text">{text}</div></section>'
    kind = ("text-only", "one-image", "two-images")[len(figures)] if len(figures) < 3 else "many-images"
    if text.count("<h3>") >= 3:
        kind += " three-columns"
    return (
        f'<section class="page {kind}"><div class="text">{text}</div>'
        f'<div class="media">{"".join(figures)}</div></section>'
    )


def markdown_to_html(md: str, accent: str, images_dir: Path, landscape: bool = False) -> str:
    sections = md.split(PAGE_BREAK)
    body = "".join(_section(s, images_dir, i, landscape) for i, s in enumerate(sections))
    css = (HERE / "style.css").read_text(encoding="utf-8")
    kind = "brochure" if landscape else "document"
    return (
        '<!doctype html><html lang="en"><head><meta charset="utf-8">'
        f"<style>{_fonts_css()}\n:root {{ --accent: {accent}; }}\n{css}</style></head>"
        f'<body class="{kind}"><header class="brand">{EMBLEM}<span>VOLTRIEVE</span></header>'
        f"{body}</body></html>"
    )


def _title(md: str) -> str:
    first = next((line for line in md.splitlines() if line.startswith("# ")), "# Voltrieve")
    return html.escape(first[2:].strip())


def write_pdf(md: str, out: Path, accent: str, images_dir: Path, landscape: bool) -> Path:
    from playwright.sync_api import sync_playwright

    out.parent.mkdir(parents=True, exist_ok=True)
    page_html = markdown_to_html(md, accent, images_dir, landscape)
    footer = (
        '<div style="font-family: Helvetica, Arial, sans-serif; font-size: 7px; color: #6b7078; '
        'width: 100%; padding: 0 14mm; display: flex; justify-content: space-between;">'
        f"<span>Voltrieve | {_title(md)}</span>"
        '<span><span class="pageNumber"></span> / <span class="totalPages"></span></span></div>'
    )
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()
        page.set_content(page_html, wait_until="load")
        if landscape:
            page.pdf(path=str(out), format="A4", landscape=True, print_background=True,
                     margin={"top": "0", "bottom": "0", "left": "0", "right": "0"})
        else:
            page.pdf(path=str(out), format="A4", print_background=True,
                     display_header_footer=True, header_template="<span></span>",
                     footer_template=footer,
                     margin={"top": "14mm", "bottom": "16mm", "left": "14mm", "right": "14mm"})
        browser.close()
    return out
