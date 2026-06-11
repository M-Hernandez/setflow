"""Backfill track enrichment from 1001tracklists.

Searches 1001tracklists for each track missing a tracklists_1001_id,
then fetches platform streaming links (Spotify URI, Apple Music, etc.),
labels, play counts, and first-played dates.

Usage:
    python -m app.ingestion.backfill_1001tracklists
    python -m app.ingestion.backfill_1001tracklists --dry-run
    python -m app.ingestion.backfill_1001tracklists --dj "Adam Beyer"
    python -m app.ingestion.backfill_1001tracklists --batch-size 50
    python -m app.ingestion.backfill_1001tracklists --resume
    python -m app.ingestion.backfill_1001tracklists --reset-progress
"""

import argparse
import asyncio
import json
import logging
import random
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import httpx
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import async_session
from app.ingestion.resolve import _apply_1001tracklists_enrichment
from app.ingestion.tracklists1001_client import (
    SessionState,
    pace,
    search_and_enrich,
)
from app.models import DJ, Set, SetTrack, Track

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

PROGRESS_FILE = Path.home() / ".setflow" / "1001tracklists_progress.json"


# ---------------------------------------------------------------------------
# Progress persistence
# ---------------------------------------------------------------------------


def _load_progress() -> set[int]:
    """Load set of track IDs already attempted in previous runs."""
    if PROGRESS_FILE.exists():
        try:
            data = json.loads(PROGRESS_FILE.read_text())
            return set(data.get("attempted_ids", []))
        except (json.JSONDecodeError, OSError) as exc:
            logger.warning("Could not load progress file: %s", exc)
    return set()


def _save_progress(attempted_ids: set[int]) -> None:
    """Save attempted track IDs for resume."""
    PROGRESS_FILE.parent.mkdir(parents=True, exist_ok=True)
    PROGRESS_FILE.write_text(
        json.dumps(
            {
                "attempted_ids": sorted(attempted_ids),
                "last_run": datetime.now(timezone.utc).isoformat(),
            },
            indent=2,
        )
    )


def _clear_progress() -> None:
    """Delete progress file to start fresh."""
    if PROGRESS_FILE.exists():
        PROGRESS_FILE.unlink()
        logger.info("Progress file cleared: %s", PROGRESS_FILE)


# ---------------------------------------------------------------------------
# Stats
# ---------------------------------------------------------------------------


@dataclass
class BackfillStats:
    total_candidates: int = 0
    matched: int = 0
    spotify_filled: int = 0
    apple_music_filled: int = 0
    label_filled: int = 0
    beatport_filled: int = 0
    no_match: int = 0
    rate_limited: bool = False


# ---------------------------------------------------------------------------
# Core backfill
# ---------------------------------------------------------------------------


async def backfill_tracks(
    session: AsyncSession,
    client: httpx.AsyncClient,
    batch_size: int = 100,
    dj_name: str | None = None,
    dry_run: bool = False,
    resume: bool = False,
) -> BackfillStats:
    """Enrich tracks via 1001tracklists search + medialink pipeline."""
    stats = BackfillStats()
    state = SessionState()

    # Find tracks linked to sets that haven't been tried on 1001tracklists yet
    linked_ids = select(SetTrack.track_id.distinct())
    if dj_name:
        dj_set_ids = (
            select(Set.id)
            .join(DJ, Set.dj_id == DJ.id)
            .where(func.lower(DJ.name) == dj_name.lower())
        )
        linked_ids = linked_ids.where(SetTrack.set_id.in_(dj_set_ids))

    result = await session.execute(
        select(Track)
        .where(
            Track.id.in_(linked_ids),
            Track.tracklists_1001_id.is_(None),
        )
        .order_by(Track.id)
    )
    tracks = list(result.scalars().all())
    logger.info("Found %d tracks not yet tried on 1001tracklists", len(tracks))

    # Filter out already-attempted tracks if resuming
    attempted_ids = _load_progress() if resume else set()
    if resume and attempted_ids:
        before = len(tracks)
        tracks = [t for t in tracks if t.id not in attempted_ids]
        logger.info("Resume: skipped %d previously attempted tracks", before - len(tracks))

    if not tracks:
        logger.info("No tracks to process")
        return stats

    # Shuffle for anti-pattern detection
    random.shuffle(tracks)

    # Cap to batch size
    if len(tracks) > batch_size:
        logger.info("Capping to batch size %d (of %d candidates)", batch_size, len(tracks))
        tracks = tracks[:batch_size]

    stats.total_candidates = len(tracks)
    logger.info("Processing %d tracks", len(tracks))

    for i, track in enumerate(tracks, 1):
        if state.should_stop:
            logger.error("Circuit breaker open — stopping backfill")
            stats.rate_limited = True
            break

        match = await search_and_enrich(
            client, track.artist, track.title, track.remix, state
        )

        if match:
            had_spotify = track.spotify_uri is not None
            had_apple = track.apple_music_id is not None
            had_label = track.label is not None
            had_beatport = track.beatport_id is not None

            _apply_1001tracklists_enrichment(track, match)
            stats.matched += 1

            if track.spotify_uri and not had_spotify:
                stats.spotify_filled += 1
            if track.apple_music_id and not had_apple:
                stats.apple_music_filled += 1
            if track.label and not had_label:
                stats.label_filled += 1
            if track.beatport_id and not had_beatport:
                stats.beatport_filled += 1
        else:
            stats.no_match += 1

        # Track progress for resume
        attempted_ids.add(track.id)
        _save_progress(attempted_ids)

        # Progress logging every 10 tracks
        if i % 10 == 0:
            logger.info(
                "Progress: %d/%d — matched=%d spotify=%d apple=%d label=%d no_match=%d",
                i,
                stats.total_candidates,
                stats.matched,
                stats.spotify_filled,
                stats.apple_music_filled,
                stats.label_filled,
                stats.no_match,
            )

        # Pace between tracks (the search_and_enrich already paced between
        # its internal search and medialink calls)
        if i < len(tracks) and not state.should_stop:
            await pace()

    if dry_run:
        logger.info("DRY RUN — rolling back all changes")
        await session.rollback()
    else:
        await session.flush()

    return stats


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


async def run_backfill(
    dry_run: bool = False,
    dj_name: str | None = None,
    batch_size: int = 100,
    resume: bool = False,
) -> BackfillStats:
    """Run the backfill with configured settings."""
    async with httpx.AsyncClient() as client:
        async with async_session() as session:
            async with session.begin():
                stats = await backfill_tracks(
                    session,
                    client,
                    batch_size=batch_size,
                    dj_name=dj_name,
                    dry_run=dry_run,
                    resume=resume,
                )
    return stats


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Backfill track enrichment from 1001tracklists."
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Run enrichment but don't commit changes to DB",
    )
    parser.add_argument(
        "--dj",
        type=str,
        default=None,
        help="Only backfill tracks from a specific DJ's sets",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=100,
        help="Max tracks to process in this run (default: 100)",
    )
    parser.add_argument(
        "--resume",
        action="store_true",
        help="Skip tracks attempted in previous runs",
    )
    parser.add_argument(
        "--reset-progress",
        action="store_true",
        help="Clear progress file and start fresh",
    )
    args = parser.parse_args()

    if args.reset_progress:
        _clear_progress()

    stats = asyncio.run(
        run_backfill(
            dry_run=args.dry_run,
            dj_name=args.dj,
            batch_size=args.batch_size,
            resume=args.resume,
        )
    )

    print("\n" + "=" * 50)
    print("1001TRACKLISTS BACKFILL RESULTS")
    print("=" * 50)
    print(f"  Total candidates:   {stats.total_candidates}")
    print(f"  Matched:            {stats.matched}")
    print(f"  Spotify filled:     {stats.spotify_filled}")
    print(f"  Apple Music filled: {stats.apple_music_filled}")
    print(f"  Label filled:       {stats.label_filled}")
    print(f"  Beatport filled:    {stats.beatport_filled}")
    print(f"  No match:           {stats.no_match}")
    print(f"  Rate limited:       {stats.rate_limited}")
    print("=" * 50)


if __name__ == "__main__":
    main()
