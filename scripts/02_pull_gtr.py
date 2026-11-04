"""Pull the full UKRI Gateway to Research catalogue through the GtR-2 API.

Writes gzipped JSON Lines files under data/raw/gtr/:
  projects.jsonl.gz       one record per project, including organisation links
  organisations.jsonl.gz  one record per organisation (name, regNumber, addresses)
  funds.jsonl.gz          one record per fund (value, dates, funder link)

Resumable: a .progress file per resource records the last completed page.
"""
import argparse, gzip, json, os, sys, time
import requests

BASE = "https://gtr.ukri.org/gtr/api"
HEADERS = {"Accept": "application/vnd.rcuk.gtr.json-v7",
           "User-Agent": "industry-funders-phase1 (academic research; contact via GitHub)"}
RESOURCES = {"projects": "project", "organisations": "organisation", "funds": "fund"}


def get(url, params, retries=6):
    delay = 2
    for attempt in range(retries):
        try:
            r = requests.get(url, params=params, headers=HEADERS, timeout=60)
            if r.status_code == 200:
                return r.json()
            if r.status_code in (429, 500, 502, 503, 504):
                raise RuntimeError(f"HTTP {r.status_code}")
            r.raise_for_status()
        except Exception as e:  # noqa: BLE001
            if attempt == retries - 1:
                raise
            print(f"  retry {attempt + 1} after {e}", file=sys.stderr)
            time.sleep(delay)
            delay = min(delay * 2, 60)


def pull(resource, outdir, size=100, pause=0.3):
    key = RESOURCES[resource]
    out = os.path.join(outdir, f"{resource}.jsonl.gz")
    prog = os.path.join(outdir, f"{resource}.progress")
    start = 1
    if os.path.exists(prog):
        start = int(open(prog).read().strip() or 0) + 1
    mode = "ab" if start > 1 else "wb"
    first = get(f"{BASE}/{resource}", {"q": "*", "s": size, "p": start})
    total_pages = first["totalPages"]
    print(f"{resource}: {first['totalSize']} records, {total_pages} pages, starting at page {start}")
    with gzip.open(out, mode) as fh:
        page = start
        data = first
        while True:
            for rec in data.get(key, []):
                fh.write((json.dumps(rec, separators=(",", ":")) + "\n").encode())
            fh.flush()
            open(prog, "w").write(str(page))
            if page % 50 == 0 or page == total_pages:
                print(f"  {resource} page {page}/{total_pages}", flush=True)
            if page >= total_pages:
                break
            page += 1
            time.sleep(pause)
            data = get(f"{BASE}/{resource}", {"q": "*", "s": size, "p": page})
    print(f"{resource}: done -> {out}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--outdir", default="data/raw/gtr")
    ap.add_argument("--resources", nargs="+", default=["projects", "organisations", "funds"])
    ap.add_argument("--pause", type=float, default=0.3)
    a = ap.parse_args()
    os.makedirs(a.outdir, exist_ok=True)
    for res in a.resources:
        pull(res, a.outdir, pause=a.pause)
