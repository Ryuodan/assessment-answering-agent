#!/usr/bin/env bash
# Production-ish start used by the screen session.
# Usage: ./serve.sh [port] [host] [root_path]
#   root_path is the nginx prefix (e.g. /assessment) so FastAPI emits correct
#   /docs and /openapi.json URLs. Leave empty when serving at the domain root.
set -euo pipefail

cd "$(dirname "$0")"

if [ ! -f .env ]; then
  echo "No .env found. Run: cp .env.example .env  (then set GROQ_API_KEY)" >&2
  exit 1
fi

# shellcheck disable=SC1091
source /home/m.sayed/miniconda3/etc/profile.d/conda.sh
conda activate assessment_env

PORT="${1:-8093}"
HOST="${2:-127.0.0.1}"
ROOT_PATH="${3:-}"

ROOT_ARG=()
if [ -n "${ROOT_PATH}" ]; then
  ROOT_ARG=(--root-path "${ROOT_PATH}")
fi

mkdir -p logs
echo "Starting assessment-answer on http://${HOST}:${PORT} (env: assessment_env)"
exec uvicorn src.api:app --host "${HOST}" --port "${PORT}" "${ROOT_ARG[@]}" 2>&1 | tee -a logs/server.log
