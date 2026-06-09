"""Backfill gap-filling enrichment on existing tracks.

Iterates over tracks with null BPM/key/subgenre/label and applies:
1. Deezer (ISRC → BPM)
2. GetSongBPM (artist + title → BPM + key)
3. Discogs (artist + title → genre/subgenre/label, with label fallback)

Usage:
    python -m app.ingestion.backfill_enrichment
    python -m app.ingestion.backfill_enrichment --dry-run
"""

import argparse
import asyncio
import logging
from dataclasses import dataclass

import httpx
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db import async_session
from app.ingestion.deezer_lookup import lookup_by_isrc as deezer_lookup_by_isrc
from app.ingestion.discogs_lookup import search_label_styles, search_track as discogs_search_track
from app.ingestion.genre_mapping import map_styles_to_subgenre
from app.ingestion.getsongbpm_lookup import search as getsongbpm_search
from app.ingestion.resolve import (
    _apply_deezer_enrichment,
    _apply_discogs_enrichment,
    _apply_getsongbpm_enrichment,
)
from app.models import SetTrack, Track

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


@dataclass
class BackfillStats:
    """Counts of what the backfill touched."""

    total_candidates: int = 0
    deezer_filled: int = 0
    getsongbpm_filled: int = 0
    discogs_filled: int = 0
    unchanged: int = 0


async def _discogs_with_backoff(
    client: httpx.AsyncClient,
    artist: str,
    title: str,
    token: str | None,
):
    """Try Discogs track search + label fallback with polite pacing.

    Authenticated: 60 req/min (1 req/s). Unauthenticated: 25 req/min (2.4s gap).
    Each track may make 2 calls (search + fallback), so we pace accordingly.
    """
    # Pace to stay under rate limit: ~2.5s between track lookups if unauthenticated
    delay = 1.0 if token else 2.5

    result = await discogs_search_track(client, artist, title, token)
    if result is not None and result.styles:
        await asyncio.sleep(delay)
        return result

    # Track search missed or no styles — try label fallback
    await asyncio.sleep(delay)
    result = await search_label_styles(client, artist, token)
    if result is not None:
        await asyncio.sleep(delay)
        return result

    await asyncio.sleep(delay)
    return None


async def backfill_tracks(
    session: AsyncSession,
    httpx_client: httpx.AsyncClient,
    getsongbpm_api_key: str | None,
    discogs_token: str | None,
    dry_run: bool = False,
) -> BackfillStats:
    """Backfill enrichment on all tracks that are missing BPM, key, subgenre, or label."""
    stats = BackfillStats()

    # Find all tracks linked to sets that need enrichment
    linked_ids = select(SetTrack.track_id.distinct())
    result = await session.execute(
        select(Track)
        .where(
            Track.id.in_(linked_ids),
            or_(
                Track.bpm.is_(None),
                Track.key.is_(None),
                Track.subgenre.is_(None),
                Track.label.is_(None),
            ),
        )
        .order_by(Track.id)
    )
    tracks = result.scalars().all()
    stats.total_candidates = len(tracks)
    logger.info("Found %d tracks needing enrichment", len(tracks))

    for i, track in enumerate(tracks, 1):
        changed = False

        # Deezer: ISRC → BPM
        if track.bpm is None and track.isrc:
            deezer_result = await deezer_lookup_by_isrc(httpx_client, track.isrc)
            if deezer_result and deezer_result.bpm is not None:
                _apply_deezer_enrichment(track, deezer_result)
                stats.deezer_filled += 1
                changed = True

        # GetSongBPM: artist + title → BPM + key
        if (track.bpm is None or track.key is None) and getsongbpm_api_key:
            gs_result = await getsongbpm_search(
                httpx_client, track.artist, track.title, getsongbpm_api_key
            )
            if gs_result:
                had_bpm = track.bpm is not None
                had_key = track.key is not None
                _apply_getsongbpm_enrichment(track, gs_result)
                if (track.bpm is not None and not had_bpm) or (track.key is not None and not had_key):
                    stats.getsongbpm_filled += 1
                    changed = True

        # Discogs: artist + title → genre/subgenre/label
        if track.genre is None or track.subgenre is None or track.label is None:
            discogs_result = await _discogs_with_backoff(
                httpx_client, track.artist, track.title, discogs_token
            )
            if discogs_result:
                had_subgenre = track.subgenre is not None
                _apply_discogs_enrichment(track, discogs_result)
                if track.subgenre is not None and not had_subgenre:
                    stats.discogs_filled += 1
                    changed = True

        if not changed:
            stats.unchanged += 1

        # Progress logging every 50 tracks
        if i % 50 == 0:
            logger.info(
                "Progress: %d/%d — deezer=%d getsongbpm=%d discogs=%d",
                i, len(tracks), stats.deezer_filled,
                stats.getsongbpm_filled, stats.discogs_filled,
            )

    if dry_run:
        logger.info("DRY RUN — rolling back all changes")
        await session.rollback()
    else:
        await session.flush()

    return stats


async def run_backfill(dry_run: bool = False) -> BackfillStats:
    """Run the backfill with env-configured API keys."""
    getsongbpm_api_key = settings.getsongbpm_api_key or None
    discogs_token = settings.discogs_token or None

    if not getsongbpm_api_key:
        logger.warning("GETSONGBPM_API_KEY not set — skipping GetSongBPM enrichment")
    if not discogs_token:
        logger.warning("DISCOGS_TOKEN not set — Discogs will use unauthenticated rate limit (25 req/min)")

    async with httpx.AsyncClient() as client:
        async with async_session() as session:
            async with session.begin():
                stats = await backfill_tracks(
                    session, client, getsongbpm_api_key, discogs_token, dry_run
                )

    return stats


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Backfill gap-filling enrichment on existing tracks."
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Run enrichment but don't commit changes to DB",
    )
    args = parser.parse_args()

    stats = asyncio.run(run_backfill(dry_run=args.dry_run))

    print("\n" + "=" * 50)
    print("BACKFILL RESULTS")
    print("=" * 50)
    print(f"  Total candidates:   {stats.total_candidates}")
    print(f"  Deezer filled:      {stats.deezer_filled}")
    print(f"  GetSongBPM filled:  {stats.getsongbpm_filled}")
    print(f"  Discogs filled:     {stats.discogs_filled}")
    print(f"  Unchanged:          {stats.unchanged}")
    print("=" * 50)


if __name__ == "__main__":
    main()
