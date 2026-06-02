"""Derive transitions from consecutive set_tracks pairs.

For each set, walks the ordered set_tracks and creates a Transition row
for each consecutive pair (position N → position N+1). Skips gaps where
tracks are unresolved (missing BPM/key data is fine — those fields are
nullable on Transition).
"""

import logging
from dataclasses import dataclass

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.ingestion.camelot import key_relationship
from app.models import Set, SetTrack, Track, Transition

logger = logging.getLogger(__name__)


@dataclass
class DerivationResult:
    """Summary of a derive_transitions() run."""

    transitions_created: int = 0
    sets_processed: int = 0
    gaps_skipped: int = 0


async def derive_transitions_for_set(
    session: AsyncSession,
    set_id: int,
    *,
    replace: bool = False,
) -> int:
    """Derive transitions for a single set.

    Args:
        session: Database session.
        set_id: The set to process.
        replace: If True, delete existing transitions first (idempotent re-run).
                 If False, skip sets that already have transitions.

    Returns:
        Number of transitions created.
    """
    # Check for existing transitions
    existing = await session.execute(
        select(Transition.id).where(Transition.set_id == set_id).limit(1)
    )
    if existing.scalar_one_or_none() is not None:
        if not replace:
            return 0
        await session.execute(
            delete(Transition).where(Transition.set_id == set_id)
        )

    # Load set_tracks ordered by position, with eager-loaded tracks
    result = await session.execute(
        select(SetTrack)
        .where(SetTrack.set_id == set_id)
        .options(selectinload(SetTrack.track))
        .order_by(SetTrack.position)
    )
    set_tracks = result.scalars().all()

    if len(set_tracks) < 2:
        return 0

    created = 0
    for i in range(len(set_tracks) - 1):
        st_a = set_tracks[i]
        st_b = set_tracks[i + 1]
        track_a: Track = st_a.track
        track_b: Track = st_b.track

        # Skip gaps — consecutive positions only
        if st_b.position != st_a.position + 1:
            continue

        # BPM delta (signed: positive = tempo increase)
        bpm_delta: float | None = None
        if track_a.bpm is not None and track_b.bpm is not None:
            bpm_delta = track_b.bpm - track_a.bpm

        # Key relationship via Camelot wheel
        key_rel = key_relationship(track_a.key, track_b.key)

        # Genre continuity (subgenre match)
        genre_cont: bool | None = None
        if track_a.subgenre is not None and track_b.subgenre is not None:
            genre_cont = track_a.subgenre == track_b.subgenre
        elif track_a.genre is not None and track_b.genre is not None:
            genre_cont = track_a.genre == track_b.genre

        # Track A duration from timestamps
        duration: float | None = None
        if (
            st_a.start_time_seconds is not None
            and st_b.start_time_seconds is not None
        ):
            duration = st_b.start_time_seconds - st_a.start_time_seconds

        transition = Transition(
            set_id=set_id,
            track_a_id=track_a.id,
            track_b_id=track_b.id,
            position=st_a.position,
            bpm_delta=bpm_delta,
            key_relationship=key_rel,
            genre_continuity=genre_cont,
            track_a_duration_seconds=duration,
        )
        session.add(transition)
        created += 1

    await session.flush()
    return created


async def derive_transitions(
    session: AsyncSession,
    *,
    set_ids: list[int] | None = None,
    replace: bool = False,
) -> DerivationResult:
    """Derive transitions for multiple sets.

    Args:
        session: Database session.
        set_ids: Specific set IDs to process. If None, processes all sets.
        replace: If True, replaces existing transitions (idempotent).

    Returns:
        DerivationResult with counts.
    """
    if set_ids is not None:
        ids = set_ids
    else:
        result = await session.execute(select(Set.id))
        ids = [row[0] for row in result.all()]

    dr = DerivationResult()
    for sid in ids:
        created = await derive_transitions_for_set(
            session, sid, replace=replace
        )
        dr.transitions_created += created
        dr.sets_processed += 1

    return dr
