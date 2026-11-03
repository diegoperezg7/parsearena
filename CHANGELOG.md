# Changelog

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
