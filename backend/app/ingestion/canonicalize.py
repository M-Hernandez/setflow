"""Track name canonicalization for matching across sources."""

import re
import unicodedata


def canonicalize(text: str) -> str:
    """Normalize a string for fuzzy matching.

    - NFKD unicode normalization (decompose ligatures, etc.)
    - Strip accents (keep base characters)
    - Lowercase
    - Collapse whitespace
    - Strip leading/trailing whitespace
    """
    # NFKD decomposition: é → e + combining accent
    text = unicodedata.normalize("NFKD", text)
    # Drop combining marks (accents)
    text = "".join(c for c in text if unicodedata.category(c) != "Mn")
    text = text.lower().strip()
    # Collapse multiple spaces
    text = re.sub(r"\s+", " ", text)
    return text


def canonicalize_track(
    artist: str, title: str, remix: str | None = None
) -> tuple[str, str, str | None]:
    """Canonicalize artist, title, and remix for matching.

    Returns (canonical_artist, canonical_title, canonical_remix).
    """
    return (
        canonicalize(artist),
        canonicalize(title),
        canonicalize(remix) if remix else None,
    )
