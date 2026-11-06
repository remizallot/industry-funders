#!/usr/bin/env bash
# Run the full pipeline inside Docker. Needs Docker Desktop running.
# The OpenAlex key is read from config/openalex_key.txt if present.
set -euo pipefail
cd "$(dirname "$0")/.."
docker compose build pipeline
docker compose run --rm pipeline bash scripts/run_all.sh
echo "done: industry-funders-explorer.html and industry-funders-ranked.xlsx refreshed"
