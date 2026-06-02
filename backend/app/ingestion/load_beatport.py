"""Load the Beatport 10M Kaggle dataset into the beatport_tracks reference table.

Usage:
    python -m app.ingestion.load_beatport --data-dir data/beatport [--chunk-size 50000]

Requires the dataset to be downloaded and extracted first:
    kaggle datasets download -d mcfurland/10-m-beatport-tracks-spotify-audio-features
"""

import argparse
import sys
import time
from pathlib import Path

import pandas as pd
from sqlalchemy import create_engine, text

from app.config import settings
from app.models import BeatportTrack

# Required CSV files from the Beatport 10M dataset
REQUIRED_FILES = [
    "bp_track.csv",
    "bp_genre.csv",
    "bp_subgenre.csv",
    "bp_key.csv",
    "bp_artist.csv",
    "bp_artist_track.csv",
    "bp_label.csv",
]

DEFAULT_CHUNK_SIZE = 50_000


def make_sync_url(async_url: str) -> str:
    """Convert an asyncpg database URL to a psycopg2 URL for sync operations."""
    return async_url.replace("postgresql+asyncpg://", "postgresql+psycopg2://")


def load_lookup_csv(path: Path, id_col: str, name_col: str) -> dict[int, str]:
    """Load a small lookup CSV into a {id: name} dict."""
    df = pd.read_csv(path)
    return dict(zip(df[id_col].astype(int), df[name_col].astype(str)))


def build_artist_map(
    artist_path: Path,
    artist_track_path: Path,
    chunk_size: int = 100_000,
) -> dict[int, str]:
    """Build a {track_id: "Artist1, Artist2"} map from artist CSVs.

    Loads all artists into memory, then streams artist_track in chunks.
    """
    print("Loading artist names...")
    artists = load_lookup_csv(artist_path, "artist_id", "artist_name")
    print(f"  {len(artists):,} artists loaded")

    print("Building artist-track map...")
    artist_map: dict[int, list[str]] = {}
    rows_processed = 0

    for chunk in pd.read_csv(artist_track_path, chunksize=chunk_size):
        for _, row in chunk.iterrows():
            track_id = int(row["track_id"])
            artist_id = int(row["artist_id"])
            artist_name = artists.get(artist_id, "Unknown")
            if not isinstance(artist_name, str) or artist_name == "nan":
                artist_name = "Unknown"
            if track_id not in artist_map:
                artist_map[track_id] = []
            artist_map[track_id].append(artist_name)
        rows_processed += len(chunk)
        print(f"  {rows_processed:,} artist-track rows processed", end="\r")

    print(f"\n  {len(artist_map):,} tracks have artist mappings")

    # Join artist lists into comma-separated strings
    return {tid: ", ".join(names) for tid, names in artist_map.items()}


def validate_files(data_dir: Path) -> bool:
    """Check that all required CSV files exist."""
    missing = [f for f in REQUIRED_FILES if not (data_dir / f).exists()]
    if missing:
        print(f"ERROR: Missing files in {data_dir}:")
        for f in missing:
            print(f"  - {f}")
        return False
    return True


def main(args: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        description="Load Beatport 10M dataset into the beatport_tracks table."
    )
    parser.add_argument(
        "--data-dir",
        type=Path,
        required=True,
        help="Directory containing extracted Beatport CSV files",
    )
    parser.add_argument(
        "--chunk-size",
        type=int,
        default=DEFAULT_CHUNK_SIZE,
        help=f"Rows per chunk for CSV streaming (default: {DEFAULT_CHUNK_SIZE})",
    )
    parsed = parser.parse_args(args)

    data_dir = parsed.data_dir
    chunk_size = parsed.chunk_size

    if not validate_files(data_dir):
        sys.exit(1)

    start_time = time.time()

    # Step 1: Load lookup tables
    print("\n=== Loading lookup tables ===")
    genres = load_lookup_csv(data_dir / "bp_genre.csv", "genre_id", "genre_name")
    subgenres = load_lookup_csv(data_dir / "bp_subgenre.csv", "subgenre_id", "subgenre_name")
    keys = load_lookup_csv(data_dir / "bp_key.csv", "key_id", "key_name")
    labels = load_lookup_csv(data_dir / "bp_label.csv", "label_id", "label_name")

    print(f"  Genres: {len(genres)}")
    print(f"  Subgenres: {len(subgenres)}")
    print(f"  Keys: {len(keys)}")
    print(f"  Labels: {len(labels)}")

    print(f"\nGenre list:")
    for gid, gname in sorted(genres.items(), key=lambda x: x[1]):
        print(f"  [{gid}] {gname}")

    # Step 2: Build artist map
    print("\n=== Building artist map ===")
    artist_map = build_artist_map(
        data_dir / "bp_artist.csv",
        data_dir / "bp_artist_track.csv",
        chunk_size=chunk_size,
    )

    # Step 3: Create sync engine and load tracks
    print("\n=== Loading tracks into database ===")
    sync_url = make_sync_url(settings.database_url)
    engine = create_engine(sync_url)

    with engine.begin() as conn:
        # Truncate for idempotency
        conn.execute(text("TRUNCATE TABLE beatport_tracks"))
        print("  Truncated beatport_tracks table")

        total_inserted = 0
        for chunk in pd.read_csv(
            data_dir / "bp_track.csv",
            chunksize=chunk_size,
            low_memory=False,
        ):
            rows = []
            for _, row in chunk.iterrows():
                track_id = int(row["track_id"])
                genre_id = row.get("genre_id")
                subgenre_id = row.get("subgenre_id")
                key_id = row.get("key_id")
                label_id = row.get("label_id")

                rows.append({
                    "id": track_id,
                    "name": str(row.get("title", ""))[:500],
                    "mix_name": str(row.get("mix", ""))[:500] if pd.notna(row.get("mix")) else None,
                    "artist": artist_map.get(track_id, "Unknown")[:1000],
                    "label": labels.get(int(label_id), None) if pd.notna(label_id) else None,
                    "isrc": str(row.get("isrc", ""))[:12] if pd.notna(row.get("isrc")) else None,
                    "bpm": int(row["bpm"]) if pd.notna(row.get("bpm")) else None,
                    "key": keys.get(int(key_id), None) if pd.notna(key_id) else None,
                    "genre": genres.get(int(genre_id), "Unknown") if pd.notna(genre_id) else "Unknown",
                    "subgenre": subgenres.get(int(subgenre_id), None) if pd.notna(subgenre_id) else None,
                    "release_date": str(row.get("release_date", ""))[:10] if pd.notna(row.get("release_date")) else None,
                })

            if rows:
                conn.execute(
                    BeatportTrack.__table__.insert(),
                    rows,
                )
                total_inserted += len(rows)
                print(f"  {total_inserted:,} rows inserted", end="\r")

    elapsed = time.time() - start_time
    print(f"\n\n=== Load complete ===")
    print(f"  Total rows: {total_inserted:,}")
    print(f"  Time: {elapsed:.1f}s")

    # Print genre distribution
    print(f"\n=== Genre distribution ===")
    with engine.connect() as conn:
        result = conn.execute(text(
            "SELECT genre, COUNT(*) as cnt FROM beatport_tracks "
            "GROUP BY genre ORDER BY cnt DESC"
        ))
        for row in result:
            print(f"  {row.genre}: {row.cnt:,}")

    engine.dispose()


if __name__ == "__main__":
    main()
