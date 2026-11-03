"""Parser registry and isolated environments.

Every parser lives in its own uv-managed virtual environment under
``$PARSEARENA_HOME/envs`` and is driven through a small runner script in a
subprocess. parsearena never imports a parser and never bundles one.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
from dataclasses import dataclass
from importlib import resources
from pathlib import Path

from .errors import UserError


@dataclass(frozen=True)
class ParserSpec:
    name: str
    label: str
    packages: tuple[str, ...]
    runner: str
    license: str
    url: str
    python: str = "3.12"
    env: tuple[tuple[str, str], ...] = ()
    # (binary, env var that may point to it, install hint) checked before running
    tools: tuple[tuple[str, str, str], ...] = ()
    note: str = ""

    @property
    def version(self) -> str:
        return self.packages[0].split("==", 1)[1]

    @property
    def key(self) -> str:
        digest = hashlib.sha256(json.dumps([self.packages, self.python]).encode()).hexdigest()[:8]
        return f"{self.name}-{self.version}-py{self.python.replace('.', '')}-{digest}"


PARSERS: dict[str, ParserSpec] = {
    "docling": ParserSpec(
        name="docling",
        label="Docling",
        packages=("docling==2.146.0",),
        runner="run_docling.py",
        license="MIT",
        url="https://github.com/docling-project/docling",
    ),
    "marker": ParserSpec(
        name="marker",
        label="Marker",
        packages=("marker-pdf==2.1.0",),
        runner="run_marker.py",
        license="Code Apache-2.0; model weights modified OpenRAIL-M",
        url="https://github.com/datalab-to/marker",
        tools=(
            (
                "llama-server",
                "LLAMA_CPP_BINARY",
                "Marker 2.x runs its OCR model through llama.cpp when there is no NVIDIA GPU: "
                "`brew install llama.cpp`, or set LLAMA_CPP_BINARY to a llama-server binary.",
            ),
        ),
    ),
    "mineru": ParserSpec(
        name="mineru",
        label="MinerU",
        packages=("mineru==4.1.6",),
        runner="run_mineru.py",
        license="Apache-2.0 with additional terms",
        url="https://github.com/opendatalab/MinerU",
        env=(("MINERU_MODEL_SOURCE", "huggingface"), ("MINERU_TELEMETRY_DISABLED", "1")),
        note='effort "medium": local layout, OCR, table and formula models, no VLM',
    ),
    "unstructured": ParserSpec(
        name="unstructured",
        label="Unstructured",
        packages=("unstructured[pdf]==0.27.36",),
        runner="run_unstructured.py",
        license="Apache-2.0",
        url="https://github.com/Unstructured-IO/unstructured",
        tools=(
            (
                "pdftoppm",
                "",
                "Unstructured hi_res needs poppler: `brew install poppler` / `apt install poppler-utils`.",
            ),
            (
                "tesseract",
                "",
                "Unstructured hi_res needs tesseract: "
                "`brew install tesseract` / `apt install tesseract-ocr`.",
            ),
        ),
    ),
    "pypdf": ParserSpec(
        name="pypdf",
        label="pypdf (baseline)",
        packages=("pypdf==6.21.4",),
        runner="run_pypdf.py",
        license="BSD-3-Clause",
        url="https://github.com/py-pdf/pypdf",
    ),
}

DEFAULT_PARSERS = ("docling", "marker", "mineru", "unstructured", "pypdf")


def parse_parser_list(value: str) -> list[ParserSpec]:
    names = [n.strip().lower() for n in value.split(",") if n.strip()]
    if not names:
        raise UserError("No parsers selected.", f"Choose from: {', '.join(PARSERS)}")
    unknown = [n for n in names if n not in PARSERS]
    if unknown:
        raise UserError(
            f"Unknown parser: {', '.join(unknown)}",
            f"Available parsers: {', '.join(PARSERS)}",
        )
    return [PARSERS[n] for n in dict.fromkeys(names)]


def home() -> Path:
    if os.environ.get("PARSEARENA_HOME"):
        return Path(os.environ["PARSEARENA_HOME"]).expanduser()
    base = os.environ.get("XDG_CACHE_HOME") or Path.home() / ".cache"
    return Path(base) / "parsearena"


def env_dir(spec: ParserSpec) -> Path:
    return home() / "envs" / spec.key


def env_python(spec: ParserSpec) -> Path:
    d = env_dir(spec)
    return d / ("Scripts/python.exe" if sys.platform == "win32" else "bin/python")


def missing_tools(spec: ParserSpec) -> list[str]:
    """Install hints for system tools the parser needs but that are not available."""
    hints = []
    for binary, env_var, hint in spec.tools:
        configured = os.environ.get(env_var) if env_var else None
        if configured and Path(configured).exists():
            continue
        if shutil.which(binary) is None:
            hints.append(hint)
    return hints


def find_uv() -> str:
    uv = shutil.which("uv")
    if uv is None:
        raise UserError(
            "uv was not found on PATH.",
            "parsearena installs each parser in its own uv environment. "
            "Install uv: https://docs.astral.sh/uv/getting-started/installation/",
        )
    return uv


def is_installed(spec: ParserSpec) -> bool:
    return (env_dir(spec) / ".parsearena-ok").exists() and env_python(spec).exists()


def ensure_env(spec: ParserSpec, log=print) -> Path:
    """Create the parser's environment if needed and return its python."""
    if is_installed(spec):
        return env_python(spec)
    uv = find_uv()
    d = env_dir(spec)
    d.parent.mkdir(parents=True, exist_ok=True)
    log(f"Installing {spec.label} ({', '.join(spec.packages)}) into {d}")
    steps = [
        [uv, "venv", "--quiet", "--clear", "--python", spec.python, str(d)],
        [uv, "pip", "install", "--quiet", "--python", str(env_python(spec)), *spec.packages],
    ]
    for cmd in steps:
        proc = subprocess.run(cmd, capture_output=True, text=True)
        if proc.returncode != 0:
            tail = (proc.stderr or proc.stdout).strip().splitlines()[-15:]
            raise UserError(
                f"Could not install {spec.label}.",
                "uv said:\n" + "\n".join(tail),
            )
    (d / ".parsearena-ok").write_text(json.dumps({"packages": spec.packages}))
    return env_python(spec)


def runner_dir() -> Path:
    return Path(str(resources.files("parsearena") / "runners"))
