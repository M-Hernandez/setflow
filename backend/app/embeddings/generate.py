"""Track embedding generation pipeline.

Serializes track metadata to text, embeds via Voyage AI voyage-3,
and stores 1024-dim vectors in the tracks.embedding column (pgvector).

Text serialization includes vibe/identity fields only:
artist, title, remix, genre, subgenre, label.

BPM, key, danceability, etc. are excluded — used as structured
SQL filters at query time, not baked into the embedding.

Usage:
    python -m app.embeddings.generate
    python -m app.embeddings.generate --force
    python -m app.embeddings.generate --dry-run
"""

import argparse
import asyncio
import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import async_session
from app.embeddings.voyage import VoyageEmbedder
from app.models import SetTrack, Track

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


def serialize_track(track: Track) -> str:
    """Serialize track metadata to text for embedding.

    Produces strings like:
        "Adam Beyer - Drumcode 001 (Original Mix). Techno / Peak Time Techno. Label: Drumcode."

    Only includes vibe/identity fields. BPM, key, etc. are excluded
    because they're used as structured filters at query time.
    """
    parts = [f"{track.artist} - {track.title}"]

    if track.remix:
        parts[0] += f" ({track.remix})"

    parts[0] += "."

    if track.genre and track.subgenre and track.genre != track.subgenre:
        parts.append(f"{track.genre} / {track.subgenre}.")
    elif track.genre:
        parts.append(f"{track.genre}.")
    elif track.subgenre:
        parts.append(f"{track.subgenre}.")

    if track.label:
        parts.append(f"Label: {track.label}.")

    return " ".join(parts)


async def embed_all_tracks(
    session: AsyncSession,
    *,
    force: bool = False,
    dry_run: bool = False,
) -> int:
    """Embed all linked tracks and store vectors in DB.

    Args:
        session: Database session.
        force: If True, re-embed tracks that already have embeddings.
        dry_run: If True, serialize and log but don't embed or write.

    Returns:
        Number of tracks embedded.
    """
    # Find tracks linked to sets
    linked_ids = select(SetTrack.track_id.distinct())
    query = select(Track).where(Track.id.in_(linked_ids)).order_by(Track.id)

    if not force:
        query = query.where(Track.embedding.is_(None))

    result = await session.execute(query)
    tracks = list(result.scalars().all())

    if not tracks:
        logger.info("No tracks to embed")
        return 0

    logger.info("Embedding %d tracks (force=%s, dry_run=%s)", len(tracks), force, dry_run)

    # Serialize all tracks
    texts = []
    for track in tracks:
        text = serialize_track(track)
        texts.append(text)

    # Log samples
    for i, (track, text) in enumerate(zip(tracks[:3], texts[:3])):
        logger.info("Sample %d (id=%d): %s", i + 1, track.id, text)

    if dry_run:
        logger.info("DRY RUN — would embed %d tracks. Samples above.", len(tracks))
        return 0

    # Embed via Voyage AI
    embedder = VoyageEmbedder()
    embeddings = await embedder.embed_documents(texts)

    # Write embeddings to DB
    for track, embedding in zip(tracks, embeddings):
        track.embedding = embedding

    await session.flush()
    logger.info("Stored %d embeddings", len(embeddings))
    return len(embeddings)


async def run(force: bool = False, dry_run: bool = False) -> int:
    """Run embedding generation with a fresh session."""
    async with async_session() as session:
        async with session.begin():
            count = await embed_all_tracks(session, force=force, dry_run=dry_run)
    return count


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Generate track embeddings via Voyage AI."
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Re-embed tracks that already have embeddings",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Serialize and log but don't embed or write to DB",
    )
    args = parser.parse_args()

    count = asyncio.run(run(force=args.force, dry_run=args.dry_run))
    print(f"\nEmbedded {count} tracks.")


if __name__ == "__main__":
    main()
