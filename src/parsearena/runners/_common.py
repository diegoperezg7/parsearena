"""Shared harness for parser runners.

Runners execute inside each parser's own isolated virtual environment, so this
file must only use the standard library. It is copied next to every runner.
"""

from __future__ import annotations

import json
import sys
import time
import traceback


def pick_device(requested: str) -> str:
    if requested != "auto":
        return requested
    try:
        import torch

        if torch.cuda.is_available():
            return "cuda"
        mps = getattr(torch.backends, "mps", None)
        if mps is not None and mps.is_available():
            return "mps"
    except Exception:
        pass
    return "cpu"


def log(msg: str) -> None:
    print(msg, file=sys.stderr, flush=True)


def run(setup, convert, version: str, device: str | None = None) -> None:
    """Load the manifest, set the parser up once, convert every document.

    setup(device, options) -> state
    convert(state, pdf_path, num_pages) -> list[str]  (one markdown/text string per page)
    """
    with open(sys.argv[1], encoding="utf-8") as fh:
        manifest = json.load(fh)
    # A runner that does not use torch devices passes its own device label.
    device = device or pick_device(manifest.get("device", "auto"))
    log(f"device={device}")
    t0 = time.perf_counter()
    state = setup(device, manifest.get("options", {}))
    docs = manifest["docs"]
    warmup = None
    wdoc = manifest.get("warmup_doc")
    if wdoc:
        # Most parsers load models lazily (layout, tables, OCR). Convert a small
        # warm-up PDF (one text page, one image-only page) untimed, so per-page
        # timings measure parsing and not model loading.
        try:
            convert(state, wdoc["path"], wdoc["num_pages"])
        except Exception as exc:  # noqa: BLE001
            log(f"warmup failed: {type(exc).__name__}: {exc}")
        warmup = time.perf_counter() - t0
        log(f"warmup {warmup:.1f}s")
    for doc in docs:
        res: dict = {"device": device, "version": version, "warmup_seconds": warmup}
        t = time.perf_counter()
        try:
            pages = convert(state, doc["path"], doc["num_pages"])
            pages = [p or "" for p in pages][: doc["num_pages"]]
            pages += [""] * (doc["num_pages"] - len(pages))
            res.update(pages=pages, error=None)
        except Exception as exc:  # noqa: BLE001 - every failure is recorded, not raised
            res.update(
                pages=[],
                error=f"{type(exc).__name__}: {exc}"[:1000],
                traceback=traceback.format_exc()[-4000:],
            )
        res["seconds"] = time.perf_counter() - t
        with open(doc["out"], "w", encoding="utf-8") as fh:
            json.dump(res, fh, ensure_ascii=False)
        status = "failed" if res["error"] else "ok"
        log(f"{status} {doc['id']} {res['seconds']:.1f}s")
