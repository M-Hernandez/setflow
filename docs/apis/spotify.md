# Spotify Web API

**Base URL:** `https://api.spotify.com/v1` (via spotipy library)  
**Auth:** Client credentials flow (client ID + secret, no user auth for search)  
**Docs:** https://developer.spotify.com/documentation/web-api  
**Rate limit:** Rolling 30s window, ~180 req/min. We throttle at 2s/request (default), 3s on medium rate limit.

## Endpoints used

### Search (via spotipy)

`GET /v1/search`

**Parameters:**
| Param | Required | Value |
|-------|----------|-------|
| `q` | yes | `"artist:{name} track:{title}"` or `"artist:{name} track:{title} {remix}"` |
| `type` | yes | `"track"` |
| `limit` | yes | `5` |

**Response fields extracted:**
| API field | Track column | Notes |
|-----------|-------------|-------|
| `tracks.items[0].uri` | `spotify_uri` | e.g. `spotify:track:abc123` |
| `tracks.items[0].external_ids.isrc` | `isrc` | International Standard Recording Code |
| `tracks.items[0].duration_ms` | (used in SpotifyResult) | Not stored on Track |
| `tracks.items[0].name` | (used in SpotifyResult) | For logging/debug |
| `tracks.items[0].artists[].name` | (used in SpotifyResult) | Joined with ", " |

## Endpoints available but not used

| Endpoint | Reason |
|----------|--------|
| `/v1/audio-features/{id}` | **Deprecated Nov 2024.** Was primary source for BPM, key, energy, danceability. Now returns empty. |
| `/v1/tracks/{id}` | Could get album/release date, but we get this from GetSongBPM. |
| `/v1/artists/{id}` | Genre data available but we use Beatport/Discogs taxonomy. |
| `/v1/recommendations` | Seed-based recs. Not relevant — we build our own sequencing. |

## Rate limit handling (PR #28)

Tiered circuit breaker:
- **Soft (retry-after <= 60s):** Sleep and resume, 2s throttle.
- **Medium (60-600s):** Sleep, bump throttle to 3s.
- **Hard (>600s or spotipy "Max Retries"):** Circuit breaker opens, disable client for session.

When retries exhausted: skip track, client stays alive.

## Implementation

- **Client:** `backend/app/ingestion/spotify_client.py`
- **Backfill:** `backend/app/ingestion/backfill_spotify.py`
- **Resolution:** Called during `resolve_track()` in `backend/app/ingestion/resolve.py`
