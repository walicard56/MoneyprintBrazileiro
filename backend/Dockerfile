FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# System deps kept minimal; media/engine deps are installed in the engine image.
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml ./
# Install only runtime deps (no engine extras) for the API/worker image.
RUN pip install \
    "fastapi==0.115.6" "uvicorn[standard]==0.34.0" "pydantic==2.10.4" \
    "pydantic-settings==2.7.1" "sqlalchemy==2.0.36" "alembic==1.14.0" \
    "celery==5.4.0" "redis==5.2.1" "cryptography==44.0.0" "httpx==0.28.1" \
    "python-multipart==0.0.20" "tenacity==9.0.0" "psycopg[binary]==3.2.3"

COPY . .

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
