"""Backfill Spotify URIs on existing tracks that are missing them.

Iterates over tracks linked to sets with NULL spotify_uri and retries
Spotify search using the fixed circuit breaker (PR #28).

Usage:
    python -m app.ingestion.backfill_spotify
    python -m app.ingestion.backfill_spotify --dry-run
    python -m app.ingestion.backfill_spotify --dj "Adam Beyer"
"""

import argparse
import asyncio
import logging
import re

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import async_session
from app.ingestion.spotify_client import SpotifyClient, SpotifyRateLimitError
from app.models import DJ, Set, SetTrack, Track

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

# Retry "Extended Mix" without remix tag (same logic as resolve.py)
_EXTENDED_MIX_RE = re.compile(r"^extended\s+mix$", re.IGNORECASE)


async def backfill_spotify(
    session: AsyncSession,
    spotify: SpotifyClient,
    dj_name: str | None = None,
    dry_run: bool = False,
) -> dict:
    """Retry Spotify search for all tracks with NULL spotify_uri.

    Optionally filter to tracks belonging to a specific DJ's sets.
    """
    # Build query: tracks linked to sets, missing spotify_uri
    linked_ids = select(SetTrack.track_id.distinct())

    if dj_name:
        # Filter to sets belonging to the specified DJ
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
            Track.spotify_uri.is_(None),
        )
        .order_by(Track.id)
    )
    tracks = result.scalars().all()

    stats = {
        "total_candidates": len(tracks),
        "spotify_filled": 0,
        "isrc_filled": 0,
        "no_match": 0,
        "rate_limited": False,
    }

    logger.info(
        "Found %d tracks missing Spotify URI%s",
        len(tracks),
        f" (DJ: {dj_name})" if dj_name else "",
    )

    for i, track in enumerate(tracks, 1):
        if spotify.is_disabled:
            logger.error("Spotify circuit breaker tripped — stopping backfill")
            stats["rate_limited"] = True
            break

        try:
            spotify_result = spotify.search_track(
                track.artist, track.title, track.remix
            )

            # Fallback: retry without "Extended Mix" remix tag
            if spotify_result is None and track.remix and _EXTENDED_MIX_RE.match(track.remix):
                spotify_result = spotify.search_track(
                    track.artist, track.title, None
                )

        except SpotifyRateLimitError:
            logger.error("Spotify request limit ban — stopping backfill")
            stats["rate_limited"] = True
            break

        if spotify_result:
            track.spotify_uri = spotify_result.spotify_uri
            stats["spotify_filled"] += 1
            if not track.isrc and spotify_result.isrc:
                track.isrc = spotify_result.isrc
                stats["isrc_filled"] += 1
            logger.debug(
                "Filled: %s - %s → %s",
                track.artist, track.title, spotify_result.spotify_uri,
            )
        else:
            stats["no_match"] += 1

        # Progress logging every 25 tracks
        if i % 25 == 0:
            logger.info(
                "Progress: %d/%d — filled=%d no_match=%d",
                i, len(tracks), stats["spotify_filled"], stats["no_match"],
            )

    if dry_run:
        logger.info("DRY RUN — rolling back all changes")
        await session.rollback()
    else:
        await session.flush()

    return stats


async def run_backfill(dj_name: str | None = None, dry_run: bool = False) -> dict:
    """Run the Spotify backfill."""
    spotify = SpotifyClient()

    async with async_session() as session:
        async with session.begin():
            stats = await backfill_spotify(session, spotify, dj_name, dry_run)

    return stats


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Backfill Spotify URIs on tracks missing them."
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Run search but don't commit changes to DB",
    )
    parser.add_argument(
        "--dj",
        type=str,
        default=None,
        help="Only backfill tracks from this DJ's sets",
    )
    args = parser.parse_args()

    stats = asyncio.run(run_backfill(dj_name=args.dj, dry_run=args.dry_run))

    print("\n" + "=" * 50)
    print("SPOTIFY BACKFILL RESULTS")
    print("=" * 50)
    print(f"  Total candidates:   {stats['total_candidates']}")
    print(f"  Spotify filled:     {stats['spotify_filled']}")
    print(f"  ISRC filled:        {stats['isrc_filled']}")
    print(f"  No match:           {stats['no_match']}")
    print(f"  Rate limited:       {stats['rate_limited']}")
    print("=" * 50)


if __name__ == "__main__":
    main()
