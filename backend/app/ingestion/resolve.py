"""Track resolution pipeline: ParsedTrack → enriched Track + SetTrack rows.

Every parsed track gets saved to the DB. Enrichment is best-effort:
1. Canonicalize artist/title/remix
2. Check for existing Track by (title, artist, remix) — deduplicate
3. Search Spotify (best-effort) → get ISRC, URI, duration
4. Look up ISRC in Beatport → get BPM, key, genre, subgenre
5. If no ISRC match, fuzzy match against Beatport
6. Insert Track (or reuse existing) + link via SetTrack
Tracks with no enrichment are saved with nulls for backfill later.
"""

import logging
import re
from dataclasses import dataclass, field

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ingestion.beatport_lookup import BeatportMatch, fuzzy_match, lookup_by_isrc
from app.ingestion.canonicalize import canonicalize_track
from app.ingestion.deezer_lookup import DeezerMatch
from app.ingestion.deezer_lookup import lookup_by_isrc as deezer_lookup_by_isrc
from app.ingestion.discogs_lookup import DiscogsMatch, search_label_styles, search_track as discogs_search_track
from app.ingestion.genre_mapping import map_styles_to_subgenre
from app.ingestion.getsongbpm_lookup import GetSongBPMMatch
from app.ingestion.getsongbpm_lookup import search as getsongbpm_search
from app.ingestion.parse_tracklist import ParsedTrack
from app.ingestion.spotify_client import SpotifyClient, SpotifyRateLimitError, SpotifyResult
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
    reason: str  # "no_spotify_match", "no_beatport_match", "no_enrichment"


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
        track.bpm_source = "beatport"
    if bp.key and not track.key:
        track.key = bp.key
        track.key_source = "beatport"
    if bp.genre and not track.genre:
        track.genre = bp.genre
        track.genre_source = "beatport"
    if bp.subgenre and not track.subgenre:
        track.subgenre = bp.subgenre
        track.subgenre_source = "beatport"
    if bp.label and not track.label:
        track.label = bp.label
        track.label_source = "beatport"


def _apply_deezer_enrichment(track: Track, dz: DeezerMatch) -> None:
    """Apply Deezer metadata to a Track, only filling empty fields."""
    if not track.deezer_id:
        track.deezer_id = dz.deezer_id
    if dz.bpm is not None and track.bpm is None:
        track.bpm = dz.bpm
        track.bpm_source = "deezer"


def _apply_getsongbpm_enrichment(track: Track, gs: GetSongBPMMatch) -> None:
    """Apply GetSongBPM metadata to a Track, only filling empty fields."""
    if gs.bpm is not None and track.bpm is None:
        track.bpm = gs.bpm
        track.bpm_source = "getsongbpm"
    if gs.key and not track.key:
        track.key = gs.key
        track.key_source = "getsongbpm"
    if gs.danceability is not None and track.danceability is None:
        track.danceability = gs.danceability
    if gs.acousticness is not None and track.acousticness is None:
        track.acousticness = gs.acousticness
    if gs.release_year is not None and track.release_year is None:
        track.release_year = gs.release_year
    if gs.artist_id and not track.getsongbpm_artist_id:
        track.getsongbpm_artist_id = gs.artist_id
    if gs.musicbrainz_id and not track.musicbrainz_id:
        track.musicbrainz_id = gs.musicbrainz_id


def _apply_discogs_enrichment(track: Track, dg: DiscogsMatch) -> None:
    """Apply Discogs metadata to a Track, only filling empty fields.

    Maps Discogs styles to Beatport subgenre/genre via genre_mapping.
    """
    if not track.discogs_id:
        track.discogs_id = dg.discogs_id
    if dg.label and not track.label:
        track.label = dg.label
        track.label_source = "discogs"
    if dg.styles and (not track.subgenre or not track.genre):
        subgenre, genre = map_styles_to_subgenre(dg.styles)
        if subgenre and not track.subgenre:
            track.subgenre = subgenre
            track.subgenre_source = "discogs"
        if genre and not track.genre:
            track.genre = genre
            track.genre_source = "discogs"


async def resolve_track(
    session: AsyncSession,
    parsed: ParsedTrack,
    spotify: SpotifyClient | None,
    httpx_client: httpx.AsyncClient | None = None,
    getsongbpm_api_key: str | None = None,
    discogs_token: str | None = None,
) -> tuple[Track, UnresolvedTrack | None]:
    """Resolve a single parsed track to an enriched Track row.

    Always returns a Track (never None). Enrichment is best-effort:
    Spotify → Beatport ISRC → Beatport fuzzy → Deezer BPM → GetSongBPM
    → Discogs genre/subgenre/label.

    Returns (track, None) on full enrichment, or (track, unresolved)
    when some enrichment source failed.
    """
    c_artist, c_title, c_remix = canonicalize_track(
        parsed.artist, parsed.title, parsed.remix
    )

    # Step 1: Check for existing track by identity
    existing = await _find_existing_track(session, c_artist, c_title, c_remix)

    # Step 2: Search Spotify (best-effort, skipped if circuit breaker is open)
    spotify_result: SpotifyResult | None = None
    if spotify is not None and not spotify.is_disabled:
        try:
            spotify_result = spotify.search_track(
                parsed.artist, parsed.title, parsed.remix
            )
            # Fallback: if remix is "Extended Mix", retry without it
            if spotify_result is None and parsed.remix and _EXTENDED_MIX_RE.match(parsed.remix):
                spotify_result = spotify.search_track(parsed.artist, parsed.title, None)
        except SpotifyRateLimitError as e:
            logger.warning(
                "Spotify request limit ban (%ds) — remaining tracks in this "
                "session will resolve without Spotify",
                e.retry_after,
            )

    # Step 2b: Deduplicate by ISRC or Spotify URI
    if not existing and spotify_result and spotify_result.isrc:
        existing = await _find_by_isrc(session, spotify_result.isrc)
    if not existing and spotify_result:
        existing = await _find_by_spotify_uri(session, spotify_result.spotify_uri)

    # Step 3: Beatport enrichment — ISRC first, then fuzzy (runs regardless of Spotify)
    beatport: BeatportMatch | None = None
    if spotify_result and spotify_result.isrc:
        beatport = await lookup_by_isrc(session, spotify_result.isrc)

    if beatport is None:
        beatport = await fuzzy_match(
            session, c_artist, c_title, c_remix
        )

    # Step 4: Build or update Track — always create a row
    if existing:
        track = existing
        # Fill in Spotify data if missing
        if spotify_result:
            if not track.spotify_uri:
                track.spotify_uri = spotify_result.spotify_uri
            if not track.isrc and spotify_result.isrc:
                track.isrc = spotify_result.isrc
    else:
        track = Track(
            title=c_title,
            artist=c_artist,
            remix=c_remix,
            spotify_uri=spotify_result.spotify_uri if spotify_result else None,
            isrc=spotify_result.isrc if spotify_result else None,
        )
        session.add(track)

    # Apply Beatport enrichment
    if beatport:
        _apply_beatport_enrichment(track, beatport)

    # Gap filling: Deezer BPM (requires ISRC)
    if track.bpm is None and track.isrc and httpx_client is not None:
        deezer_result = await deezer_lookup_by_isrc(httpx_client, track.isrc)
        if deezer_result:
            _apply_deezer_enrichment(track, deezer_result)
            logger.debug(
                "Deezer filled BPM for '%s - %s': %.1f",
                c_artist, c_title, deezer_result.bpm or 0,
            )

    # Gap filling: GetSongBPM (artist + title → BPM + key)
    if (track.bpm is None or track.key is None) and httpx_client is not None and getsongbpm_api_key:
        getsongbpm_result = await getsongbpm_search(
            httpx_client, c_artist, c_title, getsongbpm_api_key
        )
        if getsongbpm_result:
            _apply_getsongbpm_enrichment(track, getsongbpm_result)
            logger.debug(
                "GetSongBPM filled gaps for '%s - %s': bpm=%s key=%s",
                c_artist, c_title, getsongbpm_result.bpm, getsongbpm_result.key,
            )

    # Gap filling: Discogs (artist + title → genre/subgenre/label)
    if (track.genre is None or track.subgenre is None or track.label is None) and httpx_client is not None:
        discogs_result = await discogs_search_track(
            httpx_client, c_artist, c_title, discogs_token
        )
        # Label fallback: if track-level search missed, search by artist
        if discogs_result is None or not discogs_result.styles:
            discogs_result = await search_label_styles(
                httpx_client, c_artist, discogs_token
            )
        if discogs_result:
            _apply_discogs_enrichment(track, discogs_result)
            logger.debug(
                "Discogs filled gaps for '%s - %s': styles=%s label=%s (%s)",
                c_artist, c_title, discogs_result.styles,
                discogs_result.label, discogs_result.match_method,
            )

    # Track is unresolved if it has no BPM and no genre (no enrichment landed)
    unresolved: UnresolvedTrack | None = None
    if not beatport and track.bpm is None:
        reason = "no_enrichment" if spotify_result is None else "no_beatport_match"
        unresolved = UnresolvedTrack(
            artist=parsed.artist,
            title=parsed.title,
            remix=parsed.remix,
            position=parsed.position,
            reason=reason,
        )

    return track, unresolved


async def resolve_tracks(
    session: AsyncSession,
    parsed_tracks: list[ParsedTrack],
    set_id: int,
    spotify: SpotifyClient | None,
    httpx_client: httpx.AsyncClient | None = None,
    getsongbpm_api_key: str | None = None,
    discogs_token: str | None = None,
) -> ResolutionResult:
    """Resolve a list of parsed tracks and link them to a set.

    Creates Track rows (or reuses existing), enriches with Spotify + Beatport
    data, and inserts SetTrack rows linking them to the given set.

    Returns a ResolutionResult with counts and unresolved track details.
    """
    result = ResolutionResult()

    for parsed in parsed_tracks:
        track, unresolved = await resolve_track(
            session, parsed, spotify, httpx_client,
            getsongbpm_api_key, discogs_token,
        )

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
                "Partially resolved [%d]: %s - %s (%s) — %s",
                parsed.position,
                parsed.artist,
                parsed.title,
                parsed.remix,
                unresolved.reason,
            )

    await session.flush()
    return result
