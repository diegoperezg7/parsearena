"""Static HTML viewer: one index.html plus rendered page images."""

from __future__ import annotations

import json
import shutil
from datetime import UTC, datetime
from importlib import resources
from pathlib import Path

from .render import render_pages


def build_report(
    out_dir: Path,
    recorded: dict,
    pdf_paths: dict[str, Path],
    questions: list,
    evaluation: dict,
    timings: dict,
    is_recorded: bool,
    doc_info: dict[str, dict] | None = None,
) -> Path:
    """Write ``out_dir/index.html`` and ``out_dir/pages/<doc>/NNN.webp``."""
    out_dir.mkdir(parents=True, exist_ok=True)
    pages_root = out_dir / "pages"
    if pages_root.exists():
        shutil.rmtree(pages_root)
    docs = []
    for d in recorded["docs"]:
        names = render_pages(pdf_paths[d["id"]], pages_root / d["id"])
        info = (doc_info or {}).get(d["id"], {})
        docs.append({**d, **info, "images": [f"pages/{d['id']}/{n}" for n in names]})
    evaluation = {**evaluation, "computed": datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC")}
    data = {
        "meta": {**recorded["meta"], "recorded": is_recorded},
        "parsers": recorded["parsers"],
        "docs": docs,
        "outputs": {
            p: {d: {"pages": o["pages"], "error": o["error"]} for d, o in per.items()}
            for p, per in recorded["outputs"].items()
        },
        "questions": [{"id": q.id, "doc": q.doc, "q": q.q, "answers": q.answers} for q in questions],
        "evaluation": evaluation,
        "timings": timings,
    }
    payload = json.dumps(data, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")
    template = (resources.files("parsearena") / "report_template.html").read_text(encoding="utf-8")
    index = out_dir / "index.html"
    index.write_text(template.replace("__DATA__", payload), encoding="utf-8")
    (out_dir / "results.json").write_text(
        json.dumps(
            {k: data[k] for k in ("meta", "parsers", "evaluation", "timings")}, indent=1, ensure_ascii=False
        ),
        encoding="utf-8",
    )
    return index
