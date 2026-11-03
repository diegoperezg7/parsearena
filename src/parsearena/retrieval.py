"""Retrieval over parser outputs: BM25, local dense embeddings and their fusion."""

from __future__ import annotations

import math
from collections import Counter
from collections.abc import Sequence
from typing import Protocol

import numpy as np

from .text import tokenize

DEFAULT_EMBED_MODEL = "BAAI/bge-small-en-v1.5"


class BM25:
    """Okapi BM25 (k1=1.5, b=0.75) over pre-tokenized documents."""

    def __init__(self, docs: Sequence[str], k1: float = 1.5, b: float = 0.75) -> None:
        self.k1, self.b = k1, b
        self.tfs = [Counter(tokenize(d)) for d in docs]
        self.lens = [sum(tf.values()) for tf in self.tfs]
        self.avg = (sum(self.lens) / len(self.lens)) if self.lens else 0.0
        df: Counter[str] = Counter()
        for tf in self.tfs:
            df.update(tf.keys())
        n = len(docs)
        self.idf = {t: math.log(1 + (n - f + 0.5) / (f + 0.5)) for t, f in df.items()}

    def scores(self, query: str) -> list[float]:
        terms = tokenize(query)
        out = []
        for tf, length in zip(self.tfs, self.lens, strict=True):
            s = 0.0
            denom_base = self.k1 * (1 - self.b + self.b * length / self.avg) if self.avg else self.k1
            for t in terms:
                f = tf.get(t)
                if f:
                    s += self.idf[t] * f * (self.k1 + 1) / (f + denom_base)
            out.append(s)
        return out


class Embedder(Protocol):
    name: str

    def embed(self, texts: Sequence[str]) -> np.ndarray: ...

    def embed_queries(self, texts: Sequence[str]) -> np.ndarray: ...


class FastEmbedder:
    """Local ONNX embeddings through fastembed. No torch, no network after the first download."""

    def __init__(self, model: str = DEFAULT_EMBED_MODEL, cache_dir: str | None = None) -> None:
        quiet_hf_hub()
        from fastembed import TextEmbedding

        self.name = model
        self._model = TextEmbedding(model_name=model, cache_dir=cache_dir)
        self._store = VectorCache(cache_dir, model) if cache_dir else None

    def _cached(self, kind: str, texts: Sequence[str], fn) -> np.ndarray:
        if self._store is None:
            return _unit(np.array(list(fn(list(texts))), dtype=np.float32))
        keys = [self._store.key(kind, t) for t in texts]
        missing = [t for k, t in zip(keys, texts, strict=True) if k not in self._store]
        if missing:
            vecs = _unit(np.array(list(fn(list(dict.fromkeys(missing)))), dtype=np.float32))
            for t, v in zip(dict.fromkeys(missing), vecs, strict=True):
                self._store.put(self._store.key(kind, t), v)
            self._store.save()
        return np.stack([self._store.get(k) for k in keys])

    def embed(self, texts: Sequence[str]) -> np.ndarray:
        if not texts:
            return np.zeros((0, 1), dtype=np.float32)
        return self._cached("p", texts, self._model.passage_embed)

    def embed_queries(self, texts: Sequence[str]) -> np.ndarray:
        return self._cached("q", texts, self._model.query_embed)


class VectorCache:
    """Embeddings already computed, keyed by model and text hash, in one .npz per model.

    The first run computes every vector; later runs over the same text reuse them.
    """

    def __init__(self, cache_dir: str, model: str) -> None:
        from pathlib import Path

        slug = "".join(c if c.isalnum() else "-" for c in model)
        self.path = Path(cache_dir) / "vectors" / f"{slug}.npz"
        self._data: dict[str, np.ndarray] = {}
        self._dirty = False
        if self.path.exists():
            try:
                with np.load(self.path) as f:
                    self._data = {k: f[k] for k in f.files}
            except (OSError, ValueError):
                self._data = {}

    @staticmethod
    def key(kind: str, text: str) -> str:
        import hashlib

        return kind + hashlib.sha256(text.encode("utf-8")).hexdigest()[:32]

    def __contains__(self, key: str) -> bool:
        return key in self._data

    def get(self, key: str) -> np.ndarray:
        return self._data[key]

    def put(self, key: str, vec: np.ndarray) -> None:
        self._data[key] = vec
        self._dirty = True

    def save(self) -> None:
        if not self._dirty:
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp.npz")
        np.savez(tmp, **self._data)
        tmp.replace(self.path)
        self._dirty = False


def quiet_hf_hub() -> None:
    """Silence Hugging Face Hub progress bars and warnings; the CLI prints its own line."""
    import logging
    import os
    import warnings

    os.environ.setdefault("HF_HUB_DISABLE_PROGRESS_BARS", "1")
    os.environ.setdefault("HF_HUB_VERBOSITY", "error")
    os.environ.setdefault("HF_HUB_DISABLE_TELEMETRY", "1")
    os.environ.setdefault("TQDM_DISABLE", "1")
    logging.getLogger("huggingface_hub").setLevel(logging.ERROR)
    warnings.filterwarnings("ignore", module="huggingface_hub")
    try:
        from huggingface_hub.utils import disable_progress_bars
        from huggingface_hub.utils import logging as hf_logging

        disable_progress_bars()
        hf_logging.set_verbosity_error()
    except Exception:  # noqa: BLE001 - only cosmetic
        pass
    try:
        from loguru import logger

        logger.disable("fastembed")
    except Exception:  # noqa: BLE001
        pass


def model_is_cached(model: str, cache_dir: str) -> bool:
    from pathlib import Path

    key = model.split("/")[-1].lower()
    root = Path(cache_dir)
    return root.exists() and any(key in p.name.lower() for p in root.iterdir() if p.is_dir())


def _unit(m: np.ndarray) -> np.ndarray:
    norms = np.linalg.norm(m, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    return m / norms


def score_ranks(scores: Sequence[float], drop_zero: bool = False) -> dict[int, int]:
    """Rank of each item, best = 1. Tied scores share a rank (1, 2, 2, 4).

    With ``drop_zero`` items scoring 0 are left out: for BM25 a zero score means
    the chunk shares no term with the query, so it was not retrieved at all and
    must not get a position (or a share of a fusion) from its place in the corpus.
    """
    items = [(i, s) for i, s in enumerate(scores) if not (drop_zero and s <= 0)]
    items.sort(key=lambda t: -t[1])
    ranks: dict[int, int] = {}
    prev, rank = None, 0
    for pos, (i, s) in enumerate(items, start=1):
        if s != prev:
            rank, prev = pos, s
        ranks[i] = rank
    return ranks


def rrf(rank_maps: Sequence[dict[int, int]], k: int = 60) -> dict[int, float]:
    """Reciprocal rank fusion: sum of 1 / (k + rank) over the lists an item appears in."""
    fused: dict[int, float] = {}
    for ranks in rank_maps:
        for idx, rank in ranks.items():
            fused[idx] = fused.get(idx, 0.0) + 1.0 / (k + rank)
    return fused
