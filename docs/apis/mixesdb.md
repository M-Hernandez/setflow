# MixesDB MediaWiki API

**Base URL:** `https://www.mixesdb.com/w/api.php`  
**Auth:** None (public API)  
**Docs:** Standard MediaWiki API — https://www.mediawiki.org/wiki/API:Main_page  
**Rate limit:** No documented limit. We use 1.5s delay between calls.  
**User-Agent:** `setflow-ingestion/0.1 (DJ set tracklist research)`

## Endpoints used

### GET /api.php?action=query (search)

Search for DJ set pages by name.

**Parameters:**
| Param | Required | Value |
|-------|----------|-------|
| `action` | yes | `"query"` |
| `list` | yes | `"search"` |
| `srsearch` | yes | Search query (e.g. DJ name) |
| `srlimit` | no | Max results (default: 10) |
| `format` | yes | `"json"` |

**Response fields extracted:**
| API field | Used for |
|-----------|----------|
| `query.search[].title` | Page title — parsed for date, DJ name, venue |
| `query.search[].pageid` | Page ID (not stored) |
| `query.search[].snippet` | Preview text (not stored) |

### GET /api.php?action=parse (page content)

Get full wikitext and categories for a set page.

**Parameters:**
| Param | Required | Value |
|-------|----------|-------|
| `action` | yes | `"parse"` |
| `page` | yes | Page title |
| `format` | yes | `"json"` |
| `prop` | yes | `"wikitext\|categories"` |

**Response fields extracted:**
| API field | Used for |
|-----------|----------|
| `parse.wikitext.*` | Raw wikitext — parsed into tracklist by `parse_wiki_tracklist.py` |
| `parse.categories[].* ` | Category names — used to classify set type (live, radio, podcast, etc.) |

## Data extracted from parsed wikitext

The wikitext is parsed into `ParsedTrack` objects:
- Track position, timestamp, artist, title, remix tag, label
- Set metadata: event date, DJ names, venue, B2B flag, set type

## Endpoints available but not used

| Endpoint | Reason |
|----------|--------|
| `action=query&prop=categories` | Get categories without full page parse. We get categories from parse already. |
| `action=query&prop=links` | Internal wiki links. Not needed. |
| `action=query&list=categorymembers` | List all pages in a category. Could be used to find all sets by genre. |

## Implementation

- **Client:** `backend/app/ingestion/mixesdb.py`
- **CLI:** `backend/app/ingestion/scrape_mixesdb.py`
