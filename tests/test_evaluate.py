from parsearena.evaluate import DocOutput, Question, evaluate, timings

QS = [
    Question("q1", "a", "What was the median household income?", ["80,610"]),
    Question("q2", "b", "Which model cancels the partition function?", ["Bradley-Terry"]),
]


def outputs():
    good = {
        "a": DocOutput(pages=["Intro text.", "| Median household income | 80,610 |"], seconds=2.0),
        "b": DocOutput(pages=["The Bradley-Terry model cancels the partition function."], seconds=1.0),
    }
    lossy = {
        "a": DocOutput(pages=["Intro text.", "/dollar.tab/eight.tab/zero.tab"], seconds=0.1),
        "b": DocOutput(pages=[], error="RuntimeError: boom"),
    }
    return {"good": good, "lossy": lossy}


def test_bm25_only_metrics():
    ev = evaluate(outputs(), QS, k=5)
    assert ev["methods"] == ["bm25"]
    g = ev["parsers"]["good"]["summary"]
    assert g["survives"] == 1.0
    assert g["bm25"]["recall"] == 1.0
    assert g["bm25"]["mrr"] == 1.0
    lossy = ev["parsers"]["lossy"]
    assert lossy["summary"]["survives"] == 0.0
    assert lossy["summary"]["bm25"]["recall"] == 0.0
    assert all(q["ranks"]["bm25"] is None for q in lossy["questions"])


def test_dense_and_hybrid_with_fake_embedder(fake_embedder):
    ev = evaluate(outputs(), QS, k=1, embedder=fake_embedder)
    assert ev["methods"] == ["bm25", "dense", "hybrid"]
    s = ev["parsers"]["good"]["summary"]
    for m in ("dense", "hybrid"):
        assert 0.0 <= s[m]["recall"] <= 1.0
        assert 0.0 <= s[m]["mrr"] <= 1.0
    assert ev["parsers"]["good"]["questions"][0]["ranks"]["hybrid"] is not None


def test_relevance_is_scoped_to_the_question_document():
    out = {"p": {"a": DocOutput(pages=["nothing here"]), "b": DocOutput(pages=["income 80,610"])}}
    ev = evaluate(out, [QS[0]], k=5)
    q = ev["parsers"]["p"]["questions"][0]
    assert q["survives"] is False
    assert q["ranks"]["bm25"] is None


def test_answer_survives_but_not_retrievable_counts_as_miss():
    # answer split across two chunks: survives in the full text check only if contiguous
    out = {"p": {"a": DocOutput(pages=["x " * 10 + "80,610"])}}
    ev = evaluate(out, [QS[0]], k=5, chunk_chars=30)
    assert ev["parsers"]["p"]["summary"]["survives"] == 1.0


def test_timings_exclude_failed_documents():
    tm = timings(outputs(), {"a": 2, "b": 1})
    assert tm["good"]["pages"] == 3
    assert tm["good"]["seconds_per_page"] == 1.0
    assert tm["lossy"]["pages"] == 2
    assert tm["lossy"]["failed"] == [{"doc": "b", "error": "RuntimeError: boom"}]


def test_no_questions_gives_zero_not_crash():
    ev = evaluate(outputs(), [], k=5)
    assert ev["parsers"]["good"]["summary"]["survives"] == 0.0
