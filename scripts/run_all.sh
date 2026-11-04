#!/usr/bin/env bash
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
