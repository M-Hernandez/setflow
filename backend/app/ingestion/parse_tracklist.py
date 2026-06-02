"""Pure-function tracklist parser for YouTube DJ set descriptions."""

import re

from pydantic import BaseModel

# Timestamp at start of line, with optional numbered prefix (e.g. "1. 00:00")
_TIMESTAMP_RE = re.compile(
    r"^(?:\d+\.\s*)?(\d{1,2}:\d{2}(?::\d{2})?)\s+(.+)$"
)

# Label in square brackets at end of line
_LABEL_RE = re.compile(r"\[([^\]]+)\]\s*$")

# Remix tag in parentheses — keyword allowlist (case-insensitive)
_REMIX_RE = re.compile(
    r"\(([^)]*(?:Remix|Rmx|Mix|Edit|Rework|Remake|Dub|Bootleg|Version|VIP|Flip)[^)]*)\)",
    re.IGNORECASE,
)


class ParsedTrack(BaseModel):
    position: int
    timestamp: str
    timestamp_seconds: float
    artist: str
    title: str
    remix: str | None = None
    label: str | None = None


def timestamp_to_seconds(ts: str) -> float:
    """Convert a timestamp string to seconds.

    Handles M:SS, MM:SS, and HH:MM:SS formats.
    """
    parts = ts.split(":")
    if len(parts) == 2:
        minutes, seconds = parts
        return int(minutes) * 60 + int(seconds)
    elif len(parts) == 3:
        hours, minutes, seconds = parts
        return int(hours) * 3600 + int(minutes) * 60 + int(seconds)
    raise ValueError(f"Invalid timestamp format: {ts}")


def parse_track_line(line: str, position: int) -> ParsedTrack | None:
    """Parse a single line from a tracklist description.

    Returns ParsedTrack if the line matches the expected format, None otherwise.
    """
    line = line.strip()
    if not line:
        return None

    match = _TIMESTAMP_RE.match(line)
    if not match:
        return None

    timestamp = match.group(1)
    remainder = match.group(2).strip()

    # Split on " - " to separate artist from title (first occurrence only)
    separator_idx = remainder.find(" - ")
    if separator_idx == -1:
        return None

    artist = remainder[:separator_idx].strip()
    title_part = remainder[separator_idx + 3:].strip()

    if not artist or not title_part:
        return None

    # Extract [Label] from end
    label = None
    label_match = _LABEL_RE.search(title_part)
    if label_match:
        label = label_match.group(1).strip()
        title_part = title_part[:label_match.start()].strip()

    # Extract (Remix Tag) — only if it matches the keyword allowlist
    remix = None
    remix_match = _REMIX_RE.search(title_part)
    if remix_match:
        remix = remix_match.group(1).strip()
        title_part = (
            title_part[:remix_match.start()] + title_part[remix_match.end():]
        ).strip()

    return ParsedTrack(
        position=position,
        timestamp=timestamp,
        timestamp_seconds=timestamp_to_seconds(timestamp),
        artist=artist,
        title=title_part,
        remix=remix,
        label=label,
    )


def parse_tracklist(description: str) -> list[ParsedTrack]:
    """Parse a YouTube description into a list of tracks.

    Returns an empty list if no tracklist is found.
    """
    tracks = []
    position = 1
    for line in description.split("\n"):
        parsed = parse_track_line(line, position)
        if parsed is not None:
            tracks.append(parsed)
            position += 1
    return tracks
