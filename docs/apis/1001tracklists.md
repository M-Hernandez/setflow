# 1001Tracklists

**Base URL:** `https://www.1001tracklists.com`  
**Auth:** None for AJAX endpoints; session cookies for export/HTML pages  
**Docs:** None (undocumented AJAX endpoints, discovered via inspection)  
**Rate limit:** Undocumented. robots.txt specifies 8s crawl-delay. 429 responses on aggressive use.  
**Anti-bot:** Cloudflare Turnstile on HTML pages; AJAX endpoints bypass it. robots.txt blocks CPython UA.

**Verified:** 2026-06-09 via curl with browser User-Agent.

## Endpoints — Working (no auth)

### GET /ajax/search_tracklist.php

Search for DJ set tracklists by name.

**Parameters:**
| Param | Required | Value |
|-------|----------|-------|
| `p` | yes | Search query (URL-encoded, e.g. `adam+beyer`) |
| `noIDFieldCheck` | yes | `true` |
| `fixedMode` | yes | `true` |
| `sf` | yes | `p` |

**Headers required:** Browser User-Agent (CPython blocked).

**Response:**
```json
{
  "success": true,
  "data": [
    {
      "object": "tl",
      "properties": {
        "tracklistname": "Adam Beyer @ Drumcode Radio 823 ...",
        "id_tracklist": "647526",
        "id_unique": "bv3y93k",
        "url_name": "Adam Beyer Drumcode Radio 823 ...",
        "is_live": "1"
      }
    }
  ]
}
```

### GET /ajax/search_track.php

Search for individual tracks by name.

**Parameters:** Same as tracklist search (`p`, `noIDFieldCheck`, `fixedMode`, `sf`).

**Response:**
```json
{
  "success": true,
  "data": {
    "2p3kbfvp": {
      "object": "track",
      "properties": {
        "trackname": "No Captain",
        "id_unique": "2p3kbfvp",
        "id_track": "386886",
        "feature": "Polica",
        "fulltrackname": "Lane 8 feat. Polica - No Captain",
        "shorttrackname": "Lane 8 No Captain",
        "id_type": "0",
        "first_played": "2017-10-27",
        "play_count": "26",
        "0": {
          "object": "artist",
          "properties": {
            "artistname": "Lane 8",
            "id_unique": "846fjuw",
            "id_artist": "30887"
          }
        },
        "1": {
          "object": "label",
          "properties": {
            "id_label": "10757",
            "id_unique": "3xhq3dr",
            "labelname": "This Never Happened",
            "shortname": "This Never Happened"
          }
        }
      }
    }
  }
}
```

### GET /ajax/get_medialink.php

Get streaming platform IDs for a track. Returns Spotify, Beatport, Apple Music, Traxsource, SoundCloud links.

**Parameters:**
| Param | Required | Value |
|-------|----------|-------|
| `idObject` | yes | `5` (tracks) |
| `idItem` | yes | 1001TL track ID (numeric, from search results) |

**Response:**
```json
{
  "success": true,
  "data": [
    {
      "source": "1",
      "playerId": "9875391",
      "duration": "316",
      "type": "audio"
    },
    {
      "source": "36",
      "playerId": "598hoZZq4JR6r35UOVHxiv",
      "duration": "316",
      "type": "audio"
    }
  ]
}
```

**Source codes:**
| source | Platform |
|--------|----------|
| `1` | Beatport |
| `2` | Apple Music |
| `4` | Traxsource |
| `10` | SoundCloud |
| `36` | Spotify |

**Spotify playerId is the track ID** — convert to URI: `spotify:track:{playerId}`.

## Endpoints — Blocked or auth-required

### HTML tracklist pages

`GET /tracklist/{id_unique}/{url_name}.html`

**Status:** Blocked by Cloudflare Turnstile. Returns challenge page, no track data.

Contains (when accessible): schema.org `itemprop` microdata (MusicRecording), cue times in milliseconds, track order, genre/label per track.

### POST /ajax/export_data.php

**Status:** Requires authenticated session (`sid` + `uid` cookies).

**Parameters:** `object=tracklist&idTL={id_tracklist}`

Returns full tracklist text export with timestamps.

## Fields we could extract

| Source | Field | Use case |
|--------|-------|----------|
| `search_track` | `id_track` | Key for `get_medialink` lookup |
| `search_track` | `fulltrackname` | Artist + title + featuring |
| `search_track` | `labelname` | Label (often more accurate than Discogs) |
| `search_track` | `first_played` | First known play date |
| `search_track` | `play_count` | Popularity signal for track selection |
| `get_medialink` | Spotify `playerId` | **Direct Spotify URI without search API** |
| `get_medialink` | Beatport `playerId` | Cross-reference with Beatport dataset |
| `get_medialink` | `duration` | Track duration in seconds |

## Immediate opportunity

The `search_track` → `get_medialink` pipeline can improve Spotify URI coverage (currently 58%) **without hitting the Spotify search API**:

1. For each track with NULL `spotify_uri`, search `search_track.php` by title
2. Match artist from results
3. Call `get_medialink.php` with the `id_track`
4. Extract Spotify `playerId` from source=36
5. Set `spotify_uri = f"spotify:track:{playerId}"`

This bypasses Spotify rate limits entirely.

## Full tracklist access (future)

To get full set tracklists (track order, cue times), need one of:
- **Account + session cookies** — CrateDigger approach, uses `/ajax/export_data.php`
- **Headless browser** — Playwright to solve Turnstile CAPTCHA
- **Proxy service** — ScraperAPI, Brightdata to bypass Cloudflare

## Existing tools

| Repo | Stars | Language | Approach |
|------|-------|----------|----------|
| `elte0/1001-tracklists-api` | 52 | Python | itemprop parsing + `get_medialink` |
| `Rouzax/CrateDigger` | 2 | Python | Session-based, `export_data.php`, canary system |
| `conrad-scherb/1001-tracklists-scraper` | 4 | TypeScript | AJAX search + adjacent tracks |
| `haileys/track-explorer` | 4 | Ruby | Co-appearance proximity scoring |

## Implementation

- **Not yet implemented.** Planned for Phase 1 gap filling (Spotify URI improvement) and Phase 2 (transition data).
