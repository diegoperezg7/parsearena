"""Shared harness for parser runners.

Runners execute inside each parser's own isolated virtual environment, so this
file must only use the standard library. It is copied next to every runner.
"""

from __future__ import annotations

import json
import os
import signal
import subprocess
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


def descendants(pid: int) -> list[int]:
    """All processes below ``pid``, found through ``ps`` (no psutil in parser envs)."""
    try:
        out = subprocess.run(
            ["ps", "-A", "-o", "pid=,ppid="], capture_output=True, text=True, timeout=10
        ).stdout
    except (OSError, subprocess.SubprocessError):
        return []
    children: dict[int, list[int]] = {}
    for line in out.splitlines():
        parts = line.split()
        if len(parts) == 2 and parts[0].isdigit() and parts[1].isdigit():
            children.setdefault(int(parts[1]), []).append(int(parts[0]))
    found, stack = [], [pid]
    while stack:
        for child in children.get(stack.pop(), []):
            found.append(child)
            stack.append(child)
    return found


def kill_descendants(grace: float = 3.0) -> None:
    """Stop every process this runner started, including helper servers that a parser
    spawned in their own session (Marker's Surya servers do), so none outlive the run."""
    pids = descendants(os.getpid())
    for sig in (signal.SIGTERM, signal.SIGKILL):
        alive = []
        for p in pids:
            try:
                os.kill(p, sig)
                alive.append(p)
            except (ProcessLookupError, PermissionError):
                pass
        if not alive or sig == signal.SIGKILL:
            break
        deadline = time.time() + grace
        while time.time() < deadline and any(_alive(p) for p in alive):
            time.sleep(0.1)
        pids = [p for p in alive if _alive(p)]


def _alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except (ProcessLookupError, PermissionError):
        return False
    try:  # a zombie child still answers kill(0); reap it if it is ours
        done, _ = os.waitpid(pid, os.WNOHANG)
        return done == 0
    except ChildProcessError:
        return True


def run(setup, convert, version: str, device: str | None = None, teardown=None) -> None:
    """Run the parser, then always shut its helpers down (see kill_descendants)."""
    try:
        _run(setup, convert, version, device)
    finally:
        if teardown is not None:
            try:
                teardown()
            except Exception as exc:  # noqa: BLE001
                log(f"teardown failed: {type(exc).__name__}: {exc}")
        kill_descendants()


def _run(setup, convert, version: str, device: str | None = None) -> None:
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
