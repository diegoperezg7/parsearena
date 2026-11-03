from parsearena.retrieval import BM25, rrf, score_ranks


def test_bm25_prefers_matching_document():
    docs = ["the cat sat on the mat", "median household income was 80,610", "dogs and cats"]
    scores = BM25(docs).scores("median income")
    assert score_ranks(scores, drop_zero=True) == {1: 1}


def test_bm25_empty_query_scores_zero():
    assert BM25(["a b", "c"]).scores("") == [0.0, 0.0]


def test_ties_share_a_rank():
    assert score_ranks([1.0, 2.0, 2.0, 0.0]) == {1: 1, 2: 1, 0: 3, 3: 4}


def test_zero_bm25_scores_are_not_retrieved():
    assert score_ranks([0.0, 3.0, 0.0], drop_zero=True) == {1: 1}


def test_rrf_sums_reciprocal_ranks():
    fused = rrf([{0: 1, 1: 2}, {1: 1, 2: 2}], k=60)
    assert fused[1] == 1 / 62 + 1 / 61
    assert fused[0] == 1 / 61 and fused[2] == 1 / 62
    assert max(fused, key=fused.get) == 1


def test_rrf_does_not_favour_corpus_order_for_unmatched_chunks():
    # chunk 0 and 2 have no BM25 match; dense prefers chunk 2. Chunk 0 must not win
    # just because it comes first in the corpus.
    bm25 = score_ranks([0.0, 5.0, 0.0], drop_zero=True)
    dense = score_ranks([0.1, 0.2, 0.9])
    fused = rrf([bm25, dense])
    ranks = score_ranks([fused.get(i, 0.0) for i in range(3)])
    assert ranks[2] < ranks[0]
