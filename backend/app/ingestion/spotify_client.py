"""Spotify Web API client for track search and ISRC lookup.

Uses client credentials flow (no user auth needed for search).
Caches results in memory to avoid duplicate API calls.
"""

import logging
import time

import spotipy
from spotipy.oauth2 import SpotifyClientCredentials
from pydantic import BaseModel

from app.config import settings

logger = logging.getLogger(__name__)


class SpotifyResult(BaseModel):
    """Result from a Spotify track search."""

    spotify_uri: str
    isrc: str | None = None
    duration_ms: int
    name: str
    artist: str


class SpotifyRateLimitError(Exception):
    """Raised when Spotify rate limit retry-after exceeds max wait."""

    def __init__(self, retry_after: int) -> None:
        self.retry_after = retry_after
        super().__init__(f"Spotify rate limit: retry after {retry_after}s exceeds max wait")


# Retry-After thresholds for tiered response
SOFT_LIMIT_MAX = 60       # ≤60s: sleep it off, resume normally
MEDIUM_LIMIT_MAX = 600    # 60-600s: sleep it off, bump throttle to 3s
# >600s: kill client for this session (request limit territory)

# Minimum seconds between API calls (Spotify rolling 30s window, ~180 req/min)
DEFAULT_REQUEST_INTERVAL = 2.0
SLOWDOWN_REQUEST_INTERVAL = 3.0


class SpotifyClient:
    """Thin wrapper around spotipy with caching and rate-limit handling.

    Tiered rate-limit response:
    - Retry-After ≤ 60s:  sleep and resume (soft rate limit)
    - Retry-After 60-600s: sleep, resume with slower throttle
    - Retry-After > 600s:  kill client for session (request limit ban)
    """

    def __init__(self) -> None:
        auth_manager = SpotifyClientCredentials(
            client_id=settings.spotify_client_id,
            client_secret=settings.spotify_client_secret,
        )
        # Disable spotipy's internal retries — we handle rate limits ourselves
        self._sp = spotipy.Spotify(
            auth_manager=auth_manager, retries=0, status_retries=0
        )
        self._cache: dict[str, SpotifyResult | None] = {}
        self._last_request_time: float = 0.0
        self._request_interval: float = DEFAULT_REQUEST_INTERVAL
        self._circuit_open: bool = False

    @property
    def is_disabled(self) -> bool:
        """True if the client has been disabled by a request limit ban."""
        return self._circuit_open

    def _handle_rate_limit(self, retry_after: int) -> None:
        """Handle a 429 response based on Retry-After value.

        Soft (≤60s): sleep and continue.
        Medium (60-600s): sleep, slow down throttle.
        Hard (>600s): kill client — request limit ban territory.
        """
        if retry_after > MEDIUM_LIMIT_MAX:
            logger.error(
                "Spotify request limit ban (%ds retry-after) — "
                "circuit breaker OPEN, disabling Spotify for this session",
                retry_after,
            )
            self._circuit_open = True
            raise SpotifyRateLimitError(retry_after)
        elif retry_after > SOFT_LIMIT_MAX:
            logger.warning(
                "Spotify medium rate limit (%ds) — sleeping and slowing throttle to %.1fs",
                retry_after, SLOWDOWN_REQUEST_INTERVAL,
            )
            time.sleep(retry_after)
            self._request_interval = SLOWDOWN_REQUEST_INTERVAL
        else:
            logger.info(
                "Spotify soft rate limit (%ds) — sleeping it off",
                retry_after,
            )
            time.sleep(retry_after)

    def search_track(
        self,
        artist: str,
        title: str,
        remix: str | None = None,
        max_retries: int = 5,
    ) -> SpotifyResult | None:
        """Search Spotify for a track by artist + title + optional remix tag.

        Returns SpotifyResult on match, None if no result found.
        Handles 429 rate limiting with tiered backoff.
        """
        if self._circuit_open:
            return None

        query = f"artist:{artist} track:{title}"
        if remix:
            query = f"artist:{artist} track:{title} {remix}"

        # Check cache
        if query in self._cache:
            return self._cache[query]

        for attempt in range(max_retries):
            try:
                self._throttle()
                results = self._sp.search(q=query, type="track", limit=5)
                break
            except spotipy.exceptions.SpotifyException as e:
                if e.http_status == 429:
                    retry_after = int(e.headers.get("Retry-After", 2 ** attempt))
                    self._handle_rate_limit(retry_after)
                    if self._circuit_open:
                        self._cache[query] = None
                        return None
                    # Soft/medium limit — loop back and retry
                    continue
                else:
                    logger.error("Spotify API error: %s", e)
                    self._cache[query] = None
                    return None
        else:
            # All retries exhausted — don't kill the client, just skip this track
            logger.warning(
                "Spotify retries exhausted for '%s' — skipping track (client stays alive)",
                query[:80],
            )
            self._cache[query] = None
            return None

        items = results.get("tracks", {}).get("items", [])
        if not items:
            self._cache[query] = None
            return None

        track = items[0]
        isrc = track.get("external_ids", {}).get("isrc")
        result = SpotifyResult(
            spotify_uri=track["uri"],
            isrc=isrc,
            duration_ms=track["duration_ms"],
            name=track["name"],
            artist=", ".join(a["name"] for a in track.get("artists", [])),
        )

        self._cache[query] = result
        return result

    def _throttle(self) -> None:
        """Enforce minimum interval between Spotify API requests."""
        elapsed = time.monotonic() - self._last_request_time
        if elapsed < self._request_interval:
            time.sleep(self._request_interval - elapsed)
        self._last_request_time = time.monotonic()
