import json

import pytest

from parsearena.errors import BudgetExceeded, UserError
from parsearena.questions import dump_questions, generate_questions, load_questions

DOCS = [
    {"id": "report", "file": "report.pdf", "num_pages": 2},
    {"id": "paper", "file": "paper.pdf", "num_pages": 1},
]


def test_load_accepts_answer_or_answers(tmp_path):
    p = tmp_path / "q.yaml"
    p.write_text(
        "questions:\n"
        "  - doc: report.pdf\n    q: Median?\n    answer: '80,610'\n"
        "  - doc: paper\n    q: Model?\n    answers: [Bradley-Terry, BT]\n"
    )
    qs = load_questions(p, DOCS)
    assert [q.doc for q in qs] == ["report", "paper"]
    assert qs[0].answers == ["80,610"]
    assert qs[1].answers == ["Bradley-Terry", "BT"]
    assert qs[0].id == "q1"


@pytest.mark.parametrize(
    "body",
    [
        "questions:\n  - doc: other.pdf\n    q: x\n    answer: y\n",
        "questions:\n  - doc: report.pdf\n    q: x\n",
        "nope: 1\n",
        "questions: [\n",
    ],
)
def test_load_rejects_bad_files(tmp_path, body):
    p = tmp_path / "q.yaml"
    p.write_text(body)
    with pytest.raises(UserError):
        load_questions(p, DOCS)


def test_missing_file_is_user_error(tmp_path):
    with pytest.raises(UserError, match="not found"):
        load_questions(tmp_path / "missing.yaml", DOCS)


def test_roundtrip(tmp_path):
    p = tmp_path / "q.yaml"
    p.write_text("questions:\n  - doc: report.pdf\n    q: Median?\n    answer: '80,610'\n")
    qs = load_questions(p, DOCS)
    out = tmp_path / "out.yaml"
    dump_questions(qs, DOCS, out, header="# test")
    assert load_questions(out, DOCS)[0].answers == ["80,610"]


class FakeLLM:
    def __init__(self, replies, fail_after=None):
        self.replies = list(replies)
        self.calls = 0
        self.fail_after = fail_after

    def complete(self, system, prompt, max_tokens=2000):
        if self.fail_after is not None and self.calls >= self.fail_after:
            raise BudgetExceeded("Budget exceeded")
        self.calls += 1
        return self.replies.pop(0)


TEXT = "Real median household income was $80,610 in 2023. " * 10


def test_generation_keeps_only_verbatim_answers():
    reply = "<think>hmm</think>" + json.dumps(
        [{"q": "Median income?", "answer": "80,610"}, {"q": "Invented?", "answer": "99,999"}]
    )
    qs, skipped, budget = generate_questions(FakeLLM([reply]), DOCS[:1], {"report": TEXT}, log=lambda m: None)
    assert [q.answers for q in qs] == [["80,610"]]
    assert skipped == [] and budget is None


def test_generation_skips_docs_without_text_layer():
    qs, skipped, _ = generate_questions(FakeLLM([]), DOCS[:1], {"report": "  "}, log=lambda m: None)
    assert qs == [] and skipped == ["report.pdf"]


def test_generation_returns_partial_results_on_budget():
    reply = json.dumps([{"q": "Median income?", "answer": "80,610"}])
    llm = FakeLLM([reply, reply], fail_after=1)
    texts = {"report": TEXT, "paper": TEXT}
    qs, _, budget = generate_questions(llm, DOCS, texts, log=lambda m: None)
    assert len(qs) == 1
    assert isinstance(budget, BudgetExceeded)
