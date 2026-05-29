# AI DJ Playlist Engine — Project Plan

> An AI-powered playlist engine that learns sequencing patterns from real DJ sets and generates playlists that feel like a curated DJ experience. Spotify's playlists pick good tracks but don't understand *flow* — real DJs sequence tracks as a journey with energy arcs, harmonic mixing, tension and release. This system captures that sequence intelligence.

---

## What we're building

A web app where the user describes what they want in natural language — a vibe, a DJ persona, a mood, a duration — and Claude generates an ordered playlist that flows like a real DJ set. Every transition includes Claude's reasoning for why that track follows the previous one. An eval framework scores playlist quality against 10 quantitative metrics and a structured LLM-as-judge evaluation, validated against held-out real DJ sets. The finished playlist is pushed directly to the user's Spotify account.

**Core thesis:** The differentiator is **sequence intelligence** — not "what tracks" but "what order, and why." The system learns ordering patterns, transition preferences, and energy arc shapes from thousands of real DJ set tracklists and uses that knowledge via embeddings + RAG to generate playlists with intentional flow.

## Why this exists

Portfolio piece for AI engineer roles + a tool for personal use. The project demonstrates:

- **LLM orchestration** — Claude API with tool use, structured outputs, streaming
- **Embeddings + vector search** — Voyage AI + pgvector for track, transition, and persona similarity
- **RAG** — retrieving real DJ-validated transitions as candidates for playlist assembly
- **Agentic patterns** — multi-step playlist generation with tool calls, self-evaluation, and iterative refinement
- **Data engineering** — scraping, multi-source enrichment, normalization, fuzzy matching across messy real-world data
- **Eval systems** — 10-metric rubric, Claude-as-judge, holdout validation against real DJ sets, observability
- **System design** — end-to-end from data ingestion to Spotify playlist delivery

---

## Stack

| Layer | Choice | Rationale |
|---|---|---|
| Language (backend) | Python 3.11+ | Standard for AI/LLM work |
| Backend framework | FastAPI (async) | Modern, typed, fast iteration |
| Database | Postgres 16 + pgvector | Single source of truth for relational + vector data |
| ORM | SQLAlchemy 2.0 + asyncpg | Async-native |
| Models | Pydantic v2 | API contracts + tool schemas |
| LLM | Anthropic Claude API | Sonnet for most calls, Opus for hard reasoning |
| Embeddings | Voyage AI (`voyage-3`) | High quality, Anthropic-aligned |
| Frontend | React + Vite + TypeScript + Tailwind | Fast iteration, recruiter-familiar |
| Charts | Recharts | Energy curves, BPM graphs |
| Playlist delivery | Spotify Web API | Playlist creation via OAuth, mature API |
| Observability | Langfuse (free tier) + loguru | LLM tracing + structured logs |
| Backend deploy | Railway or Fly.io | Easy Postgres + container deploys |
| Frontend deploy | Vercel | One-click React deploys |

---

## Architecture overview

```
┌──────────────────────────────────────────────────────────────┐
│  Frontend (React/Vite/TS)                                    │
│  - Prompt input + example chips  - Playlist results view     │
│  - Energy curve visualization    - Push to Spotify button    │
└──────────────────────┬───────────────────────────────────────┘
                       │ HTTPS + SSE (streaming)
┌──────────────────────▼───────────────────────────────────────┐
│  Backend (FastAPI)                                           │
│                                                              │
│  ┌──────────────┐  ┌──────────────┐  ┌───────────────────┐   │
│  │  Ingestion   │  │  Embeddings  │  │  Agent            │   │
│  │  (1001TL +   │  │  (Voyage +   │  │  (Claude tool     │   │
│  │   Spotify +  │  │   pgvector)  │  │   use + RAG +     │   │
│  │   Discogs)   │  │              │  │   self-eval)       │   │
│  └──────────────┘  └──────────────┘  └───────────────────┘   │
│                                                              │
│  ┌──────────────┐  ┌────────────────────────────────────┐    │
│  │  Eval        │  │  Spotify Integration               │    │
│  │  framework   │  │  - Metadata resolution (Phase 1)   │    │
│  │  (10 metrics │  │  - Playlist creation (Phase 4)     │    │
│  │   + judge)   │  │  - [Apple Music — deferred]        │    │
│  └──────────────┘  └────────────────────────────────────┘    │
└──────────────────────┬───────────────────────────────────────┘
                       │
                  Postgres 16 + pgvector
```

**Key architectural property:** The agent produces a canonical playlist (artist + title + ISRC + Spotify URI). Tracks are resolved to Spotify IDs during ingestion, so playlist delivery is a single API call with URIs already in hand.

---

## Data sources

| Source | What it provides | Phase |
|---|---|---|
| 1001tracklists | Set tracklists — track ordering, DJ attribution, venue/date context, transition patterns | Phase 1 |
| Spotify Web API | BPM, key, energy, duration, popularity, ISRC, Spotify track ID, 30-sec preview URLs | Phase 1 |
| Discogs API | Subgenre/style tags (granular: "minimal deep house" vs "house"), label info | Phase 1 |
| MusicBrainz | ISRC codes for deduplication, canonical track identity | Phase 1 |

**Ingestion pipeline:**
```
1001tracklists → set structure + track names
       ↓
Spotify Search API → resolve to Spotify ID + BPM/key/energy/duration
       ↓
MusicBrainz → ISRC for deduplication
       ↓
Discogs → subgenre, style tags, label
       ↓
Postgres: tracks with rich metadata + set context
```

---

## Repo structure

```
ai-dj/
├── backend/
│   ├── app/
│   │   ├── api/              # FastAPI routes
│   │   ├── agents/           # Claude agent + tool definitions
│   │   ├── embeddings/       # Voyage wrapper + indexing
│   │   ├── ingestion/        # 1001tracklists scraper, Spotify/Discogs/MB clients
│   │   ├── spotify/          # Spotify API integration (metadata + playlist creation)
│   │   ├── eval/             # Rubric metrics + Claude-as-judge
│   │   ├── models/           # Pydantic + SQLAlchemy
│   │   ├── db/               # migrations, pgvector setup
│   │   └── config.py
│   ├── tests/
│   └── pyproject.toml
├── frontend/
│   ├── src/
│   │   ├── components/       # PlaylistView, EnergyCurve, TransitionCard, PromptInput
│   │   ├── pages/            # Home (prompt), Results (playlist + eval + Spotify push)
│   │   └── api/              # backend client
│   └── package.json
├── data/                     # cached scrapes, eval results (gitignored)
├── docs/
│   ├── architecture.md       # diagram + system design
│   ├── eval-methodology.md   # rubric, trade-offs, failure modes
│   └── prompt-iteration.md   # prompts tried + why they changed
├── docker-compose.yml        # Postgres + pgvector for local dev
├── .env.example
└── README.md
```

---

## Embedding strategy

Three embedding layers, each serving a distinct retrieval purpose:

### Layer 1 — Track embeddings
Concatenate structured features + text description into a rich representation:
```
"Subgenre: minimal deep house. BPM: 122. Key: A minor (Camelot 8A).
 Energy: 0.7. Artist: Solomun. Title: Customer Is King.
 Label: Diynamic. Style: melodic, soulful, vocal-driven."
```
Embed with `voyage-3`, store in pgvector. Enables: "find tracks similar to X" with structured filters (BPM range, key compatibility, subgenre).

### Layer 2 — Transition embeddings
Embed *pairs* of consecutive tracks from real DJ sets. Features are relational: BPM delta, Camelot key distance, energy shift, subgenre shift, same-artist flag. Enables: "given Track A, retrieve the best next-track candidates that real DJs have validated." This is the core RAG differentiator — sequence intelligence learned from thousands of real transitions.

### Layer 3 — DJ persona embeddings
Aggregate a DJ's set patterns into a profile vector: typical BPM range, key preferences, subgenre distribution, transition style, energy curve shape. Generated from a text profile derived from their data:
```
"Solomun plays melodic deep house, typical BPM range 120–125,
 prefers harmonic transitions in minor keys, builds slowly
 over 3-hour sets, peaks around hour 2. Labels: Diynamic,
 Innervisions. Avoids hard techno."
```
Enables: "generate a playlist that *feels like* this DJ."

### Deferred — Layer 4: Set segment embeddings
Embed sequences of 4-8 tracks as a single vector capturing trajectory (e.g., "slow build from deep house into peak-time techno"). Deferred until evals indicate whether arc-level retrieval adds value beyond transition pairs + persona profiles.

---

## Agent design

### Tools (5 total)

| Tool | Purpose |
|---|---|
| `search_tracks(vibe, bpm_range, key, energy, persona, exclude)` | Vector + structured search over track DB |
| `get_transition_candidates(current_track_id, energy_target, persona)` | Retrieve real DJ-validated transitions from transition embeddings (RAG) |
| `check_harmonic_compatibility(track_a_id, track_b_id)` | Camelot wheel distance + compatibility verdict |
| `get_persona_style(dj_name)` | Persona embedding summary: BPM range, key preferences, subgenres, transition patterns, energy curve |
| `score_playlist(tracks)` | Run eval rubric and return scores; enables self-correction |

### Agent loop

```
1. Parse user prompt → extract vibe, persona, duration, constraints
2. Get persona style → understand the target profile
3. Plan energy arc based on duration and vibe
4. For each slot in the playlist:
   a. Search tracks matching energy/BPM/key target for this position
   b. Get transition candidates from real DJ data
   c. Verify harmonic compatibility
   d. Place the track with reasoning
5. Score the full playlist
6. If score is below threshold → revise weak transitions and re-score
7. Return final playlist + per-transition reasoning
```

The self-correction loop (steps 5-6) is a key portfolio talking point: the agent evaluates its own output against the eval rubric and iterates before returning results.

---

## Phased build plan

Each phase has: a goal, the skills demonstrated, key tasks, and an exit criterion. Treat exit criteria as "do not move on until this works."

### Phase 0 — Foundation

**Goal:** Skeleton running locally.

- `docker-compose up` brings up Postgres 16 with pgvector extension
- FastAPI scaffold with `/health` route
- Anthropic SDK installed; `/test-claude` route returns a haiku from Claude
- Voyage SDK installed; `/test-embed` returns a vector for input text
- React/Vite frontend running on a separate port, calling `/health`
- `.env.example` documenting required keys: `ANTHROPIC_API_KEY`, `VOYAGE_API_KEY`, `DATABASE_URL`, `SPOTIFY_CLIENT_ID`, `SPOTIFY_CLIENT_SECRET`

**Skills shown:** project setup, async Python, environment management.

**Exit:** Both test routes work, frontend renders, all secrets in env vars.

### Phase 1 — Data ingestion

**Goal:** A clean Postgres database of DJ sets with rich track metadata from multiple sources.

- **1001tracklists scraper:** Use httpx with exponential backoff. Cache every page to `data/cache/`. Scrape DJ tracklist index pages, then each set page, extracting `(set_id, dj, date, venue, ordered_tracks)`. Target: 8-10 DJs, 15-20 sets each (~150-200 sets). DJ selection TBD — will span subgenres (melodic/deep, peak-time techno, groovy/funky, eclectic).
- **Spotify resolution:** For each track, search Spotify API by artist + title (ISRC preferred). Pull BPM, key, energy, duration, popularity, Spotify URI. Cache resolved URIs in Postgres.
- **Discogs enrichment:** Search Discogs API by artist + track, fuzzy match with rapidfuzz. Pull subgenre/style tags and label. Fall back to label-level style tags for unresolved tracks.
- **MusicBrainz deduplication:** Look up ISRC where possible for canonical track identity.
- **Track normalization:** `canonicalize_track()` function handling "Artist - Track (Original Mix)" / "(Remix)" / "[Label]" variants. Uses `rapidfuzz` for fuzzy matching.
- **Schema:** `djs`, `sets`, `tracks`, `set_tracks`, `transitions` (derived: consecutive track pairs within a set).

**Skills shown:** data engineering, multi-source integration, scraping with rate limits, fuzzy matching, schema design.

**Exit:** Query "every track DJ X played in 2024" returns clean, deduplicated results with BPM/key/subgenre/label populated. Discogs style tags present for 70%+ of tracks.

### Phase 2 — Embeddings

**Goal:** Three layers of vector representations in pgvector with hybrid retrieval endpoints.

- **Track embeddings:** Concatenate BPM, key, energy, subgenre, style, label, artist, mood into text → embed with `voyage-3` → store in pgvector.
- **Transition embeddings:** For every consecutive track pair in scraped sets, compute relational features (BPM delta, Camelot distance, energy shift, subgenre shift) → embed → store. This is the RAG corpus.
- **DJ persona embeddings:** Aggregate each DJ's track data into a text profile → embed → store.
- **Retrieval endpoints:** `POST /search/tracks` (vector + structured filters: BPM range, key, subgenre, energy), `POST /search/transitions` (given a track, return DJ-validated next-track candidates).

**Skills shown:** embedding API usage, vector DB, hybrid retrieval (vector + structured filters), multi-layer embedding design.

**Exit:** `POST /search/transitions` with a track ID returns sensible next-track candidates that real DJs have actually played in sequence.

### Phase 3 — The agent (centerpiece)

**Goal:** Claude generates a complete ordered playlist with reasoning per transition, and self-corrects against the eval rubric.

- Define 5 tools as Pydantic input/output schemas with async handlers.
- Wire into Claude tool-use loop using Anthropic SDK.
- Agent receives a natural language prompt and returns a structured `Playlist` Pydantic model with per-transition `reasoning`.
- Self-correction: agent calls `score_playlist` after initial generation, revises weak transitions if score is below threshold, re-scores.
- Stream tool calls and intermediate reasoning to stdout (CLI-testable).
- Add endpoint `POST /generate-playlist`.
- Log every Claude call and tool call to Langfuse.

**Skills shown:** agentic AI, tool use, prompt engineering, self-evaluation loop, structured outputs, observability.

**Exit:** Generate a 30-track playlist via CLI/curl. Output shows: every transition has reasoning, BPM/key are populated, harmonic transitions are correct, self-correction triggered at least once on a low-scoring attempt.

### Phase 4 — Spotify playlist delivery

**Goal:** Push generated playlists directly to the user's Spotify account.

- Spotify OAuth with PKCE flow.
- Create playlist endpoint: takes a generated playlist, creates it in the user's Spotify account with track URIs (already resolved in Phase 1).
- Handle missing tracks: if a canonical track doesn't have a Spotify URI, note it in the playlist description.
- Playlist metadata: name, description (including vibe/persona info), cover image (stretch).

**Skills shown:** OAuth integration, third-party API integration, error handling at system boundaries.

**Exit:** Generate a playlist via the API, push to Spotify, open Spotify and see the playlist with all tracks in order.

### Phase 5 — Eval framework

**Goal:** Automated scoring of every generated playlist with a comprehensive rubric.

**Quantitative metrics (all 0–1 normalized):**

1. **BPM smoothness** — `1 - variance(BPM_deltas) / max_acceptable_variance`
2. **Harmonic correctness** — `% of transitions on Camelot wheel adjacency`
3. **Energy curve fit** — `1 - RMSE(target_curve, actual_curve)`
4. **Persona match** — cosine similarity between generated playlist embedding and persona embedding
5. **Variety entropy** — Shannon entropy over subgenres, artists, and keys
6. **Transition fidelity** — `% of transitions that appear in real DJ sets in the database`
7. **Subgenre drift rate** — average subgenre entropy across sliding windows; measures coherence within segments
8. **Artist spacing** — minimum track distance between repeat artist appearances; penalize clustering
9. **Track placement energy accuracy** — per-track `|track_energy - target_energy_at_position|`, averaged across playlist

**Holdout benchmark:**

10. **Set similarity score** — hold out 20% of scraped sets. Generate playlists with matching persona/duration, measure track overlap and energy arc similarity against real sets.

**Claude-as-judge (structured prompt evaluating):**

11. **Subjective score** — overall flow, surprise vs coherence balance, stylistic track placement, pacing realism (build/release/build patterns vs linear ramp), opening/closing track appropriateness.

**Pipeline:** Every generated playlist is auto-scored and stored. Scores are queryable for regression tracking across prompt iterations.

**Skills shown:** AI evaluation, LLM-as-judge, holdout validation, articulating what "good" means, observability.

**Exit:** Generate 100 playlists, view scores, identify at least one failure mode and document it in `docs/eval-methodology.md`.

### Phase 6 — Frontend

**Goal:** A clean two-page UI for generating and delivering playlists.

**Page 1 — Home (prompt input):**
- Free-form text input as primary interface
- Example prompt chips below the input (clickable, populate the text field):
  - "Late night deep house, 90 minutes, Solomun style"
  - "High energy techno warmup into peak time, 2 hours, like Charlotte de Witte"
  - "Chill Sunday morning, melodic and slow, 1 hour"
- Optional structured assists: persona quick-select, duration picker
- SSE streaming: show agent thinking + tool calls as the playlist generates

**Page 2 — Results:**
- Energy curve visualization (Recharts) showing the playlist's arc
- Scrollable track cards with expandable per-transition reasoning from Claude
- Eval scores summary
- "Re-evaluate" button — re-runs the agent with feedback to improve weak areas
- "Push to Spotify" button — OAuth flow → creates playlist in user's account

**Skills shown:** React, streaming LLM responses, third-party OAuth, data visualization.

**Exit:** Type a prompt, watch the playlist stream in, review reasoning and scores, click re-evaluate and see improvements, push to Spotify and verify the playlist appears.

### Phase 7 — Ship & document

**Goal:** Public URL + portfolio package.

- Deploy backend to Railway or Fly.io (Postgres + container)
- Deploy frontend to Vercel
- Hybrid access: public frontend, playlist generation gated behind auth/invite code
- Loom demo embedded on landing page for unauthenticated visitors
- Record a 2-minute Loom demo:
  1. Type a natural language prompt, watch the playlist generate with reasoning
  2. Show eval scores, point out a failure case and how the system self-corrected
  3. Push to Spotify, show the playlist in the app
  4. Close on architecture diagram + GitHub link
- Write a recruiter-scannable `README.md`: 1-paragraph description, demo GIF, architecture diagram, live URL, Loom link, docs links
- Polish the three docs in `docs/`

**Exit:** Send the link to one friend who is a hiring manager. They get the project in under 2 minutes.

---

## Eval metrics — full reference

### Core metrics (v1)

| # | Metric | Type | Formula / Method |
|---|---|---|---|
| 1 | BPM smoothness | Quantitative | `1 - variance(BPM_deltas) / max_acceptable_variance` |
| 2 | Harmonic correctness | Quantitative | `% of transitions on Camelot wheel adjacency` |
| 3 | Energy curve fit | Quantitative | `1 - RMSE(target_curve, actual_curve)` |
| 4 | Persona match | Quantitative | Cosine similarity: generated playlist embedding vs persona embedding |
| 5 | Variety entropy | Quantitative | Shannon entropy over subgenres, artists, keys |
| 6 | Transition fidelity | Quantitative | `% of transitions found in real DJ set database` |
| 7 | Subgenre drift rate | Quantitative | Average subgenre entropy across sliding windows of size N |
| 8 | Artist spacing | Quantitative | Minimum track distance between repeat artist appearances |
| 9 | Track placement accuracy | Quantitative | Average `\|track_energy - target_energy_at_position\|` |
| 10 | Set similarity (holdout) | Benchmark | Track overlap + energy arc similarity vs held-out real DJ sets |
| 11 | Claude-as-judge | Subjective | Flow, surprise/coherence, stylistic placement, pacing realism, bookends |

### Potential future metrics

- **Pacing realism** — compare energy delta patterns (build/release/build sawtooth) against real DJ sets, not just curve fit
- **Positional appropriateness** — per-track stylistic fit at its position (beyond energy alone)
- **Bookend quality** — explicit scoring of opening track (warmup-appropriate?) and closing track (wind-down?)
- **Key journey** — tonal arc across the full playlist, beyond per-transition Camelot checks

---

## The hard parts (anticipate them)

**1001tracklists scraping.** Aggressive rate limiting. Mitigate: cache every page on disk, slow scraping with random backoff, scrape over multiple days, NEVER hammer. Treat as a one-time data collection effort, not a live pipeline.

**Track normalization + multi-source resolution.** "Solomun - Customer Is King (Original Mix)" vs "Solomun - Customer Is King" vs "Solomun - Customer Is King [Diynamic]" must match across 1001tracklists, Spotify, Discogs, and MusicBrainz. Combine ISRC lookup + `rapidfuzz` + manual rules. **Document this work in detail** — it's the kind of integration grind interviews probe.

**Discogs resolution.** Track names from 1001tracklists won't perfectly match Discogs release entries. Use fuzzy matching for track-level resolution (~70-80% hit rate), fall back to label-level style tags for the rest.

**Tool design for the agent.** Getting Claude to use tools well takes iteration. Log every tool call to Langfuse. Start fine-grained, consolidate as you learn.

**Defining "good" for evals.** Subjective. Make the subjectivity a feature: write `docs/eval-methodology.md` explaining rubric choices and trade-offs. Judgment-articulation is exactly what interviews look for.

**Streaming Claude responses to React.** SSE from FastAPI; consume with `EventSource` on frontend. Test reconnect handling.

---

## Documentation requirements

The codebase is half the portfolio. The other half is docs.

- **`README.md`** — recruiter-scannable in 60 seconds. Includes: project description (1 paragraph), demo GIF, architecture diagram, live URL, Loom demo link, docs links, quick-start for local dev.
- **`docs/architecture.md`** — one diagram + one page of prose. Include rationale for key decisions (why pgvector, why Voyage, why multi-source ingestion, why transition embeddings).
- **`docs/eval-methodology.md`** — your rubric, why you chose each metric, what trade-offs you made, at least one failure mode found and documented.
- **`docs/prompt-iteration.md`** — 3-4 versions of your agent prompt. For each: what failed, what changed, what improved. This single doc tells reviewers more about your AI engineering skill than your code does.

---

## Success criteria

This project is "done enough" for the portfolio when:

- [ ] A public URL serves the working app (generation gated behind auth)
- [ ] Loom demo is embedded on the landing page and linked from README
- [ ] A user can type a natural language prompt and receive a sequenced playlist with per-transition reasoning
- [ ] Generated playlists can be pushed to the user's Spotify account
- [ ] The eval framework scores playlists across 10 quantitative metrics + Claude-as-judge
- [ ] Holdout validation shows measurable similarity to real DJ sets
- [ ] Eval results are available across 100+ generated playlists
- [ ] All three docs (`architecture.md`, `eval-methodology.md`, `prompt-iteration.md`) are written
- [ ] The README is scannable in 60 seconds with a clear demo GIF

---

## What this project does NOT try to do

- **No real-time playback or audio mixing** — this generates playlists, not live DJ sets. Playback happens in Spotify.
- **No audio generation** — no generated loops, stems, or transitions. The value is in track selection and sequencing.
- **No model training** — uses Claude and Voyage as-is. The work is orchestration, retrieval, and evaluation, not ML research.
- **No mobile-native app** — web-first for portability and recruiter access.

---

## Future backlog

Features deferred from v1, to be prioritized based on eval results and personal use:

- [ ] **Set segment embeddings (Layer 4)** — embed 4-8 track windows for arc-level retrieval
- [ ] **CLAP audio embeddings** — multimodal text-to-audio matching via Spotify preview clips
- [ ] **Essentia audio features** — richer audio analysis (danceability, mood, spectral features)
- [ ] **Apple Music integration** — playlist delivery via MusicKit, proving the adapter abstraction
- [ ] **Additional eval metrics** — pacing realism, positional appropriateness, bookend quality, key journey
- [ ] **Live re-planning** — "More Energy" / "Less Energy" buttons that re-run the agent mid-playlist
- [ ] **MCP server** — expose DJ tools to any MCP-compatible client (Claude Desktop, etc.)
