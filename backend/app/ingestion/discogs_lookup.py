"""Discogs API lookup: artist + title → styles, label, year.

Search endpoint: GET https://api.discogs.com/database/search
  ?q={artist} {title}&type=release&per_page=5
  Authorization: Discogs token={token}  (optional, bumps rate limit 25→60 req/min)

Label fallback: when track-level search yields no style match, search by
artist only and aggregate label-level style tags.
"""

import asyncio
import logging

import httpx
from pydantic import BaseModel
from rapidfuzz import fuzz

logger = logging.getLogger(__name__)

# Conservative concurrency — Discogs rate limit is 60/min authenticated
_semaphore = asyncio.Semaphore(5)

DISCOGS_BASE_URL = "https://api.discogs.com"
DISCOGS_USER_AGENT = "SetflowDJEngine/0.1"

# Minimum fuzzy score to accept a Discogs result as a track-level match
FUZZY_THRESHOLD = 70


class DiscogsMatch(BaseModel):
    """Enrichment data from a Discogs search result."""

    discogs_id: int
    styles: list[str] = []
    label: str | None = None
    year: int | None = None
    match_method: str  # "track" or "label_fallback"


def _build_headers(token: str | None) -> dict[str, str]:
    """Build request headers, optionally with auth token."""
    headers = {"User-Agent": DISCOGS_USER_AGENT}
    if token:
        headers["Authorization"] = f"Discogs token={token}"
    return headers


def _score_result(
    result: dict, artist: str, title: str
) -> float:
    """Score a Discogs search result against the target artist + title."""
    r_title = result.get("title", "")

    # Discogs titles are formatted as "Artist - Title"
    if " - " in r_title:
        r_artist, r_track = r_title.split(" - ", 1)
    else:
        r_artist = ""
        r_track = r_title

    artist_score = fuzz.token_sort_ratio(artist.lower(), r_artist.lower())
    title_score = fuzz.token_sort_ratio(title.lower(), r_track.lower())

    # Weight title more heavily — artist names are often partial matches
    return (title_score * 0.6) + (artist_score * 0.4)


async def search_track(
    client: httpx.AsyncClient,
    artist: str,
    title: str,
    token: str | None = None,
) -> DiscogsMatch | None:
    """Search Discogs for a track by artist + title.

    Scores results with fuzzy matching and returns the best match
    above FUZZY_THRESHOLD, or None.
    """
    async with _semaphore:
        try:
            resp = await client.get(
                f"{DISCOGS_BASE_URL}/database/search",
                params={
                    "q": f"{artist} {title}",
                    "type": "release",
                    "per_page": 5,
                },
                headers=_build_headers(token),
                timeout=10.0,
            )
            resp.raise_for_status()
        except (httpx.HTTPError, httpx.TimeoutException) as e:
            logger.warning(
                "Discogs search failed for '%s - %s': %s", artist, title, e
            )
            return None

    data = resp.json()
    results = data.get("results", [])

    if not results:
        return None

    # Score and pick best match
    best_result = None
    best_score = 0.0

    for r in results:
        score = _score_result(r, artist, title)
        if score > best_score:
            best_score = score
            best_result = r

    if best_result is None or best_score < FUZZY_THRESHOLD:
        return None

    logger.debug(
        "Discogs matched '%s - %s' → '%s' (score=%.1f)",
        artist, title, best_result.get("title", ""), best_score,
    )

    return DiscogsMatch(
        discogs_id=best_result.get("id", 0),
        styles=best_result.get("style", []),
        label=best_result.get("label", [None])[0] if best_result.get("label") else None,
        year=best_result.get("year") if isinstance(best_result.get("year"), int) else None,
        match_method="track",
    )


async def search_label_styles(
    client: httpx.AsyncClient,
    artist: str,
    token: str | None = None,
) -> DiscogsMatch | None:
    """Fallback: search Discogs by artist only and aggregate style tags.

    When track-level search fails, this collects styles from the artist's
    releases to infer genre at the label/catalog level.
    """
    async with _semaphore:
        try:
            resp = await client.get(
                f"{DISCOGS_BASE_URL}/database/search",
                params={
                    "q": artist,
                    "type": "release",
                    "per_page": 10,
                },
                headers=_build_headers(token),
                timeout=10.0,
            )
            resp.raise_for_status()
        except (httpx.HTTPError, httpx.TimeoutException) as e:
            logger.warning(
                "Discogs label fallback failed for artist '%s': %s", artist, e
            )
            return None

    data = resp.json()
    results = data.get("results", [])

    if not results:
        return None

    # Aggregate styles across results, ordered by frequency
    style_counts: dict[str, int] = {}
    first_label: str | None = None
    first_id: int = 0

    for r in results:
        for style in r.get("style", []):
            style_counts[style] = style_counts.get(style, 0) + 1
        if first_label is None and r.get("label"):
            first_label = r["label"][0] if isinstance(r["label"], list) else r["label"]
        if first_id == 0 and r.get("id"):
            first_id = r["id"]

    if not style_counts:
        return None

    # Sort by frequency — most common styles first
    sorted_styles = sorted(style_counts, key=style_counts.get, reverse=True)

    return DiscogsMatch(
        discogs_id=first_id,
        styles=sorted_styles,
        label=first_label,
        year=None,
        match_method="label_fallback",
    )
