"""MinerU local analysis at effort "medium" (layout, OCR, tables, formulas; no VLM).

MinerU's "high"/"xhigh" efforts route pages through a vision-language model,
which is out of scope for parsearena v0.1.
"""

import os
from importlib.metadata import version

from _common import run

os.environ.setdefault("MINERU_TELEMETRY_DISABLED", "1")


def setup(device, options):
    if device != "auto":
        os.environ.setdefault("MINERU_DEVICE_MODE", device)
    from mineru.backend.analyze import doc_analyze
    from mineru.render.content_list import render_content_list

    return doc_analyze, render_content_list


def _render(item) -> str:
    kind = item.get("type")
    if kind == "table":
        parts = [*item.get("table_caption", []), item.get("table_body", ""), *item.get("table_footnote", [])]
        return "\n\n".join(p for p in parts if p)
    if kind in ("image", "chart"):
        parts = [
            *item.get("image_caption", []),
            *item.get("chart_caption", []),
            *item.get("image_footnote", []),
        ]
        return "\n\n".join(p for p in parts if p)
    if kind == "list":
        return "\n".join(f"- {x}" for x in item.get("list_items", []))
    text = item.get("text", "") or ""
    level = item.get("text_level")
    if kind == "text" and level:
        return "#" * min(int(level) + 1, 6) + " " + text
    return text


def convert(state, path, num_pages):
    doc_analyze, render_content_list = state
    with open(path, "rb") as fh:
        middle_json, _ = doc_analyze(fh.read(), effort="medium")
    pages = [[] for _ in range(num_pages)]
    for item in render_content_list(middle_json):
        idx = item.get("page_idx", 0)
        text = _render(item).strip()
        if text and 0 <= idx < num_pages:
            pages[idx].append(text)
    return ["\n\n".join(p) for p in pages]


if __name__ == "__main__":
    run(setup, convert, version("mineru"))
