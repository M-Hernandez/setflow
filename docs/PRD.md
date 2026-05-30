# PRD: Setflow — AI DJ Playlist Engine

## Problem Statement

Spotify and Apple Music generate playlists that pick good individual tracks but have no understanding of *flow*. They optimize for "you'll like this song" but not "this song should come after that song." Real DJs sequence tracks as a journey — energy arcs, harmonic mixing, tension and release, subgenre pockets that evolve over time. Current algorithmic playlists feel like shuffled collections, not curated experiences.

As a listener who loves electronic music, I want playlists that feel like a DJ set — where the ordering is intentional, the energy builds and releases, transitions are harmonically sound, and the overall vibe matches a specific persona or mood I describe.

## Solution

Setflow is a web app where users describe what they want in natural language — a vibe, a DJ persona, a mood, a duration — and an AI agent generates an ordered playlist that flows like a real DJ set. The system learns sequencing patterns from thousands of real DJ set tracklists scraped from 1001tracklists, enriched with track metadata from Spotify, subgenre/style tags from Discogs, and deduplicated via MusicBrainz ISRCs.

The core intelligence is **sequence awareness**: three layers of embeddings (track, transition pair, DJ persona) power a RAG-based Claude agent that doesn't just find good tracks but finds good *orderings* — validated against how real DJs actually sequence music. Every transition includes Claude's reasoning. The agent self-evaluates against a 10-metric rubric and iterates before returning results. The finished playlist is pushed directly to the user's Spotify account.

## User Stories

1. As a listener, I want to describe a playlist vibe in natural language (e.g., "dark melodic techno, 2 hours, slow build peaking around track 20"), so that I get a playlist tailored to exactly the experience I want.
2. As a listener, I want to select a DJ persona (e.g., "Solomun style"), so that the generated playlist reflects that DJ's characteristic sequencing patterns, BPM range, and subgenre preferences.
3. As a listener, I want to see example prompts on the input page, so that I understand what kinds of requests the system handles and can get started quickly.
4. As a listener, I want to click an example prompt chip and have it populate the input field, so that I can use or modify a starting point without typing from scratch.
5. As a listener, I want to watch the playlist generate in real time via streaming, so that I can see the agent's progress and reasoning as it builds the playlist.
6. As a listener, I want to see Claude's reasoning for every transition (why track B follows track A), so that I understand the sequencing logic and learn about DJ mixing principles.
7. As a listener, I want to see an energy curve visualization of my generated playlist, so that I can verify the arc matches the vibe I requested (warmup, build, peak, wind-down).
8. As a listener, I want to see eval scores for my generated playlist (BPM smoothness, harmonic correctness, energy fit, etc.), so that I have confidence the playlist is well-constructed.
9. As a listener, I want to click "Re-evaluate" to have the agent revise weak transitions, so that I can improve a playlist that scored low in certain areas without starting over.
10. As a listener, I want to push the generated playlist directly to my Spotify account with one click, so that I can immediately listen to it in Spotify.
11. As a listener, I want the playlist to appear in my Spotify library with a descriptive name and description, so that I can find it later and remember what vibe it was generated for.
12. As a listener, I want tracks that couldn't be found on Spotify to be noted in the playlist description, so that I know if anything is missing and can find alternatives manually.
13. As a listener, I want to specify a duration for my playlist, so that the system generates the right number of tracks for my listening session.
14. As a listener, I want harmonically compatible transitions between tracks, so that the playlist doesn't have jarring key clashes that break the flow.
15. As a listener, I want smooth BPM progressions, so that the energy changes feel natural rather than jarring.
16. As a listener, I want subgenre coherence within segments of the playlist, so that it doesn't randomly jump between minimal deep house and hard techno within a few tracks.
17. As a listener, I want artist variety across the playlist, so that the same artist doesn't appear multiple times in a row.
18. As a developer evaluating the system, I want to generate 100+ playlists and see aggregate eval metrics, so that I can identify failure modes and track improvements across prompt iterations.
19. As a developer evaluating the system, I want holdout validation against real DJ sets, so that I can measure whether generated playlists actually resemble how real DJs sequence tracks.
20. As a developer evaluating the system, I want Claude-as-judge subjective scores covering flow, surprise, coherence, pacing realism, and bookend quality, so that I capture qualitative dimensions that quantitative metrics miss.
21. As a developer iterating on the agent, I want every Claude call and tool call logged to Langfuse, so that I can trace agent behavior and debug tool usage patterns.
22. As a developer, I want the eval framework to auto-score every generated playlist and store results, so that I can track regressions across prompt versions without manual testing.
23. As a recruiter or hiring manager viewing the portfolio, I want a public landing page with an embedded Loom demo, so that I can understand the project in under 2 minutes without needing to authenticate.
24. As a recruiter, I want a scannable README with architecture diagram, demo GIF, and links to detailed docs, so that I can evaluate the technical depth quickly.
25. As a portfolio viewer, I want to read docs on architecture decisions, eval methodology, and prompt iteration history, so that I can assess the developer's engineering judgment beyond the code.

## Implementation Decisions

### Data Sources and Ingestion Pipeline

#### Tracklist Sources (set-level intelligence)

- **1001tracklists** is the primary source for set-level intelligence: track ordering within DJ sets, which DJs play which tracks, venue/date context, and transition patterns. Scraped with `curl_cffi` (mimics browser TLS fingerprints) + `cloudscraper` for Cloudflare bypass, with Playwright as fallback. Cached to `data/cache/` as a one-time data collection effort (not a live pipeline). 10-30 second delays between requests, run overnight.
- **MixesDB** is a supplementary tracklist source accessed via its MediaWiki API. Community-curated, high data quality, explicit completeness categories. No Cloudflare, no rate limiting drama.
- **Mixcloud API** provides tracklists with start times for radio shows and mixes. Free REST API, no auth required for reads. Best for well-documented radio shows (Essential Mix, Drumcode Radio, etc.).
- **djmix dataset** (HuggingFace, mir-aidj) provides a bootstrap corpus of ~89 mixes, 747 tracks, with transition annotations including cue points and transition lengths. Downloaded immediately to validate pipeline before scraping.
- **Set types:** All three formats are ingested — live sets, radio shows, and studio mixtapes — each tagged with `set_type` in the database. Guest mixes on radio shows are filtered out (they represent the guest DJ's sequencing, not the host's).

#### DJ Roster (30 artists, 6 genres)

| Genre | Artists |
|-------|---------|
| **Tech House** | Chris Lake*, PAWSA, Mau P, Luke Dean, Malive |
| **Melodic House & Techno** | Anyma, ARTBAT*, Argy, Cassian, Layton Giordani |
| **House** | HUGEL*, Chris Lorenzo, Prospa, Max Styler, Sidepiece |
| **Progressive House** | Guy J, Hernan Cattaneo*, Spencer Brown, Marsh, Cristoph |
| **Organic / Indie Electronic** | Lane 8*, Rufus Du Sol, Bob Moses, Sebastien Leger, Volen Sentir |
| **Techno (Peak Time / Driving)** | Charlotte de Witte, Adam Beyer*, Space 92, Amelie Lens, Marie Vaunt |

\* = seed DJ for pipeline validation (one per genre). Seed DJs chosen for genre centrality — maximum track overlap with other DJs in their genre.

**Phased scraping:** Start with 6 seed DJs, 5-8 sets each (~40 sets, ~1,000 transitions) to validate the full pipeline. Then scale to 10 sets × 30 artists.

#### Track Resolution

- **Spotify Web API** resolves tracks to Spotify URIs and ISRCs via search. Playlist delivery is a single API call with a list of URIs. **Note:** Spotify deprecated their Audio Features and Audio Analysis endpoints in November 2024 — BPM, key, energy, danceability are no longer available from Spotify for new apps. Spotify is used only for track search, URI lookup, ISRC retrieval, and playlist creation.
- **MusicBrainz** provides ISRC-based deduplication across sources and MusicBrainz Recording IDs (MBIDs) for cross-referencing with AcousticBrainz.
- Track normalization uses a `canonicalize_track()` function with `rapidfuzz` for fuzzy matching across naming variants ("Original Mix", "Remix", label suffixes).

#### Enrichment Pipeline (metadata-only for v1)

Three pre-built datasets provide BPM, key, and subgenre data without scraping or deprecated APIs:

1. **Beatport 10M+ Tracks dataset** (Kaggle, mcfurland) — 10M+ Beatport tracks with genre, subgenre, BPM, key, and label. 4.7M tracks also have Spotify audio features (pre-deprecation snapshot). PostgreSQL dump format, joined via ISRC. ODbL license.
2. **NaturNestAI/electronic-music-knowledge** (HuggingFace) — 18.3M tracks with Discogs style arrays (`styles_json`), subgenre, label, artist, year, and country. Includes an 832-genre taxonomy with BPM ranges and energy levels per genre, plus a genre evolution graph. CC0 license, Parquet format. Source: Discogs April 2026 + Ishkur's Guide to Electronic Music.
3. **AcousticBrainz CSV dumps** — ~29.5M submissions with Essentia-extracted BPM, key, key_scale, and danceability. Keyed by MusicBrainz Recording ID. CC0 license. Project discontinued 2022 but downloads still live — download ASAP.

**API-based gap filling:**
- **Discogs API** provides style tags and label info for tracks not found in the datasets (~60 req/min, `python3-discogs-client`). Track-level resolution via fuzzy matching (~70-80% hit rate), falling back to label-level style tags for unresolved tracks.
- **Label → subgenre lookup table** — a manually curated mapping of ~200-300 top electronic labels to Beatport genres. Labels are the strongest subgenre signal in electronic music (Afterlife → Melodic Techno, Drumcode → Peak Time Techno, Anjunadeep → Progressive House).

**Canonical taxonomy:** Beatport's genre categories are the target taxonomy. All Discogs styles are mapped to Beatport genres via a lookup table. Key Discogs taxonomy gaps: no "Melodic Techno," no "Organic House," no "Afro House" — these are mapped manually.

**Resolution flow:**
```
Tracklist → "Artist - Track Title"
  ├── Spotify Search → ISRC + Spotify URI
  ├── ISRC → Beatport 10M dataset → BPM, key, Beatport genre/subgenre
  ├── fuzzy match → NaturNestAI → Discogs styles, label, subgenre
  ├── ISRC → MusicBrainz → MBID → AcousticBrainz → BPM, key (backup)
  └── Label → lookup table → Beatport genre (fallback)
```

**Estimated coverage:** BPM ~90%+, Key ~85%+, Subgenre ~80%+, Label ~90%+.

#### v2: Audio Analysis (deferred)

In a future phase, audio-based features will supplement metadata:
- **CLAP embeddings** for text-audio alignment (user types "dark minimal techno" → matches audio embeddings). Killer feature for natural language prompts.
- **Essentia discogs-effnet** for 400 Discogs style classifications + 1280-dim audio embeddings.
- **Essentia RhythmExtractor + KeyExtractor** for BPM/key on uncovered tracks.
- Audio source: Deezer previews (still available) or YouTube — not Spotify (previews deprecated).
- Reference: Deej-AI's Track2Vec approach (5-second mel spectrogram slices + TF-IDF weighted CNN aggregation).

### Database Schema

- Tables: `djs`, `sets`, `tracks`, `set_tracks`, `transitions`
- `sets` includes a `set_type` field (`live`, `radio`, `mixtape`) to distinguish sequencing contexts
- `tracks` includes `isrc` and `musicbrainz_id` columns for cross-referencing with enrichment datasets
- `transitions` is derived: consecutive track pairs within a set, the foundation of the transition embedding corpus
- Postgres 16 + pgvector stores both relational data and all embedding vectors in a single instance

### Embedding Strategy (3 Layers)

- **Track embeddings:** structured metadata (BPM, key, energy, subgenre, style, label, artist) concatenated into text, embedded via Voyage `voyage-3`, stored in pgvector. Enables "find tracks similar to X" with structured filters.
- **Transition embeddings:** real DJ track pairs with relational features (BPM delta, Camelot key distance, energy shift, subgenre shift). This is the core RAG corpus — enables "given Track A, what have real DJs played next?" This is the primary differentiator from generic recommendation systems.
- **DJ persona embeddings:** aggregated DJ profiles (typical BPM range, key preferences, subgenre distribution, transition style, energy curve shape) as text, embedded. Enables "generate a playlist that feels like DJ X."
- **Deferred (Layer 4):** set segment embeddings (4-8 track trajectory windows). Will be built if evals indicate arc-level retrieval adds value beyond transition pairs + persona profiles.

### Agent Design

- 5 tools defined as Pydantic input/output schemas with async handlers:
  - `search_tracks` — vector + structured search over track DB
  - `get_transition_candidates` — retrieve DJ-validated next-track candidates from transition embeddings (RAG)
  - `check_harmonic_compatibility` — Camelot wheel distance + verdict
  - `get_persona_style` — persona profile summary
  - `score_playlist` — run eval rubric, return scores, enable self-correction
- Agent loop: parse prompt → get persona → plan energy arc → iteratively fill each slot using search + transition candidates + harmonic checks → score full playlist → revise if below threshold → return final playlist with per-transition reasoning
- Self-correction is a key architectural decision: the agent evaluates its own output and iterates, not just generating once

### Eval Framework (11 Metrics)

- 9 quantitative metrics (all 0-1 normalized): BPM smoothness, harmonic correctness, energy curve fit, persona match, variety entropy, transition fidelity, subgenre drift rate, artist spacing, track placement energy accuracy
- 1 holdout benchmark: set similarity score (track overlap + energy arc similarity vs held-out 20% of real DJ sets)
- 1 Claude-as-judge subjective score: flow, surprise/coherence balance, stylistic track placement, pacing realism, bookend appropriateness

### Playlist Delivery

- Spotify Web API with OAuth PKCE flow
- Tracks already resolved to Spotify URIs during ingestion — playlist creation is a single API call with a list of URIs
- Missing tracks noted in playlist description
- Apple Music deferred to future backlog

### Frontend

- Two-page React + Vite + TypeScript + Tailwind app
- Page 1 (Home): free-form text input + clickable example prompt chips + optional structured assists (persona, duration)
- Page 2 (Results): energy curve visualization (Recharts), track cards with expandable transition reasoning, eval scores, "Re-evaluate" button, "Push to Spotify" button (OAuth flow)
- SSE streaming for real-time agent progress

### Deployment

- Hybrid: public frontend, playlist generation gated behind auth/invite code
- Backend on Railway or Fly.io (Postgres + container), frontend on Vercel
- Loom demo embedded on landing page for unauthenticated visitors

### Observability

- Langfuse (free tier) for LLM call tracing and tool call logging
- loguru for structured application logs

## Testing Decisions

Good tests verify **external behavior through module interfaces**, not internal implementation details. Tests should answer: "given this input, does the module produce the correct output?" — not "does it call this internal method in this order?"

### Modules to test:

**1. Track Normalizer (Ingestion Pipeline)**
- Test `canonicalize_track()` with known variants: "Artist - Track (Original Mix)" vs "Artist - Track" vs "Artist - Track [Label]" should all resolve to the same canonical form
- Test fuzzy matching thresholds: near-matches should merge, distinct tracks should not
- Test ISRC-based deduplication: tracks with the same ISRC from different sources should deduplicate

**2. Spotify Resolver (Ingestion Pipeline)**
- Test track resolution: given a canonical track name, verify correct Spotify ID is returned
- Test fallback behavior: when Spotify search returns no results or low-confidence matches, verify graceful handling
- Test caching: resolved URIs should be cached and not re-fetched

**3. Discogs Enricher (Ingestion Pipeline)**
- Test fuzzy match scoring: verify high-confidence matches return track-level tags, low-confidence falls back to label-level tags
- Test style tag extraction: verify subgenre and label data is correctly parsed from Discogs responses

**4. Retrieval Layer**
- Test `search_tracks`: verify vector search returns relevant tracks and structured filters (BPM range, key, subgenre) correctly narrow results
- Test `get_transition_candidates`: given a track ID, verify returned candidates actually appear as next-tracks in real DJ sets in the database
- Test hybrid search: verify that combining vector similarity with structured filters produces better results than either alone

**5. Eval Framework (Metrics)**
- Test each of the 9 quantitative metrics in isolation with known inputs and expected outputs
- Test BPM smoothness: a playlist with constant BPM should score 1.0; one with wild jumps should score near 0
- Test harmonic correctness: a playlist where every transition is Camelot-adjacent should score 1.0
- Test artist spacing: a playlist with the same artist in consecutive slots should be penalized
- Test subgenre drift rate: a playlist that stays in one subgenre pocket should have low drift; one that jumps every track should have high drift
- Test holdout validation: verify the set similarity score computation against known overlapping/non-overlapping playlists

**6. Agent (Tool Handlers)**
- Test each tool handler in isolation with mock database state
- Test `score_playlist` produces correct metric values for a known playlist
- Test the self-correction loop: verify that when `score_playlist` returns below-threshold scores, the agent re-enters the generation loop
- Test end-to-end: given a prompt and a seeded database, verify the agent produces a valid playlist with reasoning

**7. Spotify Integration**
- Test playlist creation: given a list of Spotify URIs, verify the correct API call is constructed
- Test missing track handling: verify tracks without Spotify URIs are excluded from the playlist and noted in the description
- Test OAuth token refresh: verify expired tokens are refreshed before API calls

**8. Frontend**
- Test prompt input: verify example chips populate the text field
- Test SSE consumption: verify streaming events are correctly parsed and rendered
- Test Spotify push flow: verify OAuth redirect and playlist creation success/error states

### Testing approach
- No prior test art exists in the codebase (greenfield project)
- Backend tests with pytest + pytest-asyncio
- Frontend tests with Vitest + React Testing Library
- Use fixtures for database state; integration tests against a real Postgres instance (not mocks) for retrieval and embedding tests
- Mock external APIs (Spotify, Discogs, MusicBrainz, Voyage, Anthropic) at the HTTP boundary using `respx` or similar

## Out of Scope

- **Real-time audio playback or mixing** — Setflow generates playlists, not live DJ sets. Playback happens in Spotify.
- **Audio generation** — no generated loops, stems, transitions, or bridge audio. The value is in track selection and sequencing.
- **Model training** — uses Claude and Voyage as-is. The work is orchestration, retrieval, and evaluation, not ML research.
- **Apple Music / SoundCloud integration** — Spotify only for v1. Apple Music is in the future backlog.
- **Set segment embeddings (Layer 4)** — deferred until evals indicate value.
- **CLAP or Essentia audio ML models** — deferred to v2. v1 uses metadata-only enrichment from pre-built datasets.
- **Spotify Audio Features / Audio Analysis** — deprecated by Spotify in November 2024. Replaced by Beatport 10M dataset + AcousticBrainz dumps for BPM/key data.
- **Beatport API** — gated partner program, no public access. Using the Kaggle Beatport 10M dataset instead.
- **Audio-based track embeddings** — deferred to v2. Will use CLAP (text-audio alignment) + Essentia discogs-effnet on Deezer/YouTube audio.
- **MCP server** — deferred to future backlog.
- **Mobile-native app** — web-first.
- **Live re-planning ("More Energy" mid-playlist)** — deferred to future backlog.

## Further Notes

- **The transition embedding corpus is the key differentiator.** Every design decision should protect the quality of this data: thorough scraping, careful normalization, rich metadata enrichment. If the transition data is bad, the RAG retrieval is bad, and the playlists won't feel like real DJ sets.
- **Discogs subgenre tags are critical for electronic music.** The difference between "melodic techno" and "hard techno" is the difference between a Solomun set and an Amelie Lens set. Spotify's genre tags are too broad. This enrichment step is worth the extra ingestion complexity.
- **The self-correction loop (agent scoring its own output) is a strong portfolio talking point.** It demonstrates that the system doesn't just generate once and hope — it evaluates, identifies weaknesses, and iterates. This pattern is directly relevant to production AI systems.
- **Holdout validation against real DJ sets is the most compelling eval story.** "I validated generated playlists against held-out real DJ sets and measured track overlap and energy arc similarity" is concrete, rigorous, and grounded — exactly what an interviewer wants to hear.
- **The eval methodology doc (`docs/eval-methodology.md`) is as important as the code.** Articulating *why* you chose each metric and what trade-offs you made demonstrates judgment that code alone cannot show.
- **Pre-built datasets replace deprecated APIs.** Spotify's Audio Features deprecation (Nov 2024) was a forcing function to find better data sources. The Beatport 10M dataset, NaturNestAI electronic-music-knowledge dataset, and AcousticBrainz dumps collectively provide BPM, key, subgenre, and style data for tens of millions of tracks — better coverage than the Spotify API ever offered for electronic music.
- **Beatport's taxonomy is the gold standard for electronic music classification.** Adopted as the canonical genre taxonomy, with Discogs styles mapped to Beatport categories via a curated lookup table.
- **Prior art validates the approach.** The mir-aidj research group (ISMIR 2020) demonstrated that real DJ transitions follow learnable patterns. Deej-AI's Track2Vec showed playlist co-occurrence embeddings work, but our transition embeddings from real DJ sets are a strictly stronger signal — directional, intentional, and metadata-rich.
- **OneTagger** (open-source, Rust) is the closest reference architecture for multi-source track matching (Beatport + Discogs + MusicBrainz). Study its matching logic when building the resolution pipeline.
