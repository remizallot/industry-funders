#!/usr/bin/env bash
# Full pipeline: download, extract, merge, build. Run from the project folder.
# Inside Docker (recommended): bash scripts/run_in_docker.sh
# Natively: .venv/bin/python replaces python below (see README).
set -euo pipefail
cd "$(dirname "$0")/.."
bash scripts/01_download_iuk.sh
python scripts/02_pull_gtr.py
python scripts/03_extract_iuk.py
python scripts/04_extract_gtr.py
python scripts/06_pull_openalex.py
python scripts/07_scrape_schemes.py
python scripts/08_merge_all.py
python scripts/09_build_explorer.py
cp data/processed/industry-funders.xlsx industry-funders-ranked.xlsx 2>/dev/null || true
cp data/processed/industry-funders-explorer.html industry-funders-explorer.html 2>/dev/null || true
