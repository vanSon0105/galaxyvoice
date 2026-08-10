from __future__ import annotations

import re


_TITLE_ABBREVIATIONS = (
    "mr.",
    "mrs.",
    "ms.",
    "dr.",
    "prof.",
    "sr.",
    "jr.",
    "st.",
)
_INLINE_ABBREVIATIONS = (
    "vs.",
    "e.g.",
    "i.e.",
)
_SENTENCE_STARTERS = frozenset(
    {"a", "an", "he", "i", "it", "she", "that", "the", "they", "this", "we", "you"}
)

_WHITESPACE_RE = re.compile(r"\s+")


def normalize_text(text: str) -> str:
    """Collapse whitespace while keeping paragraph intent readable."""

    lines = [line.strip() for line in text.replace("\r\n", "\n").replace("\r", "\n").split("\n")]
    paragraphs: list[str] = []
    current: list[str] = []

    for line in lines:
        if not line:
            if current:
                paragraphs.append(" ".join(current))
                current = []
            continue
        current.append(_WHITESPACE_RE.sub(" ", line))

    if current:
        paragraphs.append(" ".join(current))

    return "\n".join(paragraphs).strip()


def split_text(text: str, max_chars: int = 160) -> list[str]:
    """Split narration text into subtitle/TTS sized chunks."""

    normalized = normalize_text(text)
    if not normalized:
        return []

    max_chars = max(40, int(max_chars))
    chunks: list[str] = []

    for paragraph in normalized.split("\n"):
        for sentence in _split_paragraph_into_sentences(paragraph):
            chunks.extend(_chunk_long_sentence(sentence, max_chars=max_chars))

    return [chunk for chunk in chunks if chunk and any(char.isalnum() for char in chunk)]


def _split_paragraph_into_sentences(paragraph: str) -> list[str]:
    sentences: list[str] = []
    start = 0
    text = paragraph.strip()

    for index, char in enumerate(text):
        if char not in ".!?;:":
            continue
        next_index = index + 1
        if next_index < len(text) and not text[next_index].isspace():
            continue
        if char == "." and next_index < len(text) and _ends_with_abbreviation(text, next_index):
            continue
        piece = text[start:next_index].strip()
        if piece:
            sentences.append(piece)
        start = next_index

    tail = text[start:].strip()
    if tail:
        sentences.append(tail)

    return sentences


def _ends_with_abbreviation(text: str, end: int) -> bool:
    prefix = text[:end].lower()
    if any(_has_abbreviation_suffix(prefix, abbreviation) for abbreviation in _TITLE_ABBREVIATIONS):
        return True
    if any(_has_abbreviation_suffix(prefix, abbreviation) for abbreviation in _INLINE_ABBREVIATIONS):
        return True
    if not _has_abbreviation_suffix(prefix, "u.s."):
        return False

    next_word = re.match(r"\s+([A-Za-z]+)", text[end:])
    return next_word is None or next_word.group(1).lower() not in _SENTENCE_STARTERS


def _has_abbreviation_suffix(prefix: str, abbreviation: str) -> bool:
    return prefix.endswith(abbreviation) and (
        len(prefix) == len(abbreviation)
        or not prefix[-len(abbreviation) - 1].isalpha()
    )


def _chunk_long_sentence(sentence: str, max_chars: int) -> list[str]:
    if len(sentence) <= max_chars:
        return [sentence]

    words = sentence.split()
    chunks: list[str] = []
    current: list[str] = []

    for word in words:
        candidate = " ".join([*current, word]) if current else word
        if len(candidate) <= max_chars:
            current.append(word)
            continue

        if current:
            chunks.append(" ".join(current))
            current = []

        if len(word) <= max_chars:
            current.append(word)
        else:
            chunks.extend(_split_oversized_word(word, max_chars=max_chars))

    if current:
        chunks.append(" ".join(current))

    return chunks


def _split_oversized_word(word: str, max_chars: int) -> list[str]:
    return [word[index : index + max_chars] for index in range(0, len(word), max_chars)]
