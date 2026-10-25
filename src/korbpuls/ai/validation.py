"""Validation helpers for AI-generated HTML."""

from __future__ import annotations

import re

_PARAGRAPH_RE = re.compile(r"<p(?:\s[^>]*)?>.*?</p>", re.DOTALL | re.IGNORECASE)
_TAG_RE = re.compile(r"<[^>]+>")
_META_MARKERS = (
    "previous assistant message",
    "unverified draft",
    "i need the actual",
    "i'll fetch",
    "i will fetch",
    "i'll now",
    "i will now",
    "as an ai",
    "language model",
    "run_korb_command",
    "tool call",
    "the user wants",
    "the user asked",
    "let me",
    "hmm,",
    "here is the",
)


def validate_html_paragraphs(
    value: str,
    *,
    min_paragraphs: int = 1,
    max_paragraphs: int = 3,
) -> str:
    """Validate model output as clean HTML paragraphs.

    Raises:
        ValueError: If the output contains anything other than the
            allowed number of non-empty ``<p>`` elements or contains
            process/meta text.
    """
    text = value.strip()
    paragraphs = _PARAGRAPH_RE.findall(text)
    if not paragraphs:
        raise ValueError("output must contain HTML <p> paragraphs")
    if not min_paragraphs <= len(paragraphs) <= max_paragraphs:
        raise ValueError(
            f"output must contain {min_paragraphs}-{max_paragraphs} paragraphs"
        )
    remainder = _PARAGRAPH_RE.sub("", text).strip()
    if remainder:
        raise ValueError("output may only contain HTML paragraphs")
    if not any(_TAG_RE.sub("", paragraph).strip() for paragraph in paragraphs):
        raise ValueError("output paragraphs must not be empty")
    lowered = text.lower()
    if any(marker in lowered for marker in _META_MARKERS):
        raise ValueError("output contains process or meta text")
    return text


def is_valid_html_paragraphs(
    value: object,
    *,
    min_paragraphs: int = 1,
    max_paragraphs: int = 3,
) -> bool:
    """Return whether a cached value is valid AI HTML."""
    if not isinstance(value, str):
        return False
    try:
        validate_html_paragraphs(
            value,
            min_paragraphs=min_paragraphs,
            max_paragraphs=max_paragraphs,
        )
    except ValueError:
        return False
    return True
