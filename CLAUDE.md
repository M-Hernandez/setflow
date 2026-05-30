# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

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
- **Data sources:** 1001tracklists (set structure) + Spotify API (track metadata) + Discogs (subgenre/style/label) + MusicBrainz (ISRC dedup)
- **Observability:** Langfuse (free tier) + loguru

**Key architectural property:** The agent produces a canonical playlist with Spotify URIs already resolved during ingestion. Playlist delivery is a single Spotify API call.

## Build plan phases

The project follows phased development defined in `PROJECT_PLAN.md`:

- **Phase 0** — Foundation: FastAPI scaffold, Postgres+pgvector via docker-compose, test routes, React frontend
- **Phase 1** — Data ingestion: 1001tracklists scraper, Spotify API metadata, Discogs subgenre/style enrichment, MusicBrainz ISRC dedup, track normalization with rapidfuzz
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
- **Multi-source ingestion:** 1001tracklists + MixesDB + Mixcloud for set structure, pre-built datasets (Beatport 10M, NaturNestAI, AcousticBrainz) for track metadata/enrichment, Discogs API for gap filling
- **Beatport taxonomy as canonical:** Beatport's genre categories are the target taxonomy; Discogs styles mapped via lookup table
- **Pre-built datasets over deprecated APIs:** Spotify Audio Features deprecated Nov 2024; BPM/key/subgenre data comes from Beatport 10M dataset + AcousticBrainz dumps + NaturNestAI dataset instead
- **Self-correcting agent:** agent scores its own playlist against eval rubric and revises weak transitions before returning results
- **SSE for streaming:** Claude agent thinking + tool calls streamed to React frontend via FastAPI SSE
- **Spotify-first delivery:** tracks resolved to Spotify URIs during ingestion; playlist creation is a single API call

## Known hard problems

- **1001tracklists scraping:** Cloudflare-protected, aggressive rate limiting — use `curl_cffi` (mimics browser TLS) + `cloudscraper`, Playwright as fallback. Cache every page to `data/cache/`, 10-30s delays between requests, scrape overnight. One-time data collection, not a live pipeline.
- **Track normalization + multi-source resolution:** "Artist - Track (Original Mix)" vs "Artist - Track" vs "Artist - Track [Label]" must match across 1001tracklists, Spotify, Discogs, and MusicBrainz. Uses `rapidfuzz` + ISRC lookup + manual rules.
- **Discogs resolution:** track names won't perfectly match Discogs entries. Fuzzy match for ~70-80% track-level, fall back to label-level style tags for the rest.
- **Agent tool design:** start fine-grained, consolidate as you learn what Claude actually calls. Log every tool call to Langfuse.
- **Defining "good" for evals:** subjective by nature. Document rubric choices and trade-offs in `docs/eval-methodology.md`.

## Production hardening (Phase 7)

Items that are fine for local dev but must be addressed before deploy:

- **CORS:** `backend/app/main.py` uses `allow_origins=["*"]` — restrict to the actual frontend domain
- **Health endpoint:** `backend/app/api/health.py` returns raw DB error strings when degraded — sanitize for production

## Environment variables

See `.env.example`. Required keys: `ANTHROPIC_API_KEY`, `VOYAGE_API_KEY`, `DATABASE_URL`, `SPOTIFY_CLIENT_ID`, `SPOTIFY_CLIENT_SECRET`.

## Custom skills

Two custom skills live in `skills/`:

- **`grill-me`** — Stress-test a plan or design through relentless interviewing, walking each branch of the decision tree. Invoke when the user says "grill me" or wants to stress-test a design.
- **`to-prd`** — Synthesize current conversation context into a PRD and publish to the issue tracker. Does not interview — just synthesizes what's known.
