"""Command line interface."""

from __future__ import annotations

import json
import sys
import time
import webbrowser
from importlib import resources
from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

from . import __version__
from .errors import UserError
from .evaluate import evaluate, timings
from .parsers import DEFAULT_PARSERS, PARSERS, env_dir, home, is_installed, missing_tools, parse_parser_list
from .pipeline import collect_docs, load_outputs, run_parser, save_outputs
from .questions import EXAMPLE, dump_questions, generate_questions, load_questions
from .retrieval import DEFAULT_EMBED_MODEL

app = typer.Typer(
    add_completion=False,
    no_args_is_help=True,
    rich_markup_mode=None,
    help="Run your PDFs through Docling, Marker, MinerU and Unstructured. "
    "Compare the output side by side and see what each one does to retrieval.",
)
console = Console(highlight=False)
err = Console(stderr=True, highlight=False)


def _version(value: bool) -> None:
    if value:
        console.print(f"parsearena {__version__}")
        raise typer.Exit()


@app.callback()
def _root(
    version: bool = typer.Option(False, "--version", callback=_version, is_eager=True, help="Show version."),
) -> None:
    pass


def _embedder(no_dense: bool, model: str):
    if no_dense:
        return None
    try:
        from .retrieval import FastEmbedder

        with console.status(f"Loading embedding model {model} (first time downloads it)..."):
            return FastEmbedder(model, cache_dir=str(home() / "models"))
    except Exception as exc:  # network errors, unknown model names
        raise UserError(
            f"Could not load the embedding model {model}: {type(exc).__name__}: {exc}"[:400],
            "Check your connection for the first download, pick another --embed-model, "
            "or use --no-dense for BM25 only.",
        ) from exc


def _analyze(
    recorded, pdf_paths, questions, out, k, no_dense, embed_model, chunk_chars, is_recorded, doc_info=None
):
    from .report import build_report

    outputs = load_outputs(recorded)
    embedder = _embedder(no_dense, embed_model)
    with console.status("Computing retrieval metrics..."):
        ev = evaluate(outputs, questions, k=k, embedder=embedder, chunk_chars=chunk_chars)
    ev["embed_model"] = embedder.name if embedder else None
    ev["questions"] = len(questions)
    tm = timings(outputs, {d["id"]: d["num_pages"] for d in recorded["docs"]})
    with console.status("Rendering pages and writing the viewer..."):
        index = build_report(out, recorded, pdf_paths, questions, ev, tm, is_recorded, doc_info)
    _print_summary(recorded, ev, tm)
    return index


def _pct(x: float) -> str:
    # Round half up, like the viewer (Math.round), so terminal and HTML agree.
    return f"{int(x * 100 + 0.5)}%"


def _print_summary(recorded, ev, tm) -> None:
    labels = {p["name"]: p["label"] for p in recorded["parsers"]}
    k = ev["k"]
    table = Table(title=None, header_style="bold", pad_edge=False)
    table.add_column("parser")
    table.add_column("survives", justify="right")
    for m in ev["methods"]:
        table.add_column(f"R@{k} {m}", justify="right")
    table.add_column("MRR " + ev["methods"][-1], justify="right")
    table.add_column("s/page", justify="right")
    table.add_column("failed", justify="right")
    has_q = ev.get("questions", 0) > 0
    for p, res in ev["parsers"].items():
        s, t = res["summary"], tm[p]
        spp = t["seconds_per_page"]
        row = [labels.get(p, p), _pct(s["survives"]) if has_q else "-"]
        row += [_pct(s[m]["recall"]) if has_q else "-" for m in ev["methods"]]
        row += [f"{s[ev['methods'][-1]]['mrr']:.2f}" if has_q else "-"]
        row += ["-" if spp is None else (f"{spp:.3f}" if spp < 0.1 else f"{spp:.1f}")]
        row += [str(len(t["failed"])) if t["failed"] else "0"]
        table.add_row(*row)
    console.print(table)
    if not has_q:
        console.print(
            "[yellow]No questions given, so retrieval metrics are empty.[/] "
            "Pass --questions FILE or --gen-questions."
        )


def _open(index: Path, no_open: bool) -> None:
    console.print(f"\nViewer: [bold]{index}[/]")
    if not no_open:
        webbrowser.open(index.resolve().as_uri())


@app.command()
def run(
    pdfs: list[Path] = typer.Argument(..., help="PDF files to parse.", show_default=False),
    parsers: str = typer.Option(
        ",".join(DEFAULT_PARSERS), "--parsers", "-p", help="Comma-separated parsers."
    ),
    questions: Path | None = typer.Option(None, "--questions", "-q", help="YAML file with questions."),
    gen_questions: bool = typer.Option(False, "--gen-questions", help="Draft questions with an LLM."),
    per_doc: int = typer.Option(5, "--per-doc", help="Questions to draft per document."),
    provider: str = typer.Option("ollama", "--provider", help="ollama, openrouter, openai or mistral."),
    model: str = typer.Option("", "--model", help="Model for --gen-questions (default depends on provider)."),
    max_cost: float = typer.Option(1.0, "--max-cost", help="Spending cap in USD for LLM calls."),
    out: Path = typer.Option(Path("parsearena-out"), "--out", "-o", help="Output directory."),
    k: int = typer.Option(5, "--k", help="k for recall@k."),
    device: str = typer.Option("auto", "--device", help="auto, cpu, mps or cuda."),
    timeout: int = typer.Option(3600, "--timeout", help="Seconds allowed per parser."),
    chunk_chars: int = typer.Option(1200, "--chunk-chars", help="Maximum characters per chunk."),
    embed_model: str = typer.Option(DEFAULT_EMBED_MODEL, "--embed-model", help="fastembed model name."),
    no_dense: bool = typer.Option(False, "--no-dense", help="BM25 only, no embeddings."),
    no_open: bool = typer.Option(False, "--no-open", help="Do not open the viewer."),
) -> None:
    """Parse PDFs with each parser in its own environment, then score retrieval."""
    specs = parse_parser_list(parsers)
    if device not in ("auto", "cpu", "mps", "cuda"):
        raise UserError(f"Unknown device: {device}", "Use auto, cpu, mps or cuda.")
    docs = collect_docs(pdfs)
    out.mkdir(parents=True, exist_ok=True)

    qs = []
    if questions:
        qs = load_questions(questions, docs)
    elif gen_questions:
        from .llm import LLM
        from .render import page_text

        llm = LLM(provider=provider, model=model, max_cost=max_cost)
        console.print(f"Drafting questions with {provider}:{llm.model}")
        texts = {d["id"]: "\n\n".join(page_text(Path(d["path"]))) for d in docs}
        qs, _, budget_err = generate_questions(llm, docs, texts, per_doc=per_doc, log=console.print)
        qpath = out / "questions.generated.yaml"
        dump_questions(
            qs, docs, qpath, header=f"# Drafted by {provider}:{llm.model}. Review before trusting."
        )
        console.print(f"Saved {len(qs)} questions to {qpath} (spent ${llm.spent:.4f})")
        if budget_err:
            raise budget_err
    else:
        console.print(
            "[yellow]No --questions or --gen-questions: only the side-by-side viewer and timings.[/]"
        )

    outputs = {}
    work = out / "work"
    for spec in specs:
        console.rule(f"{spec.label} {spec.version}")
        for hint in missing_tools(spec):
            console.print(f"[yellow]Warning:[/] {hint}")
        if not is_installed(spec):
            console.print(
                f"First use of {spec.label}: installing it in its own environment. "
                "This and the first parse can download several GB."
            )
        t0 = time.perf_counter()
        with console.status(f"Running {spec.label} on {len(docs)} PDF(s)..."):
            outputs[spec.name] = run_parser(
                spec, docs, work, device=device, timeout=timeout, log=console.print
            )
        failed = [d for d, o in outputs[spec.name].items() if not o.ok]
        status = f"[red]{len(failed)} failed[/]" if failed else "[green]ok[/]"
        console.print(f"{spec.label}: {status} in {time.perf_counter() - t0:.0f}s (log: {work / spec.name})")

    recorded = save_outputs(out / "outputs.json", docs, specs, outputs, device)
    pdf_paths = {d["id"]: Path(d["path"]) for d in docs}
    index = _analyze(recorded, pdf_paths, qs, out, k, no_dense, embed_model, chunk_chars, is_recorded=False)
    _open(index, no_open)


@app.command()
def demo(
    out: Path = typer.Option(Path("parsearena-demo"), "--out", "-o", help="Where to write the viewer."),
    k: int = typer.Option(5, "--k", help="k for recall@k."),
    no_dense: bool = typer.Option(False, "--no-dense", help="BM25 only, no embeddings download."),
    no_open: bool = typer.Option(False, "--no-open", help="Do not open the viewer."),
) -> None:
    """Recorded parser outputs on 3 public PDFs; retrieval metrics computed live."""
    base = Path(str(resources.files("parsearena") / "demo"))
    recorded = json.loads((base / "recorded.json").read_text(encoding="utf-8"))
    m = recorded["meta"]
    created = m["created"].replace("T", " ").replace("Z", " UTC")
    versions = ", ".join(f"{p['label']} {p['version']}" for p in recorded["parsers"])
    console.print(
        f"[bold]Recorded run[/] from {created} (parsearena {m['tool_version']}, {m['hardware']}).\n"
        f"Parsers: {versions}.\nParser outputs are replayed; retrieval is computed now.\n"
    )
    docs = recorded["docs"]
    qs = load_questions(base / "questions.yaml", docs)
    pdf_paths = {d["id"]: base / "pdfs" / d["file"] for d in docs}
    index = _analyze(
        recorded,
        pdf_paths,
        qs,
        out,
        k,
        no_dense,
        DEFAULT_EMBED_MODEL,
        recorded.get("chunk_chars", 1200),
        is_recorded=True,
    )
    _open(index, no_open)


@app.command("parsers")
def list_parsers() -> None:
    """List supported parsers, pinned versions, licenses and install state."""
    table = Table(header_style="bold")
    for col in ("name", "package", "license", "installed"):
        table.add_column(col)
    for spec in PARSERS.values():
        table.add_row(
            spec.name,
            " ".join(spec.packages),
            spec.license,
            str(env_dir(spec)) if is_installed(spec) else "no",
        )
    console.print(table)
    console.print(f"Environments live in {home() / 'envs'} (set PARSEARENA_HOME to move them).")


@app.command("questions-example")
def questions_example() -> None:
    """Print an example questions YAML file."""
    console.print(EXAMPLE, markup=False)


def main() -> None:
    try:
        app(standalone_mode=False)
    except UserError as exc:
        err.print(f"[bold red]Error:[/] {exc.message}", markup=True)
        if exc.hint:
            err.print(exc.hint, markup=False)
        sys.exit(1)
    except KeyboardInterrupt:
        err.print("Interrupted.")
        sys.exit(130)
    except typer.Exit as exc:
        sys.exit(exc.exit_code)
    except typer.Abort:
        sys.exit(1)
    except Exception as exc:
        import click

        if isinstance(exc, click.ClickException):
            exc.show()
            sys.exit(exc.exit_code)
        raise


if __name__ == "__main__":
    main()
