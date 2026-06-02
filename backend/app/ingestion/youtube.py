"""YouTube video search and metadata extraction via yt-dlp."""

import json
import time
from datetime import datetime, timezone
from pathlib import Path

import yt_dlp

DEFAULT_SEARCH_LIMIT = 10
MIN_DURATION_SECONDS = 1200  # 20 minutes
DEFAULT_DELAY_SECONDS = 2.0
CACHE_DIR = Path("data/cache/youtube")


def _load_from_cache(video_id: str) -> dict | None:
    """Load cached metadata for a video ID, or None if not cached."""
    cache_path = CACHE_DIR / f"{video_id}.json"
    if cache_path.exists():
        return json.loads(cache_path.read_text())
    return None


def _save_to_cache(video_id: str, metadata: dict) -> None:
    """Save video metadata to the cache directory."""
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cache_path = CACHE_DIR / f"{video_id}.json"
    cache_path.write_text(json.dumps(metadata, ensure_ascii=False, indent=2))


def search_dj_sets(
    dj_name: str,
    limit: int = DEFAULT_SEARCH_LIMIT,
    delay: float = DEFAULT_DELAY_SECONDS,
) -> list[dict]:
    """Search YouTube for DJ set videos by artist name.

    Returns a list of dicts with video_id, title, duration, and url.
    Filters to videos longer than MIN_DURATION_SECONDS (20 min).
    """
    # Request more results than needed since we filter by duration
    search_limit = limit * 3
    search_url = f"ytsearch{search_limit}:{dj_name} DJ set"

    ydl_opts = {
        "quiet": True,
        "no_warnings": True,
        "extract_flat": True,
        "skip_download": True,
    }

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(search_url, download=False)

    results = []
    for entry in info.get("entries", []):
        duration = entry.get("duration") or 0
        if duration < MIN_DURATION_SECONDS:
            continue
        results.append({
            "video_id": entry.get("id"),
            "title": entry.get("title"),
            "duration": duration,
            "url": entry.get("url") or f"https://www.youtube.com/watch?v={entry.get('id')}",
        })
        if len(results) >= limit:
            break

    if delay > 0:
        time.sleep(delay)

    return results


def get_video_metadata(
    video_id: str,
    delay: float = DEFAULT_DELAY_SECONDS,
) -> dict:
    """Fetch video metadata (title, description, uploader, duration).

    Checks cache first. On cache miss, fetches from YouTube and caches.
    """
    cached = _load_from_cache(video_id)
    if cached is not None:
        return cached

    url = f"https://www.youtube.com/watch?v={video_id}"
    ydl_opts = {
        "quiet": True,
        "no_warnings": True,
        "skip_download": True,
    }

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=False)

    metadata = {
        "video_id": video_id,
        "title": info.get("title"),
        "uploader": info.get("uploader"),
        "duration": info.get("duration"),
        "description": info.get("description", ""),
        "fetched_at": datetime.now(timezone.utc).isoformat(),
    }

    _save_to_cache(video_id, metadata)

    if delay > 0:
        time.sleep(delay)

    return metadata
