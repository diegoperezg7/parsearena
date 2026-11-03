"""Turn parser outputs plus a question set into retrieval metrics."""

from __future__ import annotations

from dataclasses import dataclass, field

from .retrieval import BM25, Embedder, rrf, score_ranks
from .text import chunk_text, contains, normalize

MRR_CUTOFF = 10


@dataclass
class Question:
    id: str
    doc: str
    q: str
    answers: list[str]


@dataclass
class DocOutput:
    pages: list[str]
    seconds: float = 0.0
    error: str | None = None
    device: str = ""
    warmup_seconds: float | None = None
    extra: dict = field(default_factory=dict)

    @property
    def text(self) -> str:
        return "\n\n".join(self.pages)

    @property
    def ok(self) -> bool:
        return self.error is None


def _first_hit(ranks: dict[int, int], relevant: set[int]) -> int | None:
    hits = [ranks[i] for i in relevant if i in ranks]
    return min(hits) if hits else None


def evaluate(
    outputs: dict[str, dict[str, DocOutput]],
    questions: list[Question],
    k: int = 5,
    embedder: Embedder | None = None,
    chunk_chars: int = 1200,
    progress=None,
) -> dict:
    """Score every parser on every question.

    Retrieval runs over the chunks of *all* documents produced by one parser, so
    a question can be answered from the wrong document. A chunk is relevant when
    it belongs to the question's document and contains one of the answers.
    """
    methods = ["bm25"] + (["dense", "hybrid"] if embedder is not None else [])
    q_vecs = embedder.embed_queries([q.q for q in questions]) if (embedder and questions) else None
    result: dict[str, dict] = {}
    for parser, docs in outputs.items():
        if progress:
            progress(parser)
        chunks = []
        for doc_id, out in docs.items():
            if out.ok:
                chunks.extend(chunk_text(doc_id, out.text, chunk_chars))
        texts = [c.text for c in chunks]
        norm_chunks = [normalize(t) for t in texts]
        norm_docs = {d: normalize(o.text) for d, o in docs.items() if o.ok}
        bm25 = BM25(texts) if texts else None
        c_vecs = embedder.embed(texts) if (embedder and texts) else None
        per_q = []
        for qi, q in enumerate(questions):
            survives = any(contains(norm_docs.get(q.doc, ""), a) for a in q.answers)
            relevant = {
                i
                for i, c in enumerate(chunks)
                if c.doc == q.doc and any(contains(norm_chunks[i], a) for a in q.answers)
            }
            ranks: dict[str, int | None] = {}
            if texts:
                orders = {"bm25": score_ranks(bm25.scores(q.q), drop_zero=True)}
                if c_vecs is not None and q_vecs is not None:
                    orders["dense"] = score_ranks((c_vecs @ q_vecs[qi]).tolist())
                    fused = rrf([orders["bm25"], orders["dense"]])
                    orders["hybrid"] = score_ranks([fused.get(i, 0.0) for i in range(len(texts))])
                for m in methods:
                    ranks[m] = _first_hit(orders[m], relevant)
            else:
                ranks = {m: None for m in methods}
            per_q.append({"id": q.id, "doc": q.doc, "survives": survives, "ranks": ranks})
        summary = {"survives": _mean([p["survives"] for p in per_q]), "chunks": len(chunks)}
        for m in methods:
            rs = [p["ranks"][m] for p in per_q]
            summary[m] = {
                "recall": _mean([r is not None and r <= k for r in rs]),
                "mrr": _mean([(1.0 / r) if (r is not None and r <= MRR_CUTOFF) else 0.0 for r in rs]),
            }
        result[parser] = {"summary": summary, "questions": per_q}
    return {
        "k": k,
        "mrr_cutoff": MRR_CUTOFF,
        "methods": methods,
        "chunk_chars": chunk_chars,
        "parsers": result,
    }


def timings(outputs: dict[str, dict[str, DocOutput]], pages: dict[str, int]) -> dict[str, dict]:
    out = {}
    for parser, docs in outputs.items():
        ok = [(d, o) for d, o in docs.items() if o.ok]
        n_pages = sum(pages.get(d, len(o.pages)) for d, o in ok)
        secs = sum(o.seconds for _, o in ok)
        warm = next((o.warmup_seconds for o in docs.values() if o.warmup_seconds is not None), None)
        out[parser] = {
            "pages": n_pages,
            "seconds": secs,
            "seconds_per_page": (secs / n_pages) if n_pages else None,
            "warmup_seconds": warm,
            "failed": [{"doc": d, "error": o.error} for d, o in docs.items() if not o.ok],
            "device": next((o.device for o in docs.values() if o.device), ""),
        }
    return out


def _mean(values) -> float:
    values = list(values)
    return (sum(float(v) for v in values) / len(values)) if values else 0.0
