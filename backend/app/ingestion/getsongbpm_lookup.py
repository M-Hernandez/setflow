"""GetSongBPM API lookup: artist + title → BPM + musical key.

Two-step API:
1. Search: GET https://api.getsongbpm.com/search/?api_key={key}&type=song&lookup={title}
2. Detail: GET https://api.getsongbpm.com/song/?api_key={key}&id={id}

Free tier — requires API key + backlink to getsongbpm.com.
"""

import asyncio
import logging
from urllib.parse import quote_plus

import httpx
from pydantic import BaseModel

logger = logging.getLogger(__name__)

# Conservative concurrency for free tier
_semaphore = asyncio.Semaphore(5)

GETSONGBPM_BASE_URL = "https://api.getsongbpm.com"


class GetSongBPMMatch(BaseModel):
    """Enrichment data from GetSongBPM."""

    bpm: float | None = None
    key: str | None = None  # Normalized to title case, e.g. "A Minor"


def _normalize_key(raw: str) -> str | None:
    """Normalize GetSongBPM key format to Beatport-style.

    GetSongBPM returns keys like "Em", "A", "C#m", "Bb".
    Convert to Beatport format: "E Minor", "A Major", "C# Minor", "Bb Major".
    """
    if not raw or raw.strip() == "":
        return None

    raw = raw.strip()

    # Already in long form like "A Minor" or "C# Major"
    if "minor" in raw.lower() or "major" in raw.lower():
        return raw.title()

    # Short form: "Em", "C#m", "Bbm", "A", "F#"
    if raw.endswith("m"):
        note = raw[:-1]
        quality = "Minor"
    else:
        note = raw
        quality = "Major"

    if not note:
        return None

    # Capitalize note properly: first letter upper, rest as-is
    note = note[0].upper() + note[1:]

    return f"{note} {quality}"


async def search(
    client: httpx.AsyncClient,
    artist: str,
    title: str,
    api_key: str,
) -> GetSongBPMMatch | None:
    """Search GetSongBPM for a track by artist + title.

    Uses a two-step process: search for song ID, then fetch details.
    Returns BPM and key if found.
    """
    if not api_key:
        return None

    async with _semaphore:
        # Step 1: Search for the song
        try:
            search_resp = await client.get(
                f"{GETSONGBPM_BASE_URL}/search/",
                params={
                    "api_key": api_key,
                    "type": "song",
                    "lookup": f"{artist} {title}",
                },
                timeout=10.0,
            )
            search_resp.raise_for_status()
        except (httpx.HTTPError, httpx.TimeoutException) as e:
            logger.warning(
                "GetSongBPM search failed for '%s - %s': %s", artist, title, e
            )
            return None

        search_data = search_resp.json()
        results = search_data.get("search")

        if not results or isinstance(results, dict) and "error" in results:
            return None

        if not isinstance(results, list) or len(results) == 0:
            return None

        # Take the first result's ID
        song_id = results[0].get("id")
        if not song_id:
            return None

        # Step 2: Fetch song details for BPM + key
        try:
            detail_resp = await client.get(
                f"{GETSONGBPM_BASE_URL}/song/",
                params={"api_key": api_key, "id": song_id},
                timeout=10.0,
            )
            detail_resp.raise_for_status()
        except (httpx.HTTPError, httpx.TimeoutException) as e:
            logger.warning(
                "GetSongBPM detail failed for song ID %s: %s", song_id, e
            )
            return None

        song_data = detail_resp.json().get("song", {})

        bpm_raw = song_data.get("tempo")
        key_raw = song_data.get("key_of")

        bpm: float | None = None
        if bpm_raw:
            try:
                bpm = float(bpm_raw)
                if bpm <= 0:
                    bpm = None
            except (ValueError, TypeError):
                bpm = None

        key = _normalize_key(key_raw) if key_raw else None

        if bpm is None and key is None:
            return None

        return GetSongBPMMatch(bpm=bpm, key=key)
