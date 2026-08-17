#!/usr/bin/env bash
# One-shot local setup for Stinky OS
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

echo "==> Creating virtualenv"
python3.12 -m venv .venv
source .venv/bin/activate

echo "==> Installing packages"
pip install -U pip
pip install -e "./packages/stinky-core[dev]"
pip install -e "./services/event-log[dev]"

echo "==> Copying .env if missing"
if [[ ! -f .env ]]; then
  cp .env.example .env
  echo "    Created .env from .env.example"
fi

echo "==> Starting infrastructure (Postgres + Redis + MinIO)"
docker compose up -d

echo ""
echo "Done. Next steps:"
echo "  source .venv/bin/activate"
echo "  cd services/event-log && uvicorn event_log.api:app --reload --port 8000"
echo "  open http://localhost:8000/docs"
