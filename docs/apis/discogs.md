# Discogs API

**Base URL:** `https://api.discogs.com`  
**Auth:** Optional token (higher rate limit). Header: `Authorization: Discogs token={token}`  
**Docs:** https://www.discogs.com/developers  
**Rate limit:** Authenticated: 60 req/min (1s gap). Unauthenticated: 25 req/min (2.5s gap). We use Semaphore(5).

## Endpoints used

### GET /database/search (track search)

Search for releases matching artist + title.

**Parameters:**
| Param | Required | Value |
|-------|----------|-------|
| `q` | yes | `"{artist} {title}"` |
| `type` | yes | `"release"` |
| `per_page` | yes | `5` |
| Header: `User-Agent` | yes | `SetflowDJEngine/0.1` |

**Response fields extracted:**
| API field | Track column | Notes |
|-----------|-------------|-------|
| `results[0].id` | `discogs_id` | Discogs release ID |
| `results[0].style[]` | `subgenre`, `genre` | Mapped to Beatport taxonomy via `genre_mapping.py` |
| `results[0].label[0]` | `label` | First label from array |

### GET /database/search (label fallback)

When track search misses, search by artist name only for label/genre data.

**Parameters:**
| Param | Required | Value |
|-------|----------|-------|
| `q` | yes | `"{artist}"` |
| `type` | yes | `"release"` |
| `per_page` | yes | `10` |

Same response fields extracted.

## Endpoints available but not used

| Endpoint | Reason |
|----------|--------|
| `GET /releases/{id}` | Full release detail (tracklist, credits, images). Could extract more metadata but not needed for v1. |
| `GET /artists/{id}` | Artist profile with name variations, groups, URLs. Not needed. |
| `GET /masters/{id}` | Master release (groups all versions). Could help with version disambiguation. |
| `GET /database/search?type=master` | Search master releases. Could reduce duplicates. |
| `GET /artists/{id}/releases` | All releases by artist. Could build discography for coverage analysis. |

## Notes

- Discogs uses "styles" (e.g. "Deep House", "Tech House") not "genres" in the Beatport sense. Mapped via `genre_mapping.py`.
- Label fallback: if track-level search misses, we search by artist to at least get label/style from their catalog.
- Fuzzy matching against results to avoid wrong release.

## Implementation

- **Client:** `backend/app/ingestion/discogs_lookup.py`
- **Backfill:** `backend/app/ingestion/backfill_enrichment.py --sources discogs`
