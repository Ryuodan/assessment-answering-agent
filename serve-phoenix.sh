#!/usr/bin/env bash
# Start the local Phoenix collector with the server settings in .env (plan 044).
# Usage: ./serve-phoenix.sh            (python -m scripts.serve_phoenix --check: what it would start)
#   The deployment runs this in `screen -S phoenix`, next to serve.sh's `assessment`.
set -euo pipefail

cd "$(dirname "$0")"

if [ ! -f .env ]; then
  echo "No .env found. Run: cp .env.example .env" >&2
  exit 1
fi

# The launcher reads .env through src/config.py, never as shell code, and then
# replaces itself with Phoenix from Phoenix's own environment (PHOENIX_EXECUTABLE).
# shellcheck disable=SC1091
source /home/m.sayed/miniconda3/etc/profile.d/conda.sh
conda activate assessment_env
exec python -m scripts.serve_phoenix "$@"
