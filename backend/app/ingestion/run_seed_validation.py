"""CLI entry point for the seed DJ validation run.

Usage:
    python -m app.ingestion.run_seed_validation
    python -m app.ingestion.run_seed_validation --report-only
    python -m app.ingestion.run_seed_validation --dj "ARTBAT"
"""

import argparse
import asyncio
import logging
import sys

from app.db import async_session
from app.ingestion.coverage_report import format_report, generate_report
from app.ingestion.ingest_dj import IngestionResult, ingest_dj
from app.ingestion.spotify_client import SpotifyClient, SpotifyRateLimitError

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

SEED_DJS = [
    {"name": "Chris Lake", "genre": "Tech House"},
    {"name": "ARTBAT", "genre": "Melodic House & Techno"},
    {"name": "HUGEL", "genre": "House"},
    {"name": "Hernan Cattaneo", "genre": "Progressive House"},
    {"name": "Lane 8", "genre": "Organic House / Downtempo"},
    {"name": "Adam Beyer", "genre": "Techno"},
]


async def run_ingestion(dj_filter: str | None = None) -> list[IngestionResult]:
    """Run ingestion for seed DJs."""
    djs = SEED_DJS
    if dj_filter:
        djs = [d for d in djs if dj_filter.lower() in d["name"].lower()]
        if not djs:
            logger.error("No seed DJ matches filter '%s'", dj_filter)
            return []

    spotify = SpotifyClient()
    results: list[IngestionResult] = []

    for dj_info in djs:
        logger.info("=" * 60)
        logger.info("Ingesting: %s (%s)", dj_info["name"], dj_info["genre"])
        logger.info("=" * 60)

        try:
            async with async_session() as session:
                async with session.begin():
                    result = await ingest_dj(
                        session,
                        dj_name=dj_info["name"],
                        genre=dj_info["genre"],
                        youtube_limit=8,
                        mixesdb_limit=10,
                        spotify=spotify,
                    )
                    results.append(result)

                    logger.info(
                        "Done: %d sets, %d tracks resolved, %d unresolved, %d transitions",
                        result.sets_persisted,
                        result.tracks_resolved,
                        result.tracks_unresolved,
                        result.transitions_created,
                    )
        except SpotifyRateLimitError as e:
            logger.error(
                "Spotify rate limit hit during %s — skipping remaining DJs. "
                "Resume later with --dj flag. (retry after %ds)",
                dj_info["name"],
                e.retry_after,
            )
            break
        except Exception:
            logger.exception("Failed to ingest %s — continuing with next DJ", dj_info["name"])

    return results


async def run_report() -> str:
    """Generate and return the coverage report."""
    async with async_session() as session:
        report = await generate_report(session)
        return format_report(report)


def main(args: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        description="Run seed DJ validation: ingest 6 DJs and generate coverage report."
    )
    parser.add_argument(
        "--report-only",
        action="store_true",
        help="Skip ingestion, just generate coverage report from existing data",
    )
    parser.add_argument(
        "--dj",
        type=str,
        default=None,
        help="Filter to a specific DJ (partial match)",
    )
    parsed = parser.parse_args(args)

    if not parsed.report_only:
        results = asyncio.run(run_ingestion(dj_filter=parsed.dj))
        print("\n" + "=" * 60)
        print("INGESTION SUMMARY")
        print("=" * 60)
        for r in results:
            print(
                f"  {r.dj_name:25s}  sets={r.sets_persisted:2d}  "
                f"tracks={r.tracks_resolved:4d}  unresolved={r.tracks_unresolved:3d}  "
                f"transitions={r.transitions_created:4d}"
            )

    report = asyncio.run(run_report())
    print("\n" + report)


if __name__ == "__main__":
    main()
