"""Beatport reference table lookup: ISRC match + fuzzy fallback."""

import logging

from pydantic import BaseModel
from rapidfuzz import fuzz
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import BeatportTrack

logger = logging.getLogger(__name__)

FUZZY_THRESHOLD = 85


class BeatportMatch(BaseModel):
    """Enrichment data from a matched Beatport track."""

    beatport_id: int
    bpm: int | None = None
    key: str | None = None
    genre: str
    subgenre: str | None = None
    label: str | None = None
    match_method: str  # "isrc" or "fuzzy"


async def lookup_by_isrc(
    session: AsyncSession, isrc: str
) -> BeatportMatch | None:
    """Look up a Beatport track by ISRC (exact match)."""
    result = await session.execute(
        select(BeatportTrack).where(BeatportTrack.isrc == isrc).limit(1)
    )
    bp = result.scalar_one_or_none()
    if bp is None:
        return None

    return BeatportMatch(
        beatport_id=bp.id,
        bpm=bp.bpm,
        key=bp.key,
        genre=bp.genre,
        subgenre=bp.subgenre,
        label=bp.label,
        match_method="isrc",
    )


async def fuzzy_match(
    session: AsyncSession,
    artist: str,
    title: str,
    remix: str | None = None,
    genre: str | None = None,
) -> BeatportMatch | None:
    """Fuzzy match against Beatport tracks using rapidfuzz.

    Matches title and remix tag independently to avoid matching the
    wrong version (e.g., Original Mix vs ARTBAT Remix).

    If genre is provided, searches only within that genre for efficiency.
    Otherwise searches all genres.
    """
    query = select(BeatportTrack)
    if genre:
        query = query.where(BeatportTrack.genre == genre)

    # Limit search scope — streaming all Beatport tracks is too expensive.
    # Use artist name as a SQL filter to narrow the candidate set.
    query = query.where(BeatportTrack.artist.ilike(f"%{artist}%"))
    result = await session.execute(query)
    candidates = result.scalars().all()

    if not candidates:
        return None

    best_match: BeatportTrack | None = None
    best_score: float = 0.0

    for bp in candidates:
        # Score title match
        title_score = fuzz.token_sort_ratio(title.lower(), bp.name.lower())

        # Score remix match — must match independently
        if remix and bp.mix_name:
            remix_score = fuzz.token_sort_ratio(remix.lower(), bp.mix_name.lower())
        elif not remix and not bp.mix_name:
            # Both have no remix — perfect match on this dimension
            remix_score = 100.0
        elif not remix and bp.mix_name:
            # Input has no remix but Beatport has one — check if it's "Original Mix"
            remix_score = 100.0 if bp.mix_name.lower() == "original mix" else 30.0
        else:
            # Input has remix but Beatport doesn't — poor match
            remix_score = 30.0

        # Combined score: title weighted more heavily, remix is a gate
        combined = (title_score * 0.6) + (remix_score * 0.4)

        if combined > best_score:
            best_score = combined
            best_match = bp

    if best_match is None or best_score < FUZZY_THRESHOLD:
        return None

    logger.debug(
        "Fuzzy matched '%s - %s (%s)' → Beatport '%s - %s (%s)' score=%.1f",
        artist,
        title,
        remix,
        best_match.artist,
        best_match.name,
        best_match.mix_name,
        best_score,
    )

    return BeatportMatch(
        beatport_id=best_match.id,
        bpm=best_match.bpm,
        key=best_match.key,
        genre=best_match.genre,
        subgenre=best_match.subgenre,
        label=best_match.label,
        match_method="fuzzy",
    )
