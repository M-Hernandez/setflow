"""Parser for MixesDB wiki markup tracklists."""

import re
from datetime import date

from pydantic import BaseModel

from app.ingestion.parse_tracklist import ParsedTrack, _LABEL_RE, _REMIX_RE

# Wiki track line: "# [00:08] Artist - Title [Label]"
# Handles [MM], [MM:SS], [HH:MM:SS], [??], or no bracket at all
_WIKI_TRACK_RE = re.compile(
    r"^#\s*(?:\[(\d{1,2}(?::\d{2}){0,2}|\?\?)\]\s*)?(.+)$"
)

# Section header for multi-DJ sets: ";Moguai" or ";Alle Farben = [[link]]"
_SECTION_HEADER_RE = re.compile(r"^;(.+)$")

# Page title: "2024-09-28 - ARTBAT @ Cercle, Fontainebleau"
_PAGE_TITLE_RE = re.compile(
    r"^(\d{4}-\d{2}-\d{2})\s*-\s*(.+?)(?:\s*@\s*(.+))?$"
)

_B2B_RE = re.compile(r"\bb2b\b", re.IGNORECASE)

# Known radio show / podcast keywords in page titles
_RADIO_KEYWORDS = [
    "radio", "podcast", "essential mix", "resident",
    "session", "show", "broadcast",
]


class MixesDBSetMetadata(BaseModel):
    """Metadata extracted from a MixesDB page title and categories."""

    page_title: str
    event_date: date | None = None
    dj_names: list[str]
    venue: str | None = None
    event_name: str | None = None
    is_b2b: bool = False
    set_type: str = "live"


class WikiTrackSection(BaseModel):
    """A section of tracks, optionally attributed to a specific DJ."""

    dj_name: str | None = None
    tracks: list[ParsedTrack]


def _wiki_timestamp_to_seconds(ts: str) -> float:
    """Convert a wiki timestamp to seconds.

    Handles:
      "12"      → 720.0   (minutes only)
      "50:24"   → 3024.0  (MM:SS)
      "1:15:30" → 4530.0  (HH:MM:SS)
      "??"      → -1.0    (unknown)
    """
    if ts == "??":
        return -1.0
    parts = ts.split(":")
    if len(parts) == 1:
        return int(parts[0]) * 60
    if len(parts) == 2:
        return int(parts[0]) * 60 + int(parts[1])
    if len(parts) == 3:
        return int(parts[0]) * 3600 + int(parts[1]) * 60 + int(parts[2])
    raise ValueError(f"Invalid wiki timestamp: {ts}")


def parse_wiki_track_line(line: str, position: int) -> ParsedTrack | None:
    """Parse a single wiki tracklist line into a ParsedTrack.

    Returns None if the line is not a track line (no '#' prefix, section header, etc).
    """
    line = line.strip()
    if not line:
        return None

    match = _WIKI_TRACK_RE.match(line)
    if not match:
        return None

    ts_raw = match.group(1)  # None if no bracket, "??" if unknown
    remainder = match.group(2).strip()

    # Compute timestamp fields
    if ts_raw is None:
        timestamp = ""
        timestamp_seconds = -1.0
    elif ts_raw == "??":
        timestamp = "??"
        timestamp_seconds = -1.0
    else:
        timestamp = ts_raw
        timestamp_seconds = _wiki_timestamp_to_seconds(ts_raw)

    # Split on " - " to separate artist from title (first occurrence)
    separator_idx = remainder.find(" - ")
    if separator_idx == -1:
        return None

    artist = remainder[:separator_idx].strip()
    title_part = remainder[separator_idx + 3:].strip()

    if not artist or not title_part:
        return None

    # Extract [Label] from end (before remix, since label is outermost)
    label = None
    label_match = _LABEL_RE.search(title_part)
    if label_match:
        label = label_match.group(1).strip()
        title_part = title_part[:label_match.start()].strip()

    # Extract (Remix Tag)
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
        timestamp_seconds=timestamp_seconds,
        artist=artist,
        title=title_part,
        remix=remix,
        label=label,
    )


def parse_wiki_tracklist(wikitext: str) -> list[WikiTrackSection]:
    """Parse full wikitext into sections of tracks.

    Splits on ";Header" lines for multi-DJ sets.
    Returns a single WikiTrackSection with dj_name=None for single-DJ sets.
    """
    if not wikitext.strip():
        return []

    sections: list[WikiTrackSection] = []
    current_dj: str | None = None
    current_tracks: list[ParsedTrack] = []
    position = 1

    for line in wikitext.split("\n"):
        line = line.strip()
        if not line:
            continue

        # Check for section header
        header_match = _SECTION_HEADER_RE.match(line)
        if header_match:
            # Save previous section if it has tracks
            if current_tracks:
                sections.append(WikiTrackSection(
                    dj_name=current_dj, tracks=current_tracks
                ))
                current_tracks = []
                position = 1
            dj_name = header_match.group(1).strip()
            # Strip wiki link suffix: ";Alle Farben = [[...]]" → "Alle Farben"
            link_idx = dj_name.find(" = [[")
            if link_idx != -1:
                dj_name = dj_name[:link_idx].strip()
            current_dj = dj_name
            continue

        # Try to parse as a track line
        parsed = parse_wiki_track_line(line, position)
        if parsed is not None:
            current_tracks.append(parsed)
            position += 1

    # Don't forget the last section
    if current_tracks:
        sections.append(WikiTrackSection(
            dj_name=current_dj, tracks=current_tracks
        ))

    return sections


def flatten_tracks(sections: list[WikiTrackSection]) -> list[ParsedTrack]:
    """Flatten multi-DJ sections into a single list with sequential positions."""
    result = []
    pos = 1
    for section in sections:
        for track in section.tracks:
            result.append(track.model_copy(update={"position": pos}))
            pos += 1
    return result


def parse_page_title(title: str) -> MixesDBSetMetadata:
    """Extract date, DJ name(s), venue/event from a MixesDB page title.

    Handles:
      "2024-09-28 - ARTBAT @ Cercle, Fontainebleau"
      "2023-07-01 - Moguai, ARTBAT, Alle Farben - 1LIVE DJ Session"
      "2025-02-21 - Armin van Buuren b2b ARTBAT @ A State Of Trance, Ahoy, Rotterdam"
    """
    title = title.strip()
    is_b2b = bool(_B2B_RE.search(title))

    match = _PAGE_TITLE_RE.match(title)
    if not match:
        # No date prefix — try to extract what we can
        dj_names = _parse_dj_names(title)
        return MixesDBSetMetadata(
            page_title=title,
            dj_names=dj_names,
            is_b2b=is_b2b,
        )

    event_date = date.fromisoformat(match.group(1))
    dj_and_event = match.group(2).strip()
    venue = match.group(3).strip() if match.group(3) else None

    # If no @ venue, check for " - Event Name" pattern
    event_name = None
    if venue is None:
        # "Moguai, ARTBAT, Alle Farben - 1LIVE DJ Session"
        # Split on last " - " to separate DJs from event name
        last_sep = dj_and_event.rfind(" - ")
        if last_sep != -1:
            dj_part = dj_and_event[:last_sep].strip()
            event_name = dj_and_event[last_sep + 3:].strip()
            dj_names = _parse_dj_names(dj_part)
        else:
            dj_names = _parse_dj_names(dj_and_event)
    else:
        dj_names = _parse_dj_names(dj_and_event)

    return MixesDBSetMetadata(
        page_title=title,
        event_date=event_date,
        dj_names=dj_names,
        venue=venue,
        event_name=event_name,
        is_b2b=is_b2b,
    )


def _parse_dj_names(dj_string: str) -> list[str]:
    """Split a DJ string into individual names.

    Handles comma-separated and "b2b" patterns:
      "ARTBAT" → ["ARTBAT"]
      "Moguai, ARTBAT, Alle Farben" → ["Moguai", "ARTBAT", "Alle Farben"]
      "Armin van Buuren b2b ARTBAT" → ["Armin van Buuren", "ARTBAT"]
    """
    # First split on b2b
    parts = _B2B_RE.split(dj_string)
    result = []
    for part in parts:
        # Then split on commas
        for name in part.split(","):
            name = name.strip()
            if name:
                result.append(name)
    return result


def classify_set_type(categories: list[str]) -> str:
    """Map MixesDB category names to set_type values.

    Categories come as "Category:Radio show", "Category:Podcast", etc.
    """
    cats_lower = [c.lower() for c in categories]
    for cat in cats_lower:
        if "guest mix" in cat or "guest_mix" in cat:
            return "guest_mix"
        if "mixtape" in cat:
            return "mixtape"
        if any(kw in cat for kw in _RADIO_KEYWORDS):
            return "radio"
    return "live"
