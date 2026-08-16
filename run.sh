#!/usr/bin/env bash
# Start the web interface. Usage: ./run.sh [port]
set -euo pipefail

cd "$(dirname "$0")"

if [ ! -f .env ]; then
  echo "No .env found. Run: cp .env.example .env  (then set GROQ_API_KEY)" >&2
  exit 1
fi

PORT="${1:-8000}"
echo "Starting on http://127.0.0.1:${PORT}"
exec uvicorn src.api:app --reload --port "${PORT}"
