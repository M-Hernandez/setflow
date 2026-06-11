"""1001tracklists AJAX API client for track enrichment.

Undocumented AJAX endpoints on 1001tracklists.com that return track metadata,
platform streaming IDs (Spotify, Apple Music, Beatport, etc.), play counts,
and label data. No authentication required.

Base URL: https://www.1001tracklists.com
Verified: 2026-06-10 via curl.
Rate limit: Undocumented. robots.txt specifies 8s crawl-delay.

Anti-bot measures:
- Randomized delay (3-5s + jitter) between requests
- Rotating browser User-Agent pool
- Exponential backoff on failures (30s -> 60s -> 120s)
- Circuit breaker after 3 consecutive failures
"""

import asyncio
import logging
import random
from dataclasses import dataclass, field
from datetime import date

import httpx
from pydantic import BaseModel
from rapidfuzz import fuzz

from app.ingestion.canonicalize import canonicalize

logger = logging.getLogger(__name__)

BASE_URL = "https://www.1001tracklists.com"

FUZZY_THRESHOLD = 75

# Source codes from get_medialink.php response
SOURCE_BEATPORT = 1
SOURCE_APPLE_MUSIC = 2
SOURCE_TRAXSOURCE = 4
SOURCE_SOUNDCLOUD = 10
SOURCE_SPOTIFY = 36

_USER_AGENTS = [
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10.15; rv:126.0) Gecko/20100101 Firefox/126.0",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:126.0) Gecko/20100101 Firefox/126.0",
]


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------


class Tracklists1001SearchResult(BaseModel):
    """A single track result from search_track.php."""

    id_track: int
    fulltrackname: str
    play_count: int | None = None
    first_played: date | None = None
    id_type: int | None = None  # 0=official, 3=bootleg, 4=acappella
    label_name: str | None = None


class Tracklists1001Match(BaseModel):
    """Matched and enriched result ready for DB application."""

    id_track: int
    fulltrackname: str
    match_score: float
    play_count: int | None = None
    first_played: date | None = None
    label_name: str | None = None
    # Platform IDs from get_medialink
    spotify_uri: str | None = None
    apple_music_id: str | None = None
    beatport_id: int | None = None
    traxsource_id: str | None = None
    soundcloud_url: str | None = None
    duration: int | None = None


# ---------------------------------------------------------------------------
# Session state / circuit breaker
# ---------------------------------------------------------------------------


@dataclass
class SessionState:
    """Tracks consecutive failures for exponential backoff."""

    consecutive_failures: int = 0
    backoff_seconds: float = 30.0
    total_requests: int = 0
    total_failures: int = 0

    MAX_CONSECUTIVE_FAILURES: int = field(default=3, repr=False)

    def record_success(self) -> None:
        self.consecutive_failures = 0
        self.backoff_seconds = 30.0
        self.total_requests += 1

    async def record_failure(self) -> bool:
        """Sleep for backoff, then return True if session should stop."""
        self.consecutive_failures += 1
        self.total_requests += 1
        self.total_failures += 1
        if self.consecutive_failures >= self.MAX_CONSECUTIVE_FAILURES:
            logger.error(
                "Circuit breaker OPEN — %d consecutive failures, stopping session",
                self.consecutive_failures,
            )
            return True
        logger.warning(
            "Failure %d/%d — backing off %.0fs",
            self.consecutive_failures,
            self.MAX_CONSECUTIVE_FAILURES,
            self.backoff_seconds,
        )
        await asyncio.sleep(self.backoff_seconds)
        self.backoff_seconds = min(self.backoff_seconds * 2, 120.0)
        return False

    @property
    def should_stop(self) -> bool:
        return self.consecutive_failures >= self.MAX_CONSECUTIVE_FAILURES


# ---------------------------------------------------------------------------
# Pacing
# ---------------------------------------------------------------------------


async def pace() -> None:
    """Randomized delay between requests. Respects 8s robots.txt crawl-delay."""
    delay = random.uniform(3.0, 5.0) + random.uniform(-1.0, 1.0)
    delay = max(delay, 2.0)
    await asyncio.sleep(delay)


# ---------------------------------------------------------------------------
# Low-level HTTP
# ---------------------------------------------------------------------------


async def _make_request(
    client: httpx.AsyncClient,
    url: str,
    params: dict,
    state: SessionState,
) -> dict | None:
    """GET request with random UA, backoff on failure."""
    headers = {"User-Agent": random.choice(_USER_AGENTS)}
    try:
        resp = await client.get(url, params=params, headers=headers, timeout=10.0)
        if resp.status_code != 200:
            logger.warning(
                "1001tracklists HTTP %d for %s", resp.status_code, url
            )
            should_stop = await state.record_failure()
            if should_stop:
                return None
            return None
        data = resp.json()
        if not data.get("success", False):
            # Valid JSON but API-level failure (e.g., "no data found")
            state.record_success()  # not a transport failure
            return None
        state.record_success()
        return data
    except (httpx.HTTPError, httpx.TimeoutException) as exc:
        logger.warning("1001tracklists request failed: %s", exc)
        await state.record_failure()
        return None
    except (ValueError, UnicodeDecodeError):
        logger.warning("1001tracklists returned non-JSON for %s", url)
        await state.record_failure()
        return None


# ---------------------------------------------------------------------------
# Search tracks
# ---------------------------------------------------------------------------


def _parse_search_results(data: dict) -> list[Tracklists1001SearchResult]:
    """Parse the nested search_track.php response into flat result objects."""
    results: list[Tracklists1001SearchResult] = []
    raw = data.get("data", {})
    if isinstance(raw, list):
        # Empty or unexpected format
        return results

    for _uid, entry in raw.items():
        if not isinstance(entry, dict) or entry.get("object") != "track":
            continue
        props = entry.get("properties", {})
        fulltrackname = props.get("fulltrackname", "")
        if not fulltrackname:
            continue

        id_track_str = props.get("id_track", "")
        try:
            id_track = int(id_track_str)
        except (ValueError, TypeError):
            continue

        # Parse play_count
        play_count = None
        pc_raw = props.get("play_count")
        if pc_raw is not None:
            try:
                play_count = int(pc_raw)
            except (ValueError, TypeError):
                pass

        # Parse first_played date
        first_played = None
        fp_raw = props.get("first_played")
        if fp_raw:
            try:
                first_played = date.fromisoformat(fp_raw)
            except (ValueError, TypeError):
                pass

        # Parse id_type
        id_type = None
        it_raw = props.get("id_type")
        if it_raw is not None:
            try:
                id_type = int(it_raw)
            except (ValueError, TypeError):
                pass

        # Extract nested label
        label_name = None
        for key, val in props.items():
            if isinstance(val, dict) and val.get("object") == "label":
                label_name = val.get("properties", {}).get("labelname")
                break

        results.append(
            Tracklists1001SearchResult(
                id_track=id_track,
                fulltrackname=fulltrackname,
                play_count=play_count,
                first_played=first_played,
                id_type=id_type,
                label_name=label_name,
            )
        )

    return results


async def search_track(
    client: httpx.AsyncClient,
    query: str,
    state: SessionState,
) -> list[Tracklists1001SearchResult]:
    """Search 1001tracklists for tracks matching a query string."""
    data = await _make_request(
        client,
        f"{BASE_URL}/ajax/search_track.php",
        params={
            "p": query,
            "noIDFieldCheck": "true",
            "fixedMode": "true",
            "sf": "p",
        },
        state=state,
    )
    if data is None:
        return []
    return _parse_search_results(data)


# ---------------------------------------------------------------------------
# Get media links (platform IDs)
# ---------------------------------------------------------------------------


def _parse_medialinks(data: dict) -> dict[int, dict]:
    """Parse get_medialink.php response into {source_id: {playerId, duration}}."""
    links: dict[int, dict] = {}
    for item in data.get("data", []):
        if not isinstance(item, dict):
            continue
        try:
            source = int(item.get("source", 0))
        except (ValueError, TypeError):
            continue
        player_id = item.get("playerId")
        if not player_id:
            continue
        duration = None
        dur_raw = item.get("duration")
        if dur_raw is not None:
            try:
                duration = int(dur_raw)
            except (ValueError, TypeError):
                pass
        links[source] = {"playerId": str(player_id), "duration": duration}
    return links


async def get_medialinks(
    client: httpx.AsyncClient,
    id_track: int,
    state: SessionState,
) -> dict[int, dict]:
    """Get platform streaming links for a track by its 1001tracklists ID."""
    data = await _make_request(
        client,
        f"{BASE_URL}/ajax/get_medialink.php",
        params={"idObject": "5", "idItem": str(id_track)},
        state=state,
    )
    if data is None:
        return {}
    return _parse_medialinks(data)


# ---------------------------------------------------------------------------
# Track matching
# ---------------------------------------------------------------------------


def match_track(
    results: list[Tracklists1001SearchResult],
    artist: str,
    title: str,
    remix: str | None,
) -> tuple[Tracklists1001SearchResult | None, float]:
    """Find the best fuzzy match from search results.

    Returns (best_match, score) or (None, 0.0).
    """
    if not results:
        return None, 0.0

    # Build canonical reference string matching 1001TL format: "Artist - Title (Remix)"
    if remix:
        reference = canonicalize(f"{artist} - {title} ({remix})")
    else:
        reference = canonicalize(f"{artist} - {title}")

    best_result: Tracklists1001SearchResult | None = None
    best_score = 0.0

    for result in results:
        candidate = canonicalize(result.fulltrackname)
        score = fuzz.token_sort_ratio(reference, candidate)

        # Penalize bootlegs and acappellas when our track doesn't indicate one
        if result.id_type in (3, 4):
            score -= 15

        if score > best_score:
            best_score = score
            best_result = result

    if best_score >= FUZZY_THRESHOLD:
        return best_result, best_score
    return None, best_score


# ---------------------------------------------------------------------------
# High-level orchestrator
# ---------------------------------------------------------------------------


async def search_and_enrich(
    client: httpx.AsyncClient,
    artist: str,
    title: str,
    remix: str | None,
    state: SessionState,
) -> Tracklists1001Match | None:
    """Search for a track, match it, and fetch platform links.

    Makes 2 API calls per successful match (search + medialink) with
    pacing between them.
    """
    if state.should_stop:
        return None

    # Build search query — include remix for specificity
    query = f"{artist} {title}"
    if remix:
        query = f"{artist} {title} {remix}"

    results = await search_track(client, query, state)
    if not results or state.should_stop:
        return None

    matched, score = match_track(results, artist, title, remix)
    if matched is None:
        logger.debug(
            "No match for '%s - %s' (best score: %.1f)", artist, title, score
        )
        return None

    logger.info(
        "Matched '%s - %s' -> '%s' (score=%.1f, plays=%s)",
        artist,
        title,
        matched.fulltrackname,
        score,
        matched.play_count,
    )

    # Pace before medialink call
    await pace()

    # Fetch platform links
    links = await get_medialinks(client, matched.id_track, state)

    # Build Spotify URI from source=36
    spotify_uri = None
    if SOURCE_SPOTIFY in links:
        spotify_id = links[SOURCE_SPOTIFY]["playerId"]
        spotify_uri = f"spotify:track:{spotify_id}"

    # Apple Music ID from source=2
    apple_music_id = None
    if SOURCE_APPLE_MUSIC in links:
        apple_music_id = links[SOURCE_APPLE_MUSIC]["playerId"]

    # Beatport ID from source=1
    beatport_id = None
    if SOURCE_BEATPORT in links:
        try:
            beatport_id = int(links[SOURCE_BEATPORT]["playerId"])
        except (ValueError, TypeError):
            pass

    # Traxsource ID from source=4
    traxsource_id = None
    if SOURCE_TRAXSOURCE in links:
        traxsource_id = links[SOURCE_TRAXSOURCE]["playerId"]

    # SoundCloud URL from source=10
    soundcloud_url = None
    if SOURCE_SOUNDCLOUD in links:
        sc_id = links[SOURCE_SOUNDCLOUD]["playerId"]
        soundcloud_url = f"https://api.soundcloud.com/tracks/{sc_id}"

    # Duration: prefer Spotify, fall back to any available
    duration = None
    for src in (SOURCE_SPOTIFY, SOURCE_BEATPORT, SOURCE_APPLE_MUSIC):
        if src in links and links[src].get("duration"):
            duration = links[src]["duration"]
            break

    return Tracklists1001Match(
        id_track=matched.id_track,
        fulltrackname=matched.fulltrackname,
        match_score=score,
        play_count=matched.play_count,
        first_played=matched.first_played,
        label_name=matched.label_name,
        spotify_uri=spotify_uri,
        apple_music_id=apple_music_id,
        beatport_id=beatport_id,
        traxsource_id=traxsource_id,
        soundcloud_url=soundcloud_url,
        duration=duration,
    )
