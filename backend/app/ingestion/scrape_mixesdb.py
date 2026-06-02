"""CLI entry point for MixesDB tracklist scraping.

Usage:
    python -m app.ingestion.scrape_mixesdb --dj "ARTBAT" --limit 10 --delay 1.5
"""

import argparse
import json
import sys

from app.ingestion.mixesdb import search_mixes, get_page_data
from app.ingestion.parse_wiki_tracklist import (
    classify_set_type,
    flatten_tracks,
    parse_page_title,
    parse_wiki_tracklist,
)


def main(args: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        description="Scrape DJ set tracklists from MixesDB."
    )
    parser.add_argument("--dj", required=True, help="DJ name to search for")
    parser.add_argument(
        "--limit", type=int, default=10, help="Max pages to process (default: 10)"
    )
    parser.add_argument(
        "--delay", type=float, default=1.5, help="Seconds between API calls (default: 1.5)"
    )
    parsed = parser.parse_args(args)

    print(f"Searching MixesDB for '{parsed.dj}'...")
    pages = search_mixes(parsed.dj, limit=parsed.limit, delay=parsed.delay)
    print(f"Found {len(pages)} pages\n")

    total_tracks = 0
    sets_with_tracklist = 0
    all_results = []

    for page in pages:
        title = page["title"]
        print(f"Fetching: {title}")

        page_data = get_page_data(title, delay=parsed.delay)
        wikitext = page_data.get("wikitext", "")
        categories = page_data.get("categories", [])

        sections = parse_wiki_tracklist(wikitext)
        tracks = flatten_tracks(sections)

        metadata = parse_page_title(title)
        metadata.set_type = classify_set_type(categories)

        if tracks:
            sets_with_tracklist += 1
            total_tracks += len(tracks)

        all_results.append({
            "page_title": title,
            "metadata": metadata.model_dump(mode="json"),
            "sections": [
                {
                    "dj_name": s.dj_name,
                    "track_count": len(s.tracks),
                }
                for s in sections
            ],
            "tracks": [t.model_dump() for t in tracks],
        })

    print("\n" + "=" * 60)
    print(json.dumps(all_results, indent=2, ensure_ascii=False))
    print("=" * 60)
    print(f"\nSummary:")
    print(f"  Pages processed: {len(pages)}")
    print(f"  Sets with tracklist: {sets_with_tracklist}")
    print(f"  Total tracks extracted: {total_tracks}")


if __name__ == "__main__":
    main()
