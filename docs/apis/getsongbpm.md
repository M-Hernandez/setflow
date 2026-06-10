# GetSongBPM API

**Base URL:** `https://api.getsong.co` (NOT `api.getsongbpm.com` — that's behind Cloudflare)  
**Auth:** API key (free, requires backlink to getsongbpm.com)  
**Docs:** https://getsongbpm.com/api  
**Rate limit:** Free tier, no documented limit. We use Semaphore(5).

## Endpoints

### GET /search/?type=song

Search for songs by title. Returns up to ~30 results.

**Parameters:**
| Param | Required | Value |
|-------|----------|-------|
| `api_key` | yes | API key |
| `type` | yes | `"song"` |
| `lookup` | yes | Song title (URL-encoded). Title only — combined "artist title" queries return no results. |

**Response:**
```json
{
  "search": [
    {
      "id": "6W32YN",
      "title": "No Captain",
      "uri": "https://getsongbpm.com/song/no-captain/6W32YN",
      "tempo": "122",
      "time_sig": "4/4",
      "key_of": "F#m",
      "open_key": "4m",
      "danceability": 63,
      "acousticness": 15,
      "artist": {
        "id": "p7g36",
        "name": "Lane 8",
        "uri": "https://getsongbpm.com/artist/lane-8/p7g36",
        "genres": ["electronic"],
        "from": null,
        "mbid": "bd052b81-353a-4bce-8cd8-72ba9d4ce414"
      },
      "album": {
        "title": "Little by Little",
        "uri": "https://getsongbpm.com/album/little-by-little/",
        "year": "2018"
      }
    }
  ]
}
```

**Error response:** `{"search": {"error": "no result"}}`

### GET /search/?type=artist

Search for artists by name.

**Parameters:**
| Param | Required | Value |
|-------|----------|-------|
| `api_key` | yes | API key |
| `type` | yes | `"artist"` |
| `lookup` | yes | Artist name (URL-encoded) |

**Response:**
```json
{
  "search": [
    {
      "id": "p7g36",
      "name": "Lane 8",
      "uri": "https://getsongbpm.com/artist/lane-8/p7g36",
      "genres": ["electronic"],
      "from": null,
      "mbid": "bd052b81-353a-4bce-8cd8-72ba9d4ce414",
      "similar": [
        {
          "id": "vv15",
          "name": "Vincenzo",
          "genres": ["electronic"],
          "from": "DE",
          "mbid": "fba73ef3-fd4c-4a4e-ae5a-d5fb2b95d16e"
        }
      ]
    }
  ]
}
```

### GET /song/?id={id}

Get song detail by GetSongBPM ID. Same fields as song search result but without `album`.

**Parameters:**
| Param | Required | Value |
|-------|----------|-------|
| `api_key` | yes | API key |
| `id` | yes | GetSongBPM song ID |

### GET /artist/?id={id}

Get artist detail by GetSongBPM ID. Includes `similar[]` array.

**Parameters:**
| Param | Required | Value |
|-------|----------|-------|
| `api_key` | yes | API key |
| `id` | yes | GetSongBPM artist ID |

### Invalid types

`type=both` and `type=tempo` return `{"error": "Bad query."}`.

## Fields we extract

| API field | Track column | Notes |
|-----------|-------------|-------|
| `tempo` | `bpm` | String, cast to float. Null or <=0 treated as missing. |
| `key_of` | `key` | Short form ("F#m"), normalized to Beatport format ("F# Minor") |
| `danceability` | `danceability` | 0-100 int. Proxy for energy data (Spotify Audio Features deprecated). |
| `acousticness` | `acousticness` | 0-100 int. Texture signal for transition quality. |
| `album.year` | `release_year` | String, cast to int. Era-aware sequencing. |
| `artist.id` | `getsongbpm_artist_id` | For batch-fetching similar artists in Phase 2. |
| `artist.mbid` | `musicbrainz_id` | MusicBrainz cross-reference. |

## Fields available but not used

| API field | Reason |
|-----------|--------|
| `time_sig` | Electronic music is overwhelmingly 4/4. Low value. |
| `open_key` | Redundant with `key_of`. Deterministic conversion. |
| `artist.genres` | We use Beatport/Discogs taxonomy instead. |
| `artist.from` | Country of origin. Not needed for sequencing. |
| `album.title` | Not needed for track enrichment. |
| `similar[]` (on artist) | Not on song search. Requires separate `/artist/` call. Planned for Phase 2. |

## Implementation

- **Client:** `backend/app/ingestion/getsongbpm_lookup.py`
- **Backfill:** `backend/app/ingestion/backfill_enrichment.py --sources getsongbpm`
- **Search strategy:** Search by title only, match artist from results using exact > substring > first result.
