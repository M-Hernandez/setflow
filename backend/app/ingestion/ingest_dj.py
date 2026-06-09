"""End-to-end ingestion orchestrator for a single DJ.

Ties together: YouTube scrape → MixesDB scrape → cross-source dedup →
DB persistence (DJ/Set rows) → track resolution → transition derivation.
"""

import logging
import os
import re
from dataclasses import dataclass, field
from datetime import date

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ingestion.derive_transitions import derive_transitions_for_set
from app.ingestion.mixesdb import get_page_data, search_mixes
from app.ingestion.parse_tracklist import ParsedTrack, parse_tracklist
from app.ingestion.parse_wiki_tracklist import (
    classify_set_type,
    flatten_tracks,
    parse_page_title,
    parse_wiki_tracklist,
)
from app.ingestion.resolve import ResolutionResult, resolve_tracks
from app.ingestion.spotify_client import SpotifyClient
from app.ingestion.youtube import get_video_metadata, search_dj_sets
from app.models import DJ, Set, SetType

logger = logging.getLogger(__name__)


@dataclass
class ScrapedSet:
    """A set discovered from YouTube or MixesDB, before DB persistence."""

    title: str
    source: str  # "youtube" or "mixesdb"
    source_url: str | None = None
    set_type: str = "live"
    is_b2b: bool = False
    venue: str | None = None
    event_date: date | None = None
    duration_seconds: int | None = None
    tracks: list[ParsedTrack] = field(default_factory=list)


@dataclass
class IngestionResult:
    """Summary of a full DJ ingestion run."""

    dj_name: str
    sets_scraped: int = 0
    sets_after_dedup: int = 0
    sets_persisted: int = 0
    tracks_resolved: int = 0
    tracks_unresolved: int = 0
    transitions_created: int = 0


def _make_slug(name: str) -> str:
    """Create a URL-friendly slug from a DJ name."""
    # Simple slugification: lowercase, replace non-alphanumeric with hyphens
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    return slug


def _dedup_key(scraped: ScrapedSet) -> str:
    """Generate a dedup key for a scraped set.

    Uses DJ-normalized event date as the primary dedup signal.
    Falls back to title-based key if no date available.
    """
    if scraped.event_date:
        return f"{scraped.event_date.isoformat()}"
    # Normalize title for comparison
    return re.sub(r"\s+", " ", scraped.title.lower().strip())


def deduplicate_sets(sets: list[ScrapedSet]) -> list[ScrapedSet]:
    """Deduplicate sets found across YouTube and MixesDB.

    When the same set appears in both sources, prefer the one with more
    tracks. If tied, prefer YouTube (has timestamps for track durations).
    """
    by_key: dict[str, ScrapedSet] = {}

    for s in sets:
        key = _dedup_key(s)
        if key not in by_key:
            by_key[key] = s
        else:
            existing = by_key[key]
            # Prefer more tracks
            if len(s.tracks) > len(existing.tracks):
                by_key[key] = s
            elif len(s.tracks) == len(existing.tracks) and s.source == "youtube":
                by_key[key] = s

    return list(by_key.values())


def scrape_youtube(dj_name: str, limit: int = 10) -> list[ScrapedSet]:
    """Scrape YouTube for DJ sets and parse tracklists."""
    logger.info("Searching YouTube for '%s' DJ sets...", dj_name)
    videos = search_dj_sets(dj_name, limit=limit)
    logger.info("Found %d videos", len(videos))

    results: list[ScrapedSet] = []
    for video in videos:
        metadata = get_video_metadata(video["video_id"])
        description = metadata.get("description", "")
        tracks = parse_tracklist(description)

        if not tracks:
            continue

        results.append(ScrapedSet(
            title=metadata.get("title", video["title"]),
            source="youtube",
            source_url=f"https://www.youtube.com/watch?v={video['video_id']}",
            set_type="live",
            duration_seconds=video.get("duration"),
            tracks=tracks,
        ))

    logger.info("YouTube: %d sets with tracklists", len(results))
    return results


def _dj_name_matches(dj_name: str, page_dj_names: list[str]) -> bool:
    """Check if the target DJ appears in the page's DJ list.

    Uses case-insensitive substring matching to handle variations
    like "Armin van Buuren b2b ARTBAT" matching target "ARTBAT".
    """
    target = dj_name.lower()
    for name in page_dj_names:
        if target in name.lower() or name.lower() in target:
            return True
    return False


def scrape_mixesdb(dj_name: str, limit: int = 10) -> list[ScrapedSet]:
    """Scrape MixesDB for DJ sets and parse tracklists."""
    logger.info("Searching MixesDB for '%s'...", dj_name)
    pages = search_mixes(dj_name, limit=limit)
    logger.info("Found %d pages", len(pages))

    results: list[ScrapedSet] = []
    for page in pages:
        title = page["title"]
        page_data = get_page_data(title)
        wikitext = page_data.get("wikitext", "")
        categories = page_data.get("categories", [])

        metadata = parse_page_title(title)

        # Skip sets where target DJ doesn't appear in the title
        if not _dj_name_matches(dj_name, metadata.dj_names):
            logger.info("Skipping misattributed set: %s (DJs: %s)", title, metadata.dj_names)
            continue

        sections = parse_wiki_tracklist(wikitext)

        # For multi-DJ sets with sections, only keep the target DJ's section
        if len(sections) > 1:
            filtered = [s for s in sections if s.dj_name and dj_name.lower() in s.dj_name.lower()]
            if filtered:
                sections = filtered
                logger.info(
                    "Multi-DJ set '%s': keeping only %s's section (%d tracks)",
                    title, dj_name, sum(len(s.tracks) for s in sections),
                )

        tracks = flatten_tracks(sections)

        if not tracks:
            continue

        metadata.set_type = classify_set_type(categories)

        results.append(ScrapedSet(
            title=title,
            source="mixesdb",
            set_type=metadata.set_type,
            is_b2b=metadata.is_b2b,
            venue=metadata.venue,
            event_date=metadata.event_date,
            tracks=tracks,
        ))

    logger.info("MixesDB: %d sets with tracklists", len(results))
    return results


def _parse_set_type(s: str) -> SetType:
    """Convert a string set type to the SetType enum."""
    try:
        return SetType(s)
    except ValueError:
        return SetType.live


async def _get_or_create_dj(
    session: AsyncSession, name: str, genre: str | None = None
) -> DJ:
    """Get existing DJ or create a new one."""
    slug = _make_slug(name)
    result = await session.execute(
        select(DJ).where(DJ.slug == slug)
    )
    dj = result.scalar_one_or_none()
    if dj is None:
        dj = DJ(name=name, slug=slug, genre=genre)
        session.add(dj)
        await session.flush()
    return dj


async def _set_exists(session: AsyncSession, dj_id: int, title: str) -> bool:
    """Check if a set with this title already exists for this DJ."""
    result = await session.execute(
        select(Set.id).where(Set.dj_id == dj_id, Set.title == title).limit(1)
    )
    return result.scalar_one_or_none() is not None


async def ingest_dj(
    session: AsyncSession,
    dj_name: str,
    genre: str | None = None,
    youtube_limit: int = 10,
    mixesdb_limit: int = 10,
    spotify: SpotifyClient | None = None,
    httpx_client: httpx.AsyncClient | None = None,
) -> IngestionResult:
    """Run full ingestion pipeline for a single DJ.

    1. Scrape YouTube + MixesDB
    2. Deduplicate across sources
    3. Persist DJ + Set rows
    4. Resolve tracks (Spotify + Beatport + Deezer + GetSongBPM)
    5. Derive transitions

    Returns an IngestionResult summary.
    """
    result = IngestionResult(dj_name=dj_name)

    # Step 1: Scrape both sources
    yt_sets = scrape_youtube(dj_name, limit=youtube_limit)
    mdb_sets = scrape_mixesdb(dj_name, limit=mixesdb_limit)
    all_sets = yt_sets + mdb_sets
    result.sets_scraped = len(all_sets)

    # Step 2: Deduplicate
    deduped = deduplicate_sets(all_sets)
    result.sets_after_dedup = len(deduped)
    logger.info(
        "%s: %d sets scraped, %d after dedup",
        dj_name, result.sets_scraped, result.sets_after_dedup,
    )

    # Step 3: Persist DJ
    dj = await _get_or_create_dj(session, dj_name, genre)

    # Step 4: Persist sets, resolve tracks, derive transitions
    if spotify is None:
        spotify = SpotifyClient()

    from app.config import settings
    getsongbpm_api_key = settings.getsongbpm_api_key or None
    discogs_token = settings.discogs_token or None

    # Manage httpx client lifecycle — create one if not provided
    owns_client = httpx_client is None
    if owns_client:
        httpx_client = httpx.AsyncClient()

    try:
        for scraped in deduped:
            # Skip if already ingested
            if await _set_exists(session, dj.id, scraped.title):
                logger.info("Skipping already-ingested set: %s", scraped.title)
                continue

            # Create Set row
            db_set = Set(
                dj_id=dj.id,
                title=scraped.title,
                set_type=_parse_set_type(scraped.set_type),
                is_b2b=scraped.is_b2b,
                source_url=scraped.source_url,
                source=scraped.source,
                venue=scraped.venue,
                duration_seconds=scraped.duration_seconds,
            )
            if scraped.event_date:
                from datetime import datetime, timezone
                db_set.event_date = datetime.combine(
                    scraped.event_date, datetime.min.time(), tzinfo=timezone.utc
                )
            session.add(db_set)
            await session.flush()

            result.sets_persisted += 1

            # Resolve tracks (Spotify may be disabled by circuit breaker)
            if spotify is not None and spotify.is_disabled:
                logger.warning(
                    "Spotify disabled (rate limit circuit breaker) — "
                    "resolving '%s' with Beatport fuzzy match only",
                    scraped.title,
                )
            resolution: ResolutionResult = await resolve_tracks(
                session, scraped.tracks, db_set.id, spotify,
                httpx_client=httpx_client,
                getsongbpm_api_key=getsongbpm_api_key,
                discogs_token=discogs_token,
            )
            result.tracks_resolved += resolution.resolved
            result.tracks_unresolved += len(
                [u for u in resolution.unresolved if u.reason == "no_spotify_match"]
            )

            # Derive transitions
            transitions = await derive_transitions_for_set(session, db_set.id)
            result.transitions_created += transitions

            logger.info(
                "  Set '%s': %d tracks resolved, %d unresolved, %d transitions",
                scraped.title,
                resolution.resolved,
                len(resolution.unresolved),
                transitions,
            )
    finally:
        if owns_client:
            await httpx_client.aclose()

    return result
