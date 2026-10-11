# One image: the FastAPI backend serving the API, uploaded media and the
# built dashboard. Used by Railway (see .railway/railway.ts); runs anywhere Docker does.

# --- Dashboard build ----------------------------------------------------------
FROM node:22-slim AS dashboard
WORKDIR /dashboard
COPY dashboard/package.json dashboard/package-lock.json ./
RUN npm ci
COPY dashboard/ ./
RUN npm run build

# --- Backend ------------------------------------------------------------------
FROM python:3.13-slim-trixie
COPY --from=ghcr.io/astral-sh/uv:0.9 /uv /usr/local/bin/uv

# ffmpeg (with zscale for HDR tone mapping) and pg_dump for daily backups.
# pg_dump comes from the PostgreSQL project's repo so it is at least as new as
# the database server (pg_dump can't dump a newer server).
RUN apt-get update \
 && apt-get install -y --no-install-recommends ca-certificates curl ffmpeg postgresql-common \
 && /usr/share/postgresql-common/pgdg/apt.postgresql.org.sh -y \
 && apt-get install -y --no-install-recommends postgresql-client-18 \
 && rm -rf /var/lib/apt/lists/*

ENV PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    PATH="/app/backend/.venv/bin:$PATH" \
    ENVIRONMENT=production \
    DASHBOARD_DIR=/app/dashboard/dist \
    MEDIA_DIR=/data/media \
    ORIGINALS_DIR=/data/originals \
    BACKUP_DIR=/data/backups

WORKDIR /app/backend
COPY backend/pyproject.toml backend/uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project
COPY backend/ ./
COPY --from=dashboard /dashboard/dist /app/dashboard/dist

EXPOSE 8000
# Apply database migrations, then serve. Railway sets PORT and terminates
# HTTPS in front of the app, passing the client address in X-Forwarded-For.
CMD ["sh", "-c", "alembic upgrade head && exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000} --proxy-headers --forwarded-allow-ips='*' --timeout-keep-alive 75"]
