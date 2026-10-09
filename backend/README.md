# MoneyPrint Backend

FastAPI backend for the MoneyPrint short-video automation platform. Replaces the
MoneyPrinterV2 CLI with a service-oriented architecture: REST API, a provider
abstraction layer with fallback and cost tracking, a relational database, and
(being built) a job queue + multi-agent orchestrator.

Licensed under AGPL-3.0 (inherited from MoneyPrinterV2).

## Layout

```
app/
  core/         settings, enums, encryption, logging
  db/           SQLAlchemy models + session
  schemas/      Pydantic request/response models
  api/          FastAPI routers (health, providers, projects, ...)
  providers/    capability abstraction layer
    base.py       abstract interfaces + request/response types
    registry.py   provider registration + catalog
    router.py     priority ordering, fallback chain, cost accounting
    impl/         concrete providers (Ollama, OpenAI, Anthropic, Nano Banana, KittenTTS)
  services/     cross-cutting business logic (costs, ...)
  workers/      Celery app (pipeline jobs)
alembic/        database migrations
tests/          pytest suite
```

## Local development (SQLite, no containers)

Requires Python 3.12.

```bash
cd backend
py -3.12 -m venv .venv
.venv\Scripts\activate            # Windows
# source .venv/bin/activate       # Unix

pip install -e .                  # or install the pinned deps from pyproject

cp .env.example .env
# Generate an encryption key and paste it into .env:
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"

alembic upgrade head              # create the SQLite schema
uvicorn app.main:app --reload     # serve at http://127.0.0.1:8000
```

Open http://127.0.0.1:8000/docs for the interactive API.

## Full stack (Postgres + Redis + worker)

```bash
# from the repo root
MP_SECRET_ENCRYPTION_KEY=$(python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())") \
  docker compose up --build
```

## Tests

```bash
cd backend
pytest
```

## Configuration

All settings are environment variables prefixed with `MP_` (see `.env.example`).
Key ones:

| Variable | Purpose |
|---|---|
| `MP_DATABASE_URL` | SQLite (dev) or `postgresql+psycopg://...` (prod) |
| `MP_REDIS_URL` | Celery broker/result backend |
| `MP_SECRET_ENCRYPTION_KEY` | Fernet key encrypting provider API keys at rest |
| `MP_LOCAL_API_TOKEN` | Optional bearer token for the dashboard; empty disables auth |
| `MP_MEDIA_ROOT` | Where generated media is written |

Provider API keys are stored **encrypted** and are never returned by the API in
plaintext nor written to logs — only a masked hint (`sk-…AB12`) is exposed.
