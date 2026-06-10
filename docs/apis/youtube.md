# YouTube (via yt-dlp)

**Base URL:** N/A — uses `yt-dlp` library for extraction, not a REST API  
**Auth:** None  
**Docs:** https://github.com/yt-dlp/yt-dlp  
**Rate limit:** No formal limit. We use 2.0s delay between calls.

## Operations used

### Search

Find DJ set videos by search query.

**yt-dlp config:**
| Option | Value |
|--------|-------|
| Search URL | `ytsearch{N}:{dj_name} DJ set` |
| `extract_flat` | `True` (metadata only, no download) |
| `skip_download` | `True` |
| `quiet` | `True` |

**Fields extracted:**
| yt-dlp field | Used for |
|-------------|----------|
| `entries[].id` | Video ID |
| `entries[].title` | Video title |
| `entries[].duration` | Duration (filter: >= 1200s / 20 min) |
| `entries[].url` | Video URL |

### Metadata extraction

Get full metadata for a specific video, primarily the description which contains the tracklist.

**yt-dlp config:**
| Option | Value |
|--------|-------|
| URL | `https://www.youtube.com/watch?v={video_id}` |
| `skip_download` | `True` |
| `quiet` | `True` |

**Fields extracted:**
| yt-dlp field | Used for |
|-------------|----------|
| `title` | Set title |
| `uploader` | Channel name |
| `duration` | Set duration |
| `description` | **Primary data source** — parsed into tracklist by `parse_tracklist.py` |

## Data extracted from description

The description is parsed into `ParsedTrack` objects:
- Timestamp, artist, title, remix tag, label
- Timestamps give transition timing data (track duration = next timestamp - current)

## Notes

- YouTube descriptions are the primary tracklist source for the project.
- Not all DJ set videos have tracklists in descriptions.
- yt-dlp handles YouTube's anti-bot measures better than direct API calls.
- No YouTube Data API key needed.

## Implementation

- **Client:** `backend/app/ingestion/youtube.py`
- **CLI:** `backend/app/ingestion/scrape.py`
