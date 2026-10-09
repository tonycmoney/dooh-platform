#!/usr/bin/env bash
# Start Postgres, the API (port 8000) and the dashboard (port 5173).
# If a tablet is plugged in over USB, forward its localhost:8000 to this Mac.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"

brew services start postgresql@17 >/dev/null
until pg_isready -q; do sleep 0.5; done

(cd "$ROOT/backend" && uv run alembic upgrade head)

if command -v adb >/dev/null && adb get-state >/dev/null 2>&1; then
  adb reverse tcp:8000 tcp:8000 && echo "Tablet connected: adb reverse tcp:8000 -> Mac:8000"
fi

trap 'kill 0' EXIT
(cd "$ROOT/backend" && uv run uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload) &
(cd "$ROOT/dashboard" && npm run dev -- --host 127.0.0.1) &
echo "Dashboard: http://localhost:5173   API docs: http://localhost:8000/docs"
wait
