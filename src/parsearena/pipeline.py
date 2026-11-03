"""Run parsers over PDFs, one isolated subprocess per parser."""

from __future__ import annotations

import json
import os
import platform
import re
import subprocess
import time
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path

import pypdfium2 as pdfium

from . import __version__
from .errors import UserError
from .evaluate import DocOutput
from .parsers import ParserSpec, ensure_env, runner_dir


def doc_id_for(path: Path, taken: set[str]) -> str:
    base = re.sub(r"[^A-Za-z0-9._-]+", "-", path.stem).strip("-") or "doc"
    doc_id, n = base, 2
    while doc_id in taken:
        doc_id, n = f"{base}-{n}", n + 1
    taken.add(doc_id)
    return doc_id


def collect_docs(paths: list[Path]) -> list[dict]:
    docs, taken = [], set()
    for p in paths:
        if not p.exists():
            raise UserError(f"File not found: {p}")
        if p.suffix.lower() != ".pdf":
            raise UserError(f"Not a PDF: {p}", "parsearena v0.1 reads PDF files only.")
        try:
            pdf = pdfium.PdfDocument(str(p))
            n = len(pdf)
            pdf.close()
        except pdfium.PdfiumError as exc:
            raise UserError(f"Could not open {p}: {exc}") from exc
        docs.append({"id": doc_id_for(p, taken), "file": p.name, "path": str(p.resolve()), "num_pages": n})
    if not docs:
        raise UserError("No PDFs given.", "Example: parsearena run docs/*.pdf")
    return docs


def hardware() -> str:
    machine = platform.machine()
    cpu = platform.processor() or machine
    if platform.system() == "Darwin":
        try:
            cpu = (
                subprocess.run(
                    ["sysctl", "-n", "machdep.cpu.brand_string"], capture_output=True, text=True, timeout=5
                ).stdout.strip()
                or cpu
            )
            mem = int(
                subprocess.run(
                    ["sysctl", "-n", "hw.memsize"], capture_output=True, text=True, timeout=5
                ).stdout
            )
            return f"{cpu}, {round(mem / 2**30)} GB RAM, macOS {platform.mac_ver()[0]}"
        except (OSError, ValueError, subprocess.SubprocessError):
            pass
    mem = ""
    try:
        mem = f", {round(os.sysconf('SC_PAGE_SIZE') * os.sysconf('SC_PHYS_PAGES') / 2**30)} GB RAM"
    except (ValueError, OSError, AttributeError):
        pass
    return f"{cpu}{mem}, {platform.system()} {platform.release()}"


def make_warmup_pdf(src: Path, dst: Path) -> dict:
    """Two pages: the first page of ``src`` as is, and the same page as an image only."""
    source = pdfium.PdfDocument(str(src))
    out = pdfium.PdfDocument.new()
    try:
        out.import_pages(source, [0])
        page = source[0]
        w, h = page.get_size()
        bitmap = page.render(scale=150 / 72)
        image = pdfium.PdfImage.new(out)
        image.set_bitmap(bitmap)
        image.set_matrix(pdfium.PdfMatrix().scale(w, h))
        new = out.new_page(w, h)
        new.insert_obj(image)
        new.gen_content()
        out.save(str(dst))
    finally:
        source.close()
        out.close()
    return {"path": str(dst), "num_pages": 2}


def run_parser(
    spec: ParserSpec,
    docs: list[dict],
    work: Path,
    device: str = "auto",
    timeout: int = 3600,
    warmup: bool = True,
    log=print,
) -> dict[str, DocOutput]:
    python = ensure_env(spec, log=log)
    # The runner's working directory is pdir, so every path handed to it is absolute.
    pdir = work.resolve() / spec.name
    pdir.mkdir(parents=True, exist_ok=True)
    warmup_doc = make_warmup_pdf(Path(docs[0]["path"]), pdir / "warmup.pdf") if (warmup and docs) else None
    manifest = {
        "device": device,
        "warmup_doc": warmup_doc,
        "docs": [
            {
                "id": d["id"],
                "path": d["path"],
                "num_pages": d["num_pages"],
                "out": str(pdir / f"{d['id']}.json"),
            }
            for d in docs
        ],
    }
    for d in manifest["docs"]:
        Path(d["out"]).unlink(missing_ok=True)
    mpath = pdir / "manifest.json"
    mpath.write_text(json.dumps(manifest, indent=2))
    env = {**dict(spec.env), **os.environ, "PYTHONUNBUFFERED": "1", "TOKENIZERS_PARALLELISM": "false"}
    env.pop("PYTHONPATH", None)
    if device == "cpu":
        env["CUDA_VISIBLE_DEVICES"] = ""
    if device != "auto":
        env["TORCH_DEVICE"] = device
    log_path = pdir / "stderr.log"
    started = time.perf_counter()
    error = None
    with open(log_path, "w") as lf:
        try:
            proc = subprocess.run(
                [str(python), str(runner_dir() / spec.runner), str(mpath)],
                stdout=lf,
                stderr=subprocess.STDOUT,
                env=env,
                timeout=timeout,
                cwd=pdir,
            )
            if proc.returncode != 0:
                error = f"runner exited with code {proc.returncode}"
        except subprocess.TimeoutExpired:
            error = f"timed out after {timeout}s"
    wall = time.perf_counter() - started
    results: dict[str, DocOutput] = {}
    for d in manifest["docs"]:
        out = Path(d["out"])
        if out.exists():
            raw = json.loads(out.read_text())
            results[d["id"]] = DocOutput(
                pages=raw.get("pages", []),
                seconds=raw.get("seconds", 0.0),
                error=raw.get("error"),
                device=raw.get("device", ""),
                warmup_seconds=raw.get("warmup_seconds"),
                extra={"version": raw.get("version"), "wall_seconds": wall},
            )
        else:
            tail = _tail(log_path)
            results[d["id"]] = DocOutput(
                pages=[], error=f"{error or 'no output'}: {tail}"[:1500], extra={"wall_seconds": wall}
            )
    return results


def _tail(path: Path, lines: int = 6) -> str:
    try:
        text = path.read_text(errors="replace").strip().splitlines()
    except OSError:
        return ""
    return " | ".join(text[-lines:])


def save_outputs(path: Path, docs: list[dict], specs: list[ParserSpec], outputs, device: str) -> dict:
    data = {
        "meta": {
            "tool": "parsearena",
            "tool_version": __version__,
            "created": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "hardware": hardware(),
            "device_requested": device,
        },
        "parsers": [
            {
                "name": s.name,
                "label": s.label,
                "version": s.version,
                "packages": list(s.packages),
                "license": s.license,
                "url": s.url,
            }
            for s in specs
        ],
        "docs": [{k: v for k, v in d.items() if k != "path"} for d in docs],
        "outputs": {p: {d: asdict(o) for d, o in per.items()} for p, per in outputs.items()},
    }
    path.write_text(json.dumps(data, ensure_ascii=False, indent=1))
    return data


def load_outputs(data: dict) -> dict[str, dict[str, DocOutput]]:
    return {p: {d: DocOutput(**o) for d, o in per.items()} for p, per in data["outputs"].items()}
