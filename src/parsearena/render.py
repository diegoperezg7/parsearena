"""Render PDF pages to images for the viewer (pypdfium2, no external tools)."""

from __future__ import annotations

from pathlib import Path

import pypdfium2 as pdfium


def render_pages(pdf_path: Path, out_dir: Path, width: int = 900) -> list[str]:
    """Write one WebP per page and return their file names (relative to out_dir)."""
    out_dir.mkdir(parents=True, exist_ok=True)
    names = []
    pdf = pdfium.PdfDocument(str(pdf_path))
    try:
        for i in range(len(pdf)):
            page = pdf[i]
            scale = width / max(page.get_width(), 1)
            image = page.render(scale=scale).to_pil().convert("RGB")
            name = f"{i + 1:03d}.webp"
            image.save(out_dir / name, "WEBP", quality=80, method=4)
            names.append(name)
            page.close()
    finally:
        pdf.close()
    return names


def page_text(pdf_path: Path) -> list[str]:
    """Text layer of every page (used only to draft questions)."""
    pdf = pdfium.PdfDocument(str(pdf_path))
    try:
        out = []
        for i in range(len(pdf)):
            tp = pdf[i].get_textpage()
            out.append(tp.get_text_range())
            tp.close()
        return out
    finally:
        pdf.close()
