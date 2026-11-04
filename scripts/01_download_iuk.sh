#!/usr/bin/env bash
set -euo pipefail
mkdir -p data/raw
PAGE=$(curl -sL "https://www.ukri.org/publications/innovate-uk-funded-projects-since-2004/")
NEW=$(printf '%s' "$PAGE" | grep -oE 'https://www\.ukri\.org/wp-content/uploads/[^"]+ToPresent\.xlsx' | head -1)
OLD=$(printf '%s' "$PAGE" | grep -oE 'https://www\.ukri\.org/wp-content/uploads/[^"]+2015To2016\.xlsx' | head -1)
curl -sL -o data/raw/iuk_2016_to_present.xlsx "$NEW"
curl -sL -o data/raw/iuk_2004_to_2016.xlsx "$OLD"
ls -la data/raw/*.xlsx
