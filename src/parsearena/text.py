"""Normalization and the one chunker every parser output goes through."""

from __future__ import annotations

import html
import re
import unicodedata
from dataclasses import dataclass

_TAG = re.compile(r"<[^>]{1,200}>")
_MD_MARKUP = re.compile(r"[*_`#|>~$\\]")
_HYPHEN_BREAK = re.compile(r"(\w)-\s*\n\s*(\w)")
_WS = re.compile(r"\s+")
_WORD = re.compile(r"\w+", re.UNICODE)
_SPACES = re.compile(r"[ \t\u00a0]{2,}")
_TABLE_RULE = re.compile(r"^\s*\|?[\s:|-]*-{3,}[\s:|-]*\|?\s*$", re.M)


def normalize(text: str) -> str:
    """Lowercase, strip markdown/HTML markup and collapse whitespace.

    Used to decide whether an answer string survives parsing, so it removes
    formatting differences between parsers (tables as pipes or HTML, bold,
    LaTeX dollars) but keeps the characters that carry meaning.
    """
    text = unicodedata.normalize("NFKC", text or "")
    text = _HYPHEN_BREAK.sub(r"\1\2", text)
    text = html.unescape(_TAG.sub(" ", text))
    text = _MD_MARKUP.sub(" ", text)
    text = text.replace("−", "-").replace("–", "-").replace("—", "-")
    return _WS.sub(" ", text).strip().lower()


def contains(haystack_norm: str, needle: str) -> bool:
    n = normalize(needle)
    return bool(n) and n in haystack_norm


def tokenize(text: str) -> list[str]:
    return _WORD.findall(normalize(text))


@dataclass(frozen=True)
class Chunk:
    doc: str
    index: int
    text: str


def _split_long(block: str, max_chars: int) -> list[str]:
    if len(block) <= max_chars:
        return [block]
    parts: list[str] = []
    for line in block.split("\n"):
        while len(line) > max_chars:
            cut = line.rfind(" ", 0, max_chars)
            cut = cut if cut > max_chars // 2 else max_chars
            parts.append(line[:cut])
            line = line[cut:].lstrip()
        parts.append(line)
    return [p for p in parts if p.strip()]


def chunk_text(doc: str, text: str, max_chars: int = 1200) -> list[Chunk]:
    """Pack paragraphs greedily into chunks of at most ``max_chars``.

    Paragraphs are separated by blank lines. A paragraph that is too long (a big
    table) is split by lines, and a line that is too long by words. The same
    function is applied to every parser, so differences in retrieval come from
    the parser output and not from the chunking.
    """
    # Padding spaces and markdown table rules carry no content; drop them so
    # chunk size measures text, not layout.
    text = _TABLE_RULE.sub("", _SPACES.sub(" ", text or ""))
    pieces: list[str] = []
    for block in re.split(r"\n\s*\n", text):
        block = block.strip()
        if block:
            pieces.extend(_split_long(block, max_chars))
    chunks: list[str] = []
    current = ""
    for piece in pieces:
        if current and len(current) + 2 + len(piece) > max_chars:
            chunks.append(current)
            current = piece
        else:
            current = f"{current}\n\n{piece}" if current else piece
    if current:
        chunks.append(current)
    return [Chunk(doc=doc, index=i, text=c) for i, c in enumerate(chunks)]
