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
        from fastembed import TextEmbedding

        self.name = model
        self._model = TextEmbedding(model_name=model, cache_dir=cache_dir)

    def embed(self, texts: Sequence[str]) -> np.ndarray:
        if not texts:
            return np.zeros((0, 1), dtype=np.float32)
        return _unit(np.array(list(self._model.passage_embed(list(texts))), dtype=np.float32))

    def embed_queries(self, texts: Sequence[str]) -> np.ndarray:
        return _unit(np.array(list(self._model.query_embed(list(texts))), dtype=np.float32))


def _unit(m: np.ndarray) -> np.ndarray:
    norms = np.linalg.norm(m, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    return m / norms


def ranking(scores: Sequence[float]) -> list[int]:
    """Indices sorted by score, best first; ties keep corpus order."""
    return sorted(range(len(scores)), key=lambda i: (-scores[i], i))


def rrf(rankings: Sequence[Sequence[int]], k: int = 60) -> list[int]:
    """Reciprocal rank fusion of several rankings over the same items."""
    fused: dict[int, float] = {}
    for r in rankings:
        for pos, idx in enumerate(r):
            fused[idx] = fused.get(idx, 0.0) + 1.0 / (k + pos + 1)
    return sorted(fused, key=lambda i: (-fused[i], i))
