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


class SpotifyClient:
    """Thin wrapper around spotipy with caching and rate-limit handling."""

    def __init__(self) -> None:
        auth_manager = SpotifyClientCredentials(
            client_id=settings.spotify_client_id,
            client_secret=settings.spotify_client_secret,
        )
        self._sp = spotipy.Spotify(auth_manager=auth_manager)
        self._cache: dict[str, SpotifyResult | None] = {}

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
                results = self._sp.search(q=query, type="track", limit=5)
                break
            except spotipy.exceptions.SpotifyException as e:
                if e.http_status == 429:
                    retry_after = int(e.headers.get("Retry-After", 2 ** attempt))
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
