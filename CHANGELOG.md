# Changelog

## [0.1.3] - 2026-11-03

### Fixed
- Parser helper processes no longer outlive a run. Marker 2.x starts Surya inference servers
  (layout, OCR error, llama.cpp) in their own sessions, and they kept running after `parsearena run`
  finished. Runners now call Marker's `shutdown_models()` and stop every descendant process on exit,
  and `run` stops the runner's whole process tree on timeouts and crashes.

## [0.1.2] - 2026-11-03

### Added
- `src/parsearena/demo/pdfs/NOTICE.md` with title, authors, source, license and changes for each
  bundled demo PDF, including the full CC BY 4.0 attribution for the DPO paper. It ships in the wheel.
- README section "Third-party documents" (EN/ES) pointing to it.

### Changed
- The default Mistral model for `--gen-questions` is now `ministral-8b-latest` (was `mistral-small-latest`).
- README notes the live `--gen-questions` tests with `ministral-8b-latest`.

## [0.1.1] - 2026-11-03

### Fixed
- Hybrid retrieval: BM25 chunks with a score of 0 no longer take part in the fusion with a position
  taken from their place in the corpus, and tied scores now share a rank. Recall@5 of the demo is
  unchanged; some MRR values move by 0.02 to 0.03.
- `--gen-questions`: a timeout is reported as a timeout, not as an unreachable server
  (`PARSEARENA_LLM_TIMEOUT` sets the limit).

### Changed
- Embeddings are cached on disk by model and text hash: a second `parsearena demo` takes about 2 s
  instead of about 40 s on a busy machine.
- The first download of the embedding model prints one line instead of Hugging Face progress bars
  and warnings.
- README and viewer explain why hybrid can score below BM25 and dense, and give the real first-run
  time of the quickstart.

## [0.1.0] - 2026-11-03

First release.

- `parsearena run`: Docling 2.146.0, Marker 2.1.0, MinerU 4.1.6, Unstructured 0.27.36 and a pypdf 6.21.4
  baseline, each in its own uv environment, run as a subprocess with pinned versions.
- Per-page outputs, time per page (model loading reported apart as warm-up) and failures.
- One chunker for every output; retrieval with BM25, local fastembed embeddings and their fusion:
  answer survives parsing, recall@k and MRR.
- Questions from a YAML file or drafted with an LLM (`--gen-questions`, Ollama, OpenRouter, OpenAI or
  Mistral) with a `--max-cost` cap.
- Static HTML viewer: page image next to any two parser outputs, metrics, timings and failures,
  English and Spanish, light and dark.
- `parsearena demo`: recorded outputs on three public PDFs, retrieval computed live.
