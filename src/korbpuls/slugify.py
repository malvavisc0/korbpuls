"""Slug generation from German text with umlaut transliteration."""

from __future__ import annotations

import re
import unicodedata


def slugify(text: str) -> str:
    """Convert German text to URL-safe slug.

    - Lowercase everything
    - Transliterate umlauts: ö→oe, ü→ue, ä→ae, ß→ss
    - Replace non-alphanumeric chars with hyphens
    - Collapse consecutive hyphens
    - Strip leading/trailing hyphens

    Args:
        text: German text to convert (e.g., team name or league name)

    Returns:
        URL-safe slug string

    Examples:
        >>> slugify("TV 1877 Lauf")
        'tv-1877-lauf'
        >>> slugify("MFR U12 mix Bezirksliga Nord")
        'mfr-u12-mix-bezirksliga-nord'
        >>> slugify("Post SV Nürnberg 4 (w)")
        'post-sv-nuernberg-4-w'
        >>> slugify("ESC Höchstadt")
        'esc-hoechstadt'
    """
    umlaut_map = {
        "ü": "ue",
        "ö": "oe",
        "ä": "ae",
        "ß": "ss",
        "Ü": "Ue",
        "Ö": "Oe",
        "Ä": "Ae",
    }
    for char, replacement in umlaut_map.items():
        text = text.replace(char, replacement)

    normalized = unicodedata.normalize("NFD", text)
    ascii_text = "".join(c for c in normalized if unicodedata.category(c) != "Mn")

    slug = ascii_text.lower()
    slug = slug.replace("&", "und")
    slug = re.sub(r"[^a-z0-9\s-]", " ", slug)
    slug = slug.replace(" ", "-")
    slug = re.sub(r"-+", "-", slug)
    return slug.strip("-")
