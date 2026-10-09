# MoneyPrint

A modular, multi-agent, multi-provider platform for automated **short-video**
creation, production, and publishing (TikTok, YouTube Shorts, Facebook/Instagram
Reels) — controlled entirely from a web dashboard.

It is the evolution of [MoneyPrinterV2](./MoneyPrinterV2) from a single CLI
script into a service-oriented platform: a REST API, a provider abstraction
layer with fallback and cost tracking, a job queue, a relational database, and a
pipeline of specialized AI agents. The original MoneyPrinterV2 remains in place
and untouched; its proven pieces (the MoviePy compose pipeline, Ollama / KittenTTS
/ Whisper / Nano Banana providers, Post Bridge publishing) are reused by the new
backend.

> Licensed under **AGPL-3.0** (inherited from MoneyPrinterV2). Any networked or
> distributed derivative must publish its source under the same license.

## Architecture

```
frontend/   React + TS + Vite + Tailwind dashboard
backend/    FastAPI API, provider layer, agents, orchestrator, Celery workers
MoneyPrinterV2/   original project (unchanged), reused as a media engine source
docker-compose.yml   api + worker + beat + Postgres + Redis
```

```
Frontend ─▶ Backend API ─▶ Orchestrator ─▶ Agents ─▶ Provider Abstraction Layer
                                                        ├─ LLM   (Ollama, OpenAI, Anthropic, OpenRouter)
                                                        ├─ Image (Nano Banana 2)
                                                        ├─ TTS   (KittenTTS)
                                                        ├─ STT   (Whisper, AssemblyAI)
                                                        └─ Publish (Post Bridge)
```

### Pipeline stages

`idea → research → script → review → storyboard → characters → scenes →
images → videos → voice → music → subtitles → edit → qc → render → publish`

Each stage runs as a tracked job with its own status
(`pending/running/completed/failed/retry/cancelled/waiting_approval`). Run modes:

- **auto** — runs end to end.
- **manual** — pauses for approval after every stage.
- **hybrid** — pauses only at configured gates (default: after script and scenes).

### Key capabilities

- **Provider abstraction** with priority-based **fallback chains** and per-call
  **cost accounting**; API keys are **encrypted at rest** and never returned to
  the frontend or logs.
- **Multi-agent** production: research, script, script reviewer, storyboard,
  scene director, character designer, image, video, voice, subtitle, music,
  editor, QC.
- **Persistent characters** with reusable Character IDs for visual consistency.
- **Projects** (channels/niches) each with their own defaults.
- **Editable, versioned prompts** and **per-agent configuration** from the UI.
- **Batch generation**, **multi-account multi-platform publishing**,
  **scheduling**, **budget limits**, and a **live dashboard**.

## Quick start (local, single-user)

### Backend

```bash
cd backend
py -3.12 -m venv .venv && .venv\Scripts\activate
pip install -e .
cp .env.example .env
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"  # paste into .env
alembic upgrade head
uvicorn app.main:app --reload       # http://127.0.0.1:8000/docs
```

The default execution mode is `thread`, so pipelines run locally without Redis.

### Frontend

```bash
cd frontend
npm install
npm run dev                          # http://localhost:5173
```

### First steps in the dashboard

1. **Settings → Seed defaults** (creates default prompts + agent configs).
2. **Providers** → add at least one LLM, one Image, and one TTS provider.
   (e.g. Ollama for LLM, Nano Banana 2 for Image, KittenTTS for TTS.)
3. **Projects** → create a channel (niche, language, style).
4. **Videos** → enter an idea and click Generate; watch the pipeline run.

## Full stack with Docker (Postgres + Redis + workers)

```bash
export MP_SECRET_ENCRYPTION_KEY=$(python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())")
docker compose up --build
```

## Provider dependencies

The core API runs with no heavy AI deps. Providers that need native packages
(Ollama SDK, KittenTTS, faster-whisper, MoviePy for rendering) are installed only
where the worker that uses them runs. See `backend/pyproject.toml` extras.

## Tests

```bash
cd backend && pytest
```
