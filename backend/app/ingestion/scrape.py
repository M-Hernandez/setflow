"""CLI entry point for YouTube tracklist scraping.

Usage:
    python -m app.ingestion.scrape --dj "Solomun" --limit 5 --delay 2.0
"""

import argparse
import json
import sys

from app.ingestion.parse_tracklist import parse_tracklist
from app.ingestion.youtube import search_dj_sets, get_video_metadata


def main(args: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        description="Scrape DJ set tracklists from YouTube descriptions."
    )
    parser.add_argument("--dj", required=True, help="DJ name to search for")
    parser.add_argument(
        "--limit", type=int, default=10, help="Max videos to process (default: 10)"
    )
    parser.add_argument(
        "--delay", type=float, default=2.0, help="Seconds between requests (default: 2.0)"
    )
    parsed = parser.parse_args(args)

    print(f"Searching YouTube for '{parsed.dj}' DJ sets...")
    videos = search_dj_sets(parsed.dj, limit=parsed.limit, delay=parsed.delay)
    print(f"Found {len(videos)} videos (>{20} min)\n")

    total_tracks = 0
    sets_with_tracklist = 0
    all_results = []

    for video in videos:
        vid = video["video_id"]
        print(f"Fetching: {video['title']} ({video['duration'] // 60} min)")

        metadata = get_video_metadata(vid, delay=parsed.delay)
        description = metadata.get("description", "")
        tracks = parse_tracklist(description)

        if tracks:
            sets_with_tracklist += 1
            total_tracks += len(tracks)

        all_results.append({
            "video_id": vid,
            "title": video["title"],
            "duration": video["duration"],
            "tracks": [t.model_dump() for t in tracks],
        })

    print("\n" + "=" * 60)
    print(json.dumps(all_results, indent=2, ensure_ascii=False))
    print("=" * 60)
    print(f"\nSummary:")
    print(f"  Videos processed: {len(videos)}")
    print(f"  Sets with tracklist: {sets_with_tracklist}")
    print(f"  Total tracks extracted: {total_tracks}")


if __name__ == "__main__":
    main()
