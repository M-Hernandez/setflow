# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Git workflow

**Never push directly to main.** All work must go through feature branches and pull requests:

1. Create a feature branch from main: `git checkout -b issue-<number>/<short-description>`
2. Commit work to the feature branch
3. Push the branch and open a PR into main
4. Merge via PR (squash or merge commit)

## Project overview

AI DJ Playlist Engine — an AI-powered playlist engine that learns sequencing patterns from real DJ sets and generates playlists with intentional flow. Users describe what they want in natural language (vibe, DJ persona, mood, duration) and Claude generates an ordered playlist where every transition includes reasoning. The core thesis: sequence intelligence — not "what tracks" but "what order, and why."

Built as a portfolio piece for AI engineer roles and as a personal-use tool. Demonstrates: embeddings, RAG, agentic tool use with self-evaluation, multi-source data engineering, and a comprehensive eval framework.

## Architecture

- **Backend:** Python 3.11+ / FastAPI (async) / SQLAlchemy 2.0 + asyncpg / Pydantic v2
- **Database:** Postgres 16 + pgvector (relational + vector data in one store)
- **LLM:** Anthropic Claude API (Sonnet for most calls, Opus for hard reasoning)
- **Embeddings:** Voyage AI (`voyage-3`) stored in pgvector — three layers: track, transition, persona
- **Frontend:** React + Vite + TypeScript + Tailwind, Recharts for energy curve visualization
- **Playlist delivery:** Spotify Web API (create playlists in user's account via OAuth)
- **Data sources:** YouTube descriptions via yt-dlp (primary) + MixesDB MediaWiki API + Mixcloud API for set structure; Beatport 10M dataset (genre-filtered) for BPM/key/subgenre; Spotify API for track resolution (ISRC + URI); Discogs API for gap filling
- **Observability:** Langfuse (free tier) + loguru

**Key architectural property:** The agent produces a canonical playlist with Spotify URIs already resolved during ingestion. Playlist delivery is a single Spotify API call.

## Build plan phases

The project follows phased development defined in `docs/PROJECT_PLAN.md` (gitignored, personal reference):

- **Phase 0** — Foundation: FastAPI scaffold, Postgres+pgvector via docker-compose, test routes, React frontend
- **Phase 1** — Data ingestion: YouTube + MixesDB + Mixcloud tracklist extraction, Beatport 10M genre-filtered loader, Spotify track resolution (ISRC + URI), remix-aware fuzzy matching with rapidfuzz, transition derivation, Discogs gap filling
- **Phase 2** — Embeddings: track embeddings, transition pair embeddings (RAG corpus), DJ persona embeddings in pgvector, hybrid retrieval endpoints
- **Phase 3** — Agent (centerpiece): Claude tool-use loop with 5 tools (search_tracks, get_transition_candidates, check_harmonic_compatibility, get_persona_style, score_playlist), self-correction loop
- **Phase 4** — Spotify playlist delivery: OAuth + playlist creation in user's account
- **Phase 5** — Eval framework: 10 quantitative metrics + Claude-as-judge + holdout validation against real DJ sets
- **Phase 6** — Frontend: prompt input page with example chips, results page with energy curve, transition reasoning, eval scores, re-evaluate button, push-to-Spotify
- **Phase 7** — Ship: deploy hybrid (public frontend, gated generation), Loom demo, docs, README polish

## Commands

```bash
# Database
docker-compose up          # Postgres 16 + pgvector

# Backend
cd backend
pip install -e ".[dev]"    # Install with dev deps (see pyproject.toml)
uvicorn app.main:app --reload  # Dev server

# Frontend
cd frontend
npm install
npm run dev                # Vite dev server

# Ingestion
python -m app.ingestion.scrape --dj solomun --limit 5

# Migrations
alembic upgrade head
alembic revision --autogenerate -m "description"
```

## Key technical decisions

- **pgvector over Pinecone:** keeps everything in one Postgres instance, simpler deployment
- **Voyage over OpenAI embeddings:** higher quality, Anthropic-aligned
- **Transition embeddings as RAG corpus:** embed real DJ track pairs to retrieve DJ-validated transitions, not just similar tracks
- **YouTube-first ingestion:** YouTube descriptions (via yt-dlp) as primary tracklist source — timestamps give transition timing data. MixesDB MediaWiki API as secondary, Mixcloud REST API as tertiary. 1001tracklists deferred to v2 (Cloudflare not worth the cost when 3 easier sources cover all seed DJs)
- **Beatport taxonomy as canonical:** Beatport's genre categories are the target taxonomy; Discogs styles mapped via lookup table
- **Beatport 10M genre-filtered:** Spotify Audio Features deprecated Nov 2024; BPM/key/subgenre comes from Beatport 10M dataset filtered to 6 target genres (~500K-1M rows). NaturNestAI and AcousticBrainz deferred until coverage gaps measured
- **Remix-aware track matching:** parse remix tags as separate field, match base title + remix tag independently to avoid matching wrong version (e.g., Original Mix vs ARTBAT Remix have different BPM/key)
- **Self-correcting agent:** agent scores its own playlist against eval rubric and revises weak transitions before returning results
- **SSE for streaming:** Claude agent thinking + tool calls streamed to React frontend via FastAPI SSE
- **Spotify-first delivery:** tracks resolved to Spotify URIs during ingestion; playlist creation is a single API call

## Known hard problems

- **Track normalization + remix disambiguation:** "Artist - Track (Original Mix)" vs "Artist - Track (ARTBAT Remix)" vs "Artist - Track [Label]" must resolve correctly across YouTube, MixesDB, Spotify, and Beatport. Wrong remix = wrong BPM/key. Uses remix-aware parsing + `rapidfuzz` + ISRC lookup.
- **Beatport dataset coverage:** Dataset is from Sept 2023; newer tracks won't be in it. Discogs API is the fallback for post-2023 releases.
- **Energy data gap:** Spotify energy field deprecated. v1 uses BPM-based heuristic; real energy data deferred to v2 audio analysis.
- **Discogs resolution:** track names won't perfectly match Discogs entries. Fuzzy match for ~70-80% track-level, fall back to label-level style tags for the rest.
- **Agent tool design:** start fine-grained, consolidate as you learn what Claude actually calls. Log every tool call to Langfuse.
- **Defining "good" for evals:** subjective by nature. Document rubric choices and trade-offs in `docs/eval-methodology.md`.

## Production hardening (Phase 7)

Items that are fine for local dev but must be addressed before deploy:

- **CORS:** `backend/app/main.py` uses `allow_origins=["*"]` — restrict to the actual frontend domain
- **Health endpoint:** `backend/app/api/health.py` returns raw DB error strings when degraded — sanitize for production

## Environment variables

See `.env.example`. Required keys: `ANTHROPIC_API_KEY`, `VOYAGE_API_KEY`, `DATABASE_URL`, `SPOTIFY_CLIENT_ID`, `SPOTIFY_CLIENT_SECRET`.

## Current state

**Phase 0 (Foundation) — complete.** All issues closed:
- #2: Postgres 16 + pgvector via docker-compose (PR #7)
- #3: FastAPI scaffold with /health route (PR #8)
- #4: Anthropic + Voyage SDK test routes (PR #9)
- #5: React + Vite + Tailwind frontend (PR #10)

**Phase 1 (Data Ingestion) — issues created.** 8 issues (#11-#18):
- #11: Schema + Alembic migrations
- #12: Beatport 10M genre-filtered loader
- #13: YouTube tracklist scraper + parser
- #14: MixesDB API client + wiki markup parser
- #15: Track resolution pipeline (Spotify → Beatport → Postgres)
- #16: Transition derivation from set_tracks
- #17: Seed DJ validation run (6 DJs, ~40 sets)
- #18: Gap filling (Mixcloud + Discogs)

**Next:** Start with #11 (schema), then #12 + #13 + #14 in parallel.

## Custom skills

Four custom skills live in `.claude/skills/`:

- **`grill-me`** — Stress-test a plan or design through relentless interviewing, walking each branch of the decision tree. Invoke when the user says "grill me" or wants to stress-test a design.
- **`tdd`** — Test-driven development with red-green-refactor loop.
- **`to-issues`** — Break a plan, spec, or PRD into independently-grabbable issues on the project issue tracker.
- **`to-prd`** — Synthesize current conversation context into a PRD and publish to the issue tracker. Does not interview — just synthesizes what's known.

## Saving research and design decisions

When research is conducted or design decisions are made, save findings to **all three places**:

1. **Memory files** — for recall in future conversations
2. **`docs/PRD.md`** — update the relevant section with the decision and rationale
3. **`docs/PROJECT_PLAN.md`** — update the relevant phase or backlog item

This ensures the PRD and project plan stay current as the source of truth, not just memory files.

## Post-merge checklist

After every merge to main, update the following documentation and architecture files to reflect the latest changes:

- **`CLAUDE.md`** — update the "Current state" section with completed issues/PRs and what's next
- **`ARCHITECTURE_NOTES.md`** (gitignored) — update the "Last updated" line, file tree, module descriptions, and "What doesn't exist yet" section
- **`docs/PROJECT_PLAN.md`** (gitignored) — no changes needed unless the plan itself changes
- **Memory files** — update `project_progress.md` to reflect current phase status
