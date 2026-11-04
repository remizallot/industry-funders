#!/usr/bin/env bash
# Optional stage: classify project themes with a local language model, then
# rebuild the workbook and explorer. Needs Docker Desktop running.
#   bash scripts/run_llm_themes.sh                 default models, up to 3000 chat-model calls
#   bash scripts/run_llm_themes.sh --max-llm 500   fewer chat-model calls (faster)
#   bash scripts/run_llm_themes.sh --max-llm 0     embeddings only
# Rerunning is cheap: answers are cached in data/processed/llm_cache.jsonl.
set -euo pipefail
cd "$(dirname "$0")/.."
docker compose up -d ollama
echo "waiting for the model server"
for i in $(seq 1 60); do curl -sf http://localhost:11434/api/tags >/dev/null && break; sleep 2; done
docker compose run --rm pipeline python scripts/10_classify_llm.py "$@"
docker compose run --rm pipeline python scripts/08_merge_all.py
docker compose run --rm pipeline python scripts/09_build_explorer.py
cp data/processed/industry-funders.xlsx industry-funders-ranked.xlsx
cp data/processed/industry-funders-explorer.html industry-funders-explorer.html
echo "done: industry-funders-explorer.html and industry-funders-ranked.xlsx refreshed"
