from parsearena.retrieval import BM25, ranking, rrf


def test_bm25_prefers_matching_document():
    docs = ["the cat sat on the mat", "median household income was 80,610", "dogs and cats"]
    scores = BM25(docs).scores("median income")
    assert ranking(scores)[0] == 1


def test_bm25_empty_query_scores_zero():
    assert BM25(["a b", "c"]).scores("") == [0.0, 0.0]


def test_ranking_is_stable_on_ties():
    assert ranking([1.0, 2.0, 2.0, 0.0]) == [1, 2, 0, 3]


def test_rrf_combines_rankings():
    fused = rrf([[0, 1, 2], [2, 1, 0]])
    assert fused == [0, 2, 1]
    assert rrf([[3, 1], [3, 2]])[0] == 3
