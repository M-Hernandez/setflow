"""Coverage report generator for ingested data.

Queries the DB and produces coverage stats: BPM/key/subgenre/label
percentages per DJ and overall. Evaluates against coverage gates.
"""

import logging
from dataclasses import dataclass, field

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import DJ, Set, SetTrack, Track, Transition

logger = logging.getLogger(__name__)

# Coverage gates — must pass before Phase 2
COVERAGE_GATES = {
    "bpm": 0.90,
    "key": 0.85,
    "subgenre": 0.80,
    "label": 0.90,
}


@dataclass
class DJCoverage:
    """Coverage stats for a single DJ."""

    dj_name: str
    sets: int = 0
    tracks: int = 0
    unique_tracks: int = 0
    transitions: int = 0
    bpm_pct: float = 0.0
    key_pct: float = 0.0
    subgenre_pct: float = 0.0
    label_pct: float = 0.0
    set_types: dict[str, int] = field(default_factory=dict)


@dataclass
class CoverageReport:
    """Full coverage report across all DJs."""

    per_dj: list[DJCoverage] = field(default_factory=list)
    total_sets: int = 0
    total_tracks: int = 0
    total_unique_tracks: int = 0
    total_transitions: int = 0
    overall_bpm_pct: float = 0.0
    overall_key_pct: float = 0.0
    overall_subgenre_pct: float = 0.0
    overall_label_pct: float = 0.0
    gates_passed: dict[str, bool] = field(default_factory=dict)


async def _dj_coverage(session: AsyncSession, dj: DJ) -> DJCoverage:
    """Compute coverage stats for a single DJ."""
    cov = DJCoverage(dj_name=dj.name)

    # Count sets
    sets_result = await session.execute(
        select(Set).where(Set.dj_id == dj.id)
    )
    sets = sets_result.scalars().all()
    cov.sets = len(sets)

    if not sets:
        return cov

    set_ids = [s.id for s in sets]

    # Set type distribution
    for s in sets:
        st = s.set_type.value
        cov.set_types[st] = cov.set_types.get(st, 0) + 1

    # Count tracks (via set_tracks)
    track_count = await session.execute(
        select(func.count()).select_from(SetTrack).where(SetTrack.set_id.in_(set_ids))
    )
    cov.tracks = track_count.scalar() or 0

    # Get unique track IDs for this DJ
    track_ids_result = await session.execute(
        select(SetTrack.track_id.distinct()).where(SetTrack.set_id.in_(set_ids))
    )
    track_ids = [row[0] for row in track_ids_result.all()]
    cov.unique_tracks = len(track_ids)

    if not track_ids:
        return cov

    # Coverage percentages
    for field_name, col in [
        ("bpm_pct", Track.bpm),
        ("key_pct", Track.key),
        ("subgenre_pct", Track.subgenre),
        ("label_pct", Track.label),
    ]:
        has_field = await session.execute(
            select(func.count()).select_from(Track)
            .where(Track.id.in_(track_ids), col.isnot(None))
        )
        count = has_field.scalar() or 0
        setattr(cov, field_name, count / len(track_ids) if track_ids else 0.0)

    # Count transitions
    trans_count = await session.execute(
        select(func.count()).select_from(Transition).where(Transition.set_id.in_(set_ids))
    )
    cov.transitions = trans_count.scalar() or 0

    return cov


async def generate_report(session: AsyncSession) -> CoverageReport:
    """Generate a full coverage report across all DJs."""
    report = CoverageReport()

    # Get all DJs that have sets
    djs_result = await session.execute(
        select(DJ).where(
            DJ.id.in_(select(Set.dj_id.distinct()))
        )
    )
    djs = djs_result.scalars().all()

    for dj in djs:
        cov = await _dj_coverage(session, dj)
        report.per_dj.append(cov)
        report.total_sets += cov.sets
        report.total_tracks += cov.tracks
        report.total_transitions += cov.transitions

    # Overall unique tracks
    all_unique = await session.execute(
        select(func.count()).select_from(Track).where(
            Track.id.in_(select(SetTrack.track_id.distinct()))
        )
    )
    report.total_unique_tracks = all_unique.scalar() or 0

    # Overall coverage percentages
    if report.total_unique_tracks > 0:
        all_track_ids = select(SetTrack.track_id.distinct())
        for field_name, col in [
            ("overall_bpm_pct", Track.bpm),
            ("overall_key_pct", Track.key),
            ("overall_subgenre_pct", Track.subgenre),
            ("overall_label_pct", Track.label),
        ]:
            has_field = await session.execute(
                select(func.count()).select_from(Track)
                .where(Track.id.in_(all_track_ids), col.isnot(None))
            )
            count = has_field.scalar() or 0
            setattr(report, field_name, count / report.total_unique_tracks)

    # Evaluate gates
    report.gates_passed = {
        "bpm": report.overall_bpm_pct >= COVERAGE_GATES["bpm"],
        "key": report.overall_key_pct >= COVERAGE_GATES["key"],
        "subgenre": report.overall_subgenre_pct >= COVERAGE_GATES["subgenre"],
        "label": report.overall_label_pct >= COVERAGE_GATES["label"],
    }

    return report


def format_report(report: CoverageReport) -> str:
    """Format a coverage report as a human-readable string."""
    lines: list[str] = []
    lines.append("=" * 70)
    lines.append("COVERAGE REPORT")
    lines.append("=" * 70)
    lines.append("")

    for cov in report.per_dj:
        lines.append(f"  {cov.dj_name}")
        lines.append(f"    Sets: {cov.sets}  |  Tracks: {cov.tracks} ({cov.unique_tracks} unique)  |  Transitions: {cov.transitions}")
        lines.append(f"    BPM: {cov.bpm_pct:.0%}  |  Key: {cov.key_pct:.0%}  |  Subgenre: {cov.subgenre_pct:.0%}  |  Label: {cov.label_pct:.0%}")
        if cov.set_types:
            types_str = ", ".join(f"{k}: {v}" for k, v in sorted(cov.set_types.items()))
            lines.append(f"    Set types: {types_str}")
        lines.append("")

    lines.append("-" * 70)
    lines.append("TOTALS")
    lines.append(f"  Sets: {report.total_sets}")
    lines.append(f"  Tracks: {report.total_tracks} ({report.total_unique_tracks} unique)")
    lines.append(f"  Transitions: {report.total_transitions}")
    lines.append("")
    lines.append("OVERALL COVERAGE")
    lines.append(f"  BPM:      {report.overall_bpm_pct:6.1%}  (gate: {COVERAGE_GATES['bpm']:.0%})  {'PASS' if report.gates_passed.get('bpm') else 'FAIL'}")
    lines.append(f"  Key:      {report.overall_key_pct:6.1%}  (gate: {COVERAGE_GATES['key']:.0%})  {'PASS' if report.gates_passed.get('key') else 'FAIL'}")
    lines.append(f"  Subgenre: {report.overall_subgenre_pct:6.1%}  (gate: {COVERAGE_GATES['subgenre']:.0%})  {'PASS' if report.gates_passed.get('subgenre') else 'FAIL'}")
    lines.append(f"  Label:    {report.overall_label_pct:6.1%}  (gate: {COVERAGE_GATES['label']:.0%})  {'PASS' if report.gates_passed.get('label') else 'FAIL'}")
    lines.append("=" * 70)

    return "\n".join(lines)
