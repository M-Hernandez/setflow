"""Track resolution pipeline: ParsedTrack → enriched Track + SetTrack rows.

Resolution flow per track:
1. Canonicalize artist/title/remix
2. Check for existing Track by (title, artist, remix) — deduplicate
3. Search Spotify → get ISRC, URI, duration
4. Look up ISRC in Beatport → get BPM, key, genre, subgenre
5. If no ISRC match, fuzzy match against Beatport
6. Insert Track (or reuse existing) + link via SetTrack
"""

import logging
import re
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ingestion.beatport_lookup import BeatportMatch, fuzzy_match, lookup_by_isrc
from app.ingestion.canonicalize import canonicalize_track
from app.ingestion.parse_tracklist import ParsedTrack
from app.ingestion.spotify_client import SpotifyClient, SpotifyResult
from app.models import SetTrack, Track

# Remix tags to strip and retry without when Spotify search fails
_EXTENDED_MIX_RE = re.compile(r"^extended\s+mix$", re.IGNORECASE)

logger = logging.getLogger(__name__)


@dataclass
class UnresolvedTrack:
    """A track that could not be fully resolved."""

    artist: str
    title: str
    remix: str | None
    position: int
    reason: str  # "no_spotify_match", "no_beatport_match"


@dataclass
class ResolutionResult:
    """Summary of a resolve_tracks() run."""

    resolved: int = 0
    reused: int = 0
    unresolved: list[UnresolvedTrack] = field(default_factory=list)


async def _find_existing_track(
    session: AsyncSession,
    artist: str,
    title: str,
    remix: str | None,
) -> Track | None:
    """Find an existing track by the unique (title, artist, remix) constraint.

    Also checks by ISRC or Spotify URI if those are set on the candidate.
    """
    query = select(Track).where(
        Track.title == title,
        Track.artist == artist,
    )
    if remix is not None:
        query = query.where(Track.remix == remix)
    else:
        query = query.where(Track.remix.is_(None))

    result = await session.execute(query)
    return result.scalar_one_or_none()


async def _find_by_isrc(session: AsyncSession, isrc: str) -> Track | None:
    """Find an existing track by ISRC."""
    result = await session.execute(
        select(Track).where(Track.isrc == isrc).limit(1)
    )
    return result.scalar_one_or_none()


async def _find_by_spotify_uri(session: AsyncSession, uri: str) -> Track | None:
    """Find an existing track by Spotify URI."""
    result = await session.execute(
        select(Track).where(Track.spotify_uri == uri).limit(1)
    )
    return result.scalar_one_or_none()


def _apply_beatport_enrichment(track: Track, bp: BeatportMatch) -> None:
    """Apply Beatport metadata to a Track, only filling empty fields."""
    if bp.beatport_id and not track.beatport_id:
        track.beatport_id = bp.beatport_id
    if bp.bpm is not None and track.bpm is None:
        track.bpm = float(bp.bpm)
    if bp.key and not track.key:
        track.key = bp.key
    if bp.genre and not track.genre:
        track.genre = bp.genre
    if bp.subgenre and not track.subgenre:
        track.subgenre = bp.subgenre
    if bp.label and not track.label:
        track.label = bp.label


async def resolve_track(
    session: AsyncSession,
    parsed: ParsedTrack,
    spotify: SpotifyClient,
) -> tuple[Track | None, UnresolvedTrack | None]:
    """Resolve a single parsed track to an enriched Track row.

    Returns (track, None) on success, (None, unresolved) on failure,
    or (track, unresolved) when Spotify resolved but Beatport didn't.
    """
    c_artist, c_title, c_remix = canonicalize_track(
        parsed.artist, parsed.title, parsed.remix
    )

    # Step 1: Check for existing track by identity
    existing = await _find_existing_track(session, c_artist, c_title, c_remix)

    # Step 2: Search Spotify
    spotify_result: SpotifyResult | None = spotify.search_track(
        parsed.artist, parsed.title, parsed.remix
    )

    # Fallback: if remix is "Extended Mix", retry without it
    if spotify_result is None and parsed.remix and _EXTENDED_MIX_RE.match(parsed.remix):
        spotify_result = spotify.search_track(parsed.artist, parsed.title, None)

    if spotify_result is None:
        if existing:
            return existing, None
        return None, UnresolvedTrack(
            artist=parsed.artist,
            title=parsed.title,
            remix=parsed.remix,
            position=parsed.position,
            reason="no_spotify_match",
        )

    # Step 2b: Deduplicate by ISRC or Spotify URI
    if not existing and spotify_result.isrc:
        existing = await _find_by_isrc(session, spotify_result.isrc)
    if not existing:
        existing = await _find_by_spotify_uri(session, spotify_result.spotify_uri)

    # Step 3: Beatport enrichment — ISRC first, then fuzzy
    beatport: BeatportMatch | None = None
    if spotify_result.isrc:
        beatport = await lookup_by_isrc(session, spotify_result.isrc)

    if beatport is None:
        beatport = await fuzzy_match(
            session, c_artist, c_title, c_remix
        )

    # Step 4: Build or update Track
    if existing:
        track = existing
        # Fill in Spotify data if missing
        if not track.spotify_uri:
            track.spotify_uri = spotify_result.spotify_uri
        if not track.isrc and spotify_result.isrc:
            track.isrc = spotify_result.isrc
    else:
        track = Track(
            title=c_title,
            artist=c_artist,
            remix=c_remix,
            spotify_uri=spotify_result.spotify_uri,
            isrc=spotify_result.isrc,
        )
        session.add(track)

    # Apply Beatport enrichment
    unresolved: UnresolvedTrack | None = None
    if beatport:
        _apply_beatport_enrichment(track, beatport)
    else:
        unresolved = UnresolvedTrack(
            artist=parsed.artist,
            title=parsed.title,
            remix=parsed.remix,
            position=parsed.position,
            reason="no_beatport_match",
        )

    return track, unresolved


async def resolve_tracks(
    session: AsyncSession,
    parsed_tracks: list[ParsedTrack],
    set_id: int,
    spotify: SpotifyClient,
) -> ResolutionResult:
    """Resolve a list of parsed tracks and link them to a set.

    Creates Track rows (or reuses existing), enriches with Spotify + Beatport
    data, and inserts SetTrack rows linking them to the given set.

    Returns a ResolutionResult with counts and unresolved track details.
    """
    result = ResolutionResult()

    for parsed in parsed_tracks:
        track, unresolved = await resolve_track(session, parsed, spotify)

        if track is None:
            if unresolved:
                result.unresolved.append(unresolved)
                logger.warning(
                    "Unresolved track [%d]: %s - %s (%s) — %s",
                    parsed.position,
                    parsed.artist,
                    parsed.title,
                    parsed.remix,
                    unresolved.reason,
                )
            continue

        # Flush to get track.id if it's new
        await session.flush()

        # Create SetTrack link
        set_track = SetTrack(
            set_id=set_id,
            track_id=track.id,
            position=parsed.position,
            start_time_seconds=parsed.timestamp_seconds
            if parsed.timestamp_seconds >= 0
            else None,
        )
        session.add(set_track)

        result.resolved += 1

        if unresolved:
            result.unresolved.append(unresolved)
            logger.info(
                "Partially resolved [%d]: %s - %s — %s",
                parsed.position,
                parsed.artist,
                parsed.title,
                unresolved.reason,
            )

    await session.flush()
    return result
