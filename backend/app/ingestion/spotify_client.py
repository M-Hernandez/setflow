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


# Don't wait longer than 30s on a single rate-limit retry
MAX_RATE_LIMIT_WAIT = 30

# Minimum seconds between API calls (Spotify uses a rolling 30s window)
MIN_REQUEST_INTERVAL = 1.0


class SpotifyClient:
    """Thin wrapper around spotipy with caching and rate-limit handling."""

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

    def search_track(
        self,
        artist: str,
        title: str,
        remix: str | None = None,
        max_retries: int = 3,
    ) -> SpotifyResult | None:
        """Search Spotify for a track by artist + title + optional remix tag.

        Returns SpotifyResult on match, None if no result found.
        Handles 429 rate limiting with exponential backoff.
        """
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
                    if retry_after > MAX_RATE_LIMIT_WAIT:
                        logger.error(
                            "Spotify rate limit too long (%ds), aborting",
                            retry_after,
                        )
                        raise SpotifyRateLimitError(retry_after)
                    logger.warning(
                        "Spotify rate limited, retrying in %ds (attempt %d/%d)",
                        retry_after,
                        attempt + 1,
                        max_retries,
                    )
                    time.sleep(retry_after)
                else:
                    logger.error("Spotify API error: %s", e)
                    self._cache[query] = None
                    return None
        else:
            logger.error("Spotify rate limit retries exhausted for query: %s", query)
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
        if elapsed < MIN_REQUEST_INTERVAL:
            time.sleep(MIN_REQUEST_INTERVAL - elapsed)
        self._last_request_time = time.monotonic()
