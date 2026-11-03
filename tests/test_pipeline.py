import shutil
import sys
from pathlib import Path

import pypdfium2 as pdfium
import pytest

from parsearena import parsers as parsers_mod
from parsearena import pipeline
from parsearena.errors import UserError
from parsearena.parsers import ParserSpec, parse_parser_list

FIX = Path(__file__).parent / "fixtures"


def make_pdf(path: Path, pages: int = 2) -> Path:
    pdf = pdfium.PdfDocument.new()
    for _ in range(pages):
        pdf.new_page(200, 200)
    pdf.save(str(path))
    return path


@pytest.fixture
def fake_runner(tmp_path, monkeypatch):
    rdir = tmp_path / "runners"
    rdir.mkdir()
    shutil.copy(parsers_mod.runner_dir() / "_common.py", rdir)
    shutil.copy(FIX / "run_fake.py", rdir)
    monkeypatch.setattr(pipeline, "runner_dir", lambda: rdir)
    monkeypatch.setattr(pipeline, "ensure_env", lambda spec, log=print: Path(sys.executable))
    return ParserSpec(
        name="fake", label="Fake", packages=("fake==0.0",), runner="run_fake.py", license="MIT", url=""
    )


def test_collect_docs_counts_pages_and_dedupes_ids(tmp_path):
    a = make_pdf(tmp_path / "a b.pdf", 3)
    (tmp_path / "x").mkdir()
    b = make_pdf(tmp_path / "x" / "a b.pdf", 1)
    docs = pipeline.collect_docs([a, b])
    assert [d["id"] for d in docs] == ["a-b", "a-b-2"]
    assert [d["num_pages"] for d in docs] == [3, 1]


def test_collect_docs_errors(tmp_path):
    with pytest.raises(UserError, match="not found"):
        pipeline.collect_docs([tmp_path / "missing.pdf"])
    txt = tmp_path / "notes.txt"
    txt.write_text("hi")
    with pytest.raises(UserError, match="Not a PDF"):
        pipeline.collect_docs([txt])
    broken = tmp_path / "broken.pdf"
    broken.write_text("not really a pdf")
    with pytest.raises(UserError, match="Could not open"):
        pipeline.collect_docs([broken])


def test_parse_parser_list():
    assert [s.name for s in parse_parser_list("pypdf, docling,pypdf")] == ["pypdf", "docling"]
    with pytest.raises(UserError, match="Unknown parser"):
        parse_parser_list("pypdf,llamaparse")


def test_run_parser_records_outputs_and_failures(tmp_path, fake_runner):
    docs = pipeline.collect_docs([make_pdf(tmp_path / "good.pdf", 2), make_pdf(tmp_path / "bad.pdf", 1)])
    res = pipeline.run_parser(fake_runner, docs, tmp_path / "work", device="cpu")
    assert res["good"].pages == ["page 1 of good.pdf", "page 2 of good.pdf"]
    assert res["good"].ok and res["good"].device == "cpu"
    assert res["good"].warmup_seconds is not None
    assert not res["bad"].ok and "cannot read this one" in res["bad"].error


def test_runner_crash_is_recorded_not_raised(tmp_path, fake_runner, monkeypatch):
    monkeypatch.setenv("FAKE_MODE", "crash")
    docs = pipeline.collect_docs([make_pdf(tmp_path / "good.pdf", 1)])
    res = pipeline.run_parser(fake_runner, docs, tmp_path / "work", warmup=False)
    assert "exited with code 3" in res["good"].error


def test_runner_timeout_is_recorded(tmp_path, fake_runner, monkeypatch):
    monkeypatch.setenv("FAKE_MODE", "hang")
    docs = pipeline.collect_docs([make_pdf(tmp_path / "good.pdf", 1)])
    res = pipeline.run_parser(fake_runner, docs, tmp_path / "work", timeout=2, warmup=False)
    assert "timed out after 2s" in res["good"].error


def test_save_and_load_outputs_roundtrip(tmp_path, fake_runner):
    docs = pipeline.collect_docs([make_pdf(tmp_path / "good.pdf", 1)])
    res = pipeline.run_parser(fake_runner, docs, tmp_path / "work")
    data = pipeline.save_outputs(tmp_path / "outputs.json", docs, [fake_runner], {"fake": res}, "auto")
    assert "path" not in data["docs"][0]
    assert pipeline.load_outputs(data)["fake"]["good"].pages == ["page 1 of good.pdf"]


def test_env_keys_change_with_pins():
    a = ParserSpec(name="x", label="X", packages=("x==1.0",), runner="r.py", license="", url="")
    b = ParserSpec(name="x", label="X", packages=("x==1.1",), runner="r.py", license="", url="")
    assert a.key != b.key and a.version == "1.0"


def test_missing_uv_is_user_error(monkeypatch):
    monkeypatch.setattr(parsers_mod.shutil, "which", lambda name: None)
    with pytest.raises(UserError, match="uv was not found"):
        parsers_mod.ensure_env(parsers_mod.PARSERS["pypdf"])


@pytest.mark.skipif(shutil.which("uv") is None, reason="needs uv")
def test_real_pypdf_baseline_in_isolated_env(tmp_path):
    """Installs pypdf into its own uv environment and parses a real PDF (light: no models)."""
    src = Path(__file__).parents[1] / "src/parsearena/demo/pdfs/dpo-arxiv-2305.18290.pdf"
    docs = pipeline.collect_docs([src])
    res = pipeline.run_parser(parsers_mod.PARSERS["pypdf"], docs, tmp_path / "work", log=lambda m: None)
    out = res["dpo-arxiv-2305.18290"]
    assert out.ok, out.error
    assert "Direct Preference Optimization" in out.pages[0]


def test_relative_work_dir(tmp_path, fake_runner, monkeypatch):
    monkeypatch.chdir(tmp_path)
    docs = pipeline.collect_docs([make_pdf(tmp_path / "good.pdf", 1)])
    res = pipeline.run_parser(fake_runner, docs, Path("rel/work"))
    assert res["good"].ok, res["good"].error
