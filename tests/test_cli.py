import json
import subprocess
import sys

import pytest

from parsearena.cli import app


def cli(*args, env=None):
    return subprocess.run(
        [sys.executable, "-m", "parsearena.cli", *args], capture_output=True, text=True, env=env
    )


def test_demo_builds_viewer_offline(tmp_path):
    out = tmp_path / "demo"
    proc = cli("demo", "--out", str(out), "--no-open", "--no-dense")
    assert proc.returncode == 0, proc.stderr
    assert "Recorded run" in proc.stdout
    html = (out / "index.html").read_text()
    assert "__DATA__" not in html and "parsearena" in html
    results = json.loads((out / "results.json").read_text())
    assert results["meta"]["recorded"] is True
    names = [p["name"] for p in results["parsers"]]
    assert "pypdf" in names
    assert set(results["evaluation"]["parsers"]) == set(names)
    pages = list((out / "pages").rglob("*.webp"))
    assert len(pages) == sum(1 for _ in pages) and pages


@pytest.mark.parametrize(
    "args, message",
    [
        (["run", "nope.pdf"], "File not found"),
        (["run", "x.pdf", "--parsers", "llamaparse"], "Unknown parser"),
    ],
)
def test_errors_are_short_and_without_traceback(args, message):
    proc = cli(*args)
    assert proc.returncode == 1
    assert message in proc.stderr
    assert "Traceback" not in proc.stderr


def test_missing_api_key_message(tmp_path):
    import os

    env = {k: v for k, v in os.environ.items() if k != "OPENROUTER_API_KEY"}
    pdf = tmp_path / "a.pdf"
    import pypdfium2 as pdfium

    doc = pdfium.PdfDocument.new()
    doc.new_page(100, 100)
    doc.save(str(pdf))
    proc = cli(
        "run",
        str(pdf),
        "--parsers",
        "pypdf",
        "--gen-questions",
        "--provider",
        "openrouter",
        "--out",
        str(tmp_path / "o"),
        "--no-open",
        env=env,
    )
    assert proc.returncode == 1
    assert "OPENROUTER_API_KEY" in proc.stderr
    assert "Traceback" not in proc.stderr


def test_version_and_help():
    proc = cli("--version")
    assert proc.returncode == 0 and "parsearena 0.1.1" in proc.stdout
    assert app.info.help.startswith("Run your PDFs")
    proc = cli("parsers")
    assert proc.returncode == 0 and "docling==2.146.0" in proc.stdout
