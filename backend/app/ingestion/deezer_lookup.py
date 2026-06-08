"""Deezer API lookup: ISRC → BPM.

Deezer exposes BPM on its track endpoint with no authentication required.
Endpoint: GET https://api.deezer.com/track/isrc:{ISRC}
"""

import asyncio
import logging

import httpx
from pydantic import BaseModel

logger = logging.getLogger(__name__)

# Polite concurrency — Deezer allows ~50 req/s but no need to hammer
_semaphore = asyncio.Semaphore(20)

DEEZER_BASE_URL = "https://api.deezer.com"


class DeezerMatch(BaseModel):
    """Enrichment data from a Deezer track lookup."""

    deezer_id: int
    bpm: float | None = None


async def lookup_by_isrc(
    client: httpx.AsyncClient, isrc: str
) -> DeezerMatch | None:
    """Look up a track on Deezer by ISRC. Returns BPM if available."""
    async with _semaphore:
        try:
            resp = await client.get(
                f"{DEEZER_BASE_URL}/track/isrc:{isrc}",
                timeout=10.0,
            )
            resp.raise_for_status()
        except (httpx.HTTPError, httpx.TimeoutException) as e:
            logger.warning("Deezer lookup failed for ISRC %s: %s", isrc, e)
            return None

    data = resp.json()

    # Deezer returns {"error": {...}} for unknown ISRCs
    if "error" in data:
        return None

    deezer_id = data.get("id")
    if not deezer_id:
        return None

    bpm = data.get("bpm")
    # Deezer returns 0 when BPM is unknown
    if bpm is not None and bpm <= 0:
        bpm = None

    return DeezerMatch(
        deezer_id=deezer_id,
        bpm=float(bpm) if bpm else None,
    )
