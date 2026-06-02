"""MixesDB MediaWiki API client with local JSON caching."""

import json
import re
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

DEFAULT_SEARCH_LIMIT = 10
DEFAULT_DELAY_SECONDS = 1.5
CACHE_DIR = Path("data/cache/mixesdb")
API_BASE = "https://www.mixesdb.com/w/api.php"
USER_AGENT = "setflow-ingestion/0.1 (DJ set tracklist research)"


def _sanitize_filename(page_title: str) -> str:
    """Convert a page title to a safe filename for caching."""
    safe = re.sub(r"[^\w\s\-]", "_", page_title)
    safe = re.sub(r"\s+", "_", safe).strip("_")
    return safe[:200]


def _load_from_cache(page_title: str) -> dict | None:
    """Load cached page data, or None if not cached."""
    cache_path = CACHE_DIR / f"{_sanitize_filename(page_title)}.json"
    if cache_path.exists():
        return json.loads(cache_path.read_text())
    return None


def _save_to_cache(page_title: str, data: dict) -> None:
    """Save page data to the cache directory."""
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cache_path = CACHE_DIR / f"{_sanitize_filename(page_title)}.json"
    cache_path.write_text(json.dumps(data, ensure_ascii=False, indent=2))


def _api_request(params: dict) -> dict:
    """Make a GET request to the MixesDB MediaWiki API."""
    query_string = urllib.parse.urlencode(params)
    url = f"{API_BASE}?{query_string}"
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req) as resp:
        return json.loads(resp.read().decode())


def search_mixes(
    query: str,
    limit: int = DEFAULT_SEARCH_LIMIT,
    delay: float = DEFAULT_DELAY_SECONDS,
) -> list[dict]:
    """Search MixesDB for mix pages matching a query.

    Returns list of dicts with title, pageid, and snippet.
    """
    params = {
        "action": "query",
        "list": "search",
        "srsearch": query,
        "srlimit": limit,
        "format": "json",
    }
    data = _api_request(params)
    results = []
    for entry in data.get("query", {}).get("search", []):
        results.append({
            "title": entry.get("title", ""),
            "pageid": entry.get("pageid"),
            "snippet": entry.get("snippet", ""),
        })

    if delay > 0:
        time.sleep(delay)

    return results


def get_page_data(
    page_title: str,
    delay: float = DEFAULT_DELAY_SECONDS,
) -> dict:
    """Fetch wikitext and categories for a MixesDB page.

    Checks cache first. On cache miss, fetches from API and caches.
    """
    cached = _load_from_cache(page_title)
    if cached is not None:
        return cached

    # Fetch wikitext
    parse_params = {
        "action": "parse",
        "page": page_title,
        "format": "json",
        "prop": "wikitext|categories",
    }
    parse_data = _api_request(parse_params)

    parse_result = parse_data.get("parse", {})
    wikitext = parse_result.get("wikitext", {}).get("*", "")
    categories = [
        cat.get("*", "") for cat in parse_result.get("categories", [])
    ]

    result = {
        "page_title": page_title,
        "wikitext": wikitext,
        "categories": categories,
        "fetched_at": datetime.now(timezone.utc).isoformat(),
    }

    _save_to_cache(page_title, result)

    if delay > 0:
        time.sleep(delay)

    return result
