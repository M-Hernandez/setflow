# Deezer API

**Base URL:** `https://api.deezer.com`  
**Auth:** None (public API for this endpoint)  
**Docs:** https://developers.deezer.com  
**Rate limit:** Not documented for this endpoint. We use Semaphore(20).

## Endpoints used

### GET /track/isrc:{ISRC}

Look up a track by ISRC. Returns track metadata including BPM.

**Parameters:**
| Param | Required | Value |
|-------|----------|-------|
| Path: `isrc` | yes | ISRC code (e.g. `USRC11700001`) |

**Response fields extracted:**
| API field | Track column | Notes |
|-----------|-------------|-------|
| `id` | `deezer_id` | Deezer track ID |
| `bpm` | `bpm` | Float. Null or <=0 treated as missing. |

## Endpoints available but not used

| Endpoint | Reason |
|----------|--------|
| `GET /search?q={query}` | Could search by artist+title, but we only call Deezer when we have an ISRC (from Spotify). |
| `GET /track/{id}` | Same data as ISRC lookup. |
| `GET /artist/{id}` | Genre data available but we use Beatport/Discogs taxonomy. |
| `GET /album/{id}` | Album metadata. Not needed. |

## Notes

- Requires ISRC, so only works for tracks that already have Spotify resolution.
- BPM coverage is low for electronic music — Deezer's BPM data is sparse for niche genres.
- No API key needed — fully public endpoint.

## Implementation

- **Client:** `backend/app/ingestion/deezer_lookup.py`
- **Backfill:** `backend/app/ingestion/backfill_enrichment.py --sources deezer`
