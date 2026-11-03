from parsearena.text import chunk_text, contains, normalize, tokenize


def test_normalize_strips_markup_and_case():
    assert normalize("| **Median** | $80,610 |") == "median 80,610"
    assert normalize("<td>Bradley&#8211;Terry</td>") == "bradley-terry"
    assert normalize("infla-\ntion   adjusted") == "inflation adjusted"


def test_contains_ignores_formatting_differences():
    out = normalize("| All households | 132,200 | 80,610 |")
    assert contains(out, "80,610")
    assert not contains(out, "80,611")
    assert not contains(out, "   ")


def test_tokenize_lowercases_words():
    assert tokenize("Direct Preference-Optimization (DPO)") == ["direct", "preference", "optimization", "dpo"]


def test_chunks_respect_max_size_and_keep_all_text():
    paras = [f"Paragraph {i} " + "word " * 40 for i in range(20)]
    chunks = chunk_text("d", "\n\n".join(paras), max_chars=500)
    assert all(len(c.text) <= 500 for c in chunks)
    joined = " ".join(c.text for c in chunks)
    for i in range(20):
        assert f"Paragraph {i} " in joined
    assert [c.index for c in chunks] == list(range(len(chunks)))


def test_long_table_is_split_by_lines_and_rules_dropped():
    rows = "\n".join(f"| row {i} |      value {i}      |" for i in range(200))
    table = "| a | b |\n|-----|-----|\n" + rows
    chunks = chunk_text("d", table, max_chars=300)
    assert len(chunks) > 1
    assert all(len(c.text) <= 300 for c in chunks)
    assert not any("-----" in c.text for c in chunks)
    assert "| row 199 | value 199 |" in chunks[-1].text


def test_overlong_line_is_split_by_words():
    chunks = chunk_text("d", "x" * 50 + " " + "y " * 400, max_chars=100)
    assert all(len(c.text) <= 100 for c in chunks)


def test_empty_text_has_no_chunks():
    assert chunk_text("d", "") == []
    assert chunk_text("d", "\n\n  \n") == []
