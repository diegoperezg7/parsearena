"""Question sets: hand-written YAML or drafted by an LLM from the PDF text layer."""

from __future__ import annotations

import json
import re
from pathlib import Path

import yaml

from .errors import BudgetExceeded, UserError
from .evaluate import Question
from .text import contains, normalize

EXAMPLE = """questions:
  - doc: report.pdf          # file name (or its stem) of one of the PDFs
    q: What was the median household income in 2023?
    answer: "80,610"          # a short string that must appear in the document
  - doc: report.pdf
    q: Which region had the highest median income?
    answers: ["West", "the West"]   # any of these counts
"""


def load_questions(path: Path, docs: list[dict]) -> list[Question]:
    if not path.exists():
        raise UserError(f"Questions file not found: {path}", "Format:\n" + EXAMPLE)
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as exc:
        raise UserError(f"Could not parse {path}: {exc}", "Format:\n" + EXAMPLE) from exc
    items = raw.get("questions") if isinstance(raw, dict) else raw
    if not isinstance(items, list):
        raise UserError(f"{path} has no `questions:` list.", "Format:\n" + EXAMPLE)
    by_name = {}
    for d in docs:
        by_name[d["id"]] = d["id"]
        by_name[d["file"]] = d["id"]
        by_name[Path(d["file"]).stem] = d["id"]
    out: list[Question] = []
    for i, item in enumerate(items, start=1):
        if not isinstance(item, dict):
            raise UserError(f"Question {i} in {path} is not a mapping.", "Format:\n" + EXAMPLE)
        doc = str(item.get("doc", ""))
        if doc not in by_name:
            raise UserError(
                f"Question {i} refers to unknown doc {doc!r}.",
                "Use the file name of one of the PDFs passed to run: " + ", ".join(d["file"] for d in docs),
            )
        answers = item.get("answers") or ([item["answer"]] if "answer" in item else [])
        answers = [str(a) for a in answers if str(a).strip()]
        if not item.get("q") or not answers:
            raise UserError(f"Question {i} in {path} needs `q` and `answer` (or `answers`).")
        out.append(
            Question(id=str(item.get("id") or f"q{i}"), doc=by_name[doc], q=str(item["q"]), answers=answers)
        )
    return out


def dump_questions(questions: list[Question], docs: list[dict], path: Path, header: str = "") -> None:
    file_of = {d["id"]: d["file"] for d in docs}
    data = {
        "questions": [
            {"id": q.id, "doc": file_of.get(q.doc, q.doc), "q": q.q, "answers": q.answers} for q in questions
        ]
    }
    text = yaml.safe_dump(data, sort_keys=False, allow_unicode=True, width=100)
    path.write_text((header + "\n" if header else "") + text, encoding="utf-8")


SYSTEM = (
    "You write retrieval test questions for a document. Each question must be answerable from a "
    "single passage, and its answer must be a SHORT string (a number, a name, a few words) copied "
    "verbatim from the text. Reply with JSON only."
)

PROMPT = """Text of the document "{name}" (may be truncated):
<<<
{text}
>>>
Write {n} questions about specific facts in this text (numbers in tables, definitions, names).
Return a JSON list like [{{"q": "...", "answer": "..."}}].
The answer must appear verbatim in the text above."""


def _parse_json_list(reply: str) -> list[dict]:
    reply = re.sub(r"<think>.*?</think>", "", reply, flags=re.S)
    m = re.search(r"\[.*\]", reply, flags=re.S)
    if not m:
        return []
    try:
        data = json.loads(m.group(0))
    except json.JSONDecodeError:
        return []
    return [d for d in data if isinstance(d, dict)]


def generate_questions(llm, docs: list[dict], texts: dict[str, str], per_doc: int = 5, log=print):
    """Draft questions per document; keep only those whose answer is in the source text.

    Returns (questions, skipped_docs, budget_error). Stops early, keeping what it
    has, if the next call would exceed the budget.
    """
    questions: list[Question] = []
    skipped: list[str] = []
    for d in docs:
        text = texts.get(d["id"], "")
        if len(text.strip()) < 200:
            skipped.append(d["file"])
            log(f"Skipping {d['file']}: no usable text layer to draft questions from (scanned?).")
            continue
        prompt = PROMPT.format(name=d["file"], text=text[:12000], n=per_doc)
        try:
            reply = llm.complete(SYSTEM, prompt, max_tokens=4000)
        except BudgetExceeded as exc:
            return questions, skipped, exc
        norm = normalize(text)
        kept = 0
        for item in _parse_json_list(reply):
            q, a = str(item.get("q", "")).strip(), str(item.get("answer", "")).strip()
            if q and a and len(a) <= 80 and contains(norm, a):
                kept += 1
                questions.append(Question(id=f"{d['id']}-g{kept}", doc=d["id"], q=q, answers=[a]))
        log(f"{d['file']}: kept {kept} questions")
    return questions, skipped, None
