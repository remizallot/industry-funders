"""Phase 2: companies that fund or co-author UK university papers in the
School's subfields, from OpenAlex (free API, shared daily budget).

Two routes, both aggregated server-side with group_by so that only a few
hundred cheap requests are needed:

  funder route     for each subfield, the top 200 funders of UK university
                   papers; funders are classified as companies through their
                   ROR record (type "company") or a name heuristic; for each
                   corporate funder, the universities it funded (group_by
                   institution) give company x university paper counts.
  co-author route  papers with a UK university author and a company author,
                   downloaded by cursor with authorships only, give company x
                   university co-authorship counts.

All intermediate responses are cached under data/raw/openalex so reruns
cost nothing. Output: data/processed/openalex_evidence.csv.
"""
import hashlib, json, os, re, sys, time
import pandas as pd, requests, yaml

OA = "https://api.openalex.org"
ROR = "https://api.ror.org/v2/organizations/"
RAW = "data/raw/openalex"
HEADERS = {"User-Agent": "industry-funders-phase2 (academic research tool)"}
# Free key from openalex.org/settings/api; needed for cursor paging. Read from the
# environment or from config/openalex_key.txt (gitignored), never from the code.
API_KEY = os.environ.get("OPENALEX_API_KEY") or (
    open("config/openalex_key.txt").read().strip() if os.path.exists("config/openalex_key.txt") else None)
CFG = yaml.safe_load(open("config/openalex_subfields.yml"))
SUBFIELDS = {str(k): v for k, v in CFG["subfields"].items()}
YEARS = f"{CFG['year_from']}-2026"
MAX_INSTITUTIONS = 25  # skip works with more distinct institutions than this (large consortia)
COMPANY_NAME = re.compile(r"\b(ltd|limited|plc|inc|llc|gmbh|ag|s\.?a\.?|b\.?v\.?|n\.?v\.?|corp|corporation|co\.|company|pharma|pharmaceutical|"
                          r"therapeutics|biosciences|biotech|technologies|industries|holdings|group)\b", re.I)
PUBLIC_NAME = re.compile(r"council|ministry|ministerio|minist|government|foundation|fonds|fondation|stiftung|trust|society|academy|"
                         r"university|universit|college|institute|instituto|agency|agencia|department|commission|programme|program|"
                         r"nhs|national|research|fund\b|charity|hospital|centre|center|association|federation|royal|european|"
                         r"consejo|conselho|deutsche|bundes|generalitat|wellcome|cancer research", re.I)
ACAD = re.compile("|".join(yaml.safe_load(open("config/themes.yml"))["academic_patterns"]), re.I)

os.makedirs(RAW, exist_ok=True)
state_path = os.path.join(RAW, "state.json")
state = json.load(open(state_path)) if os.path.exists(state_path) else {"requests": 0, "cursor": "*", "coauthor_done": False}


def save_state():
    json.dump(state, open(state_path, "w"))


class Budget(Exception):
    pass


def oa_get(path, params, cache_key):
    cp = os.path.join(RAW, "cache", cache_key + ".json")
    if os.path.exists(cp):
        return json.load(open(cp))
    os.makedirs(os.path.dirname(cp), exist_ok=True)
    for attempt in range(5):
        if API_KEY:
            params = {**params, "api_key": API_KEY}
        r = requests.get(f"{OA}/{path}", params=params, headers=HEADERS, timeout=60)
        state["requests"] += 1
        if r.status_code == 200:
            d = r.json()
            json.dump(d, open(cp, "w"))
            save_state()
            return d
        if r.status_code in (401, 429, 402, 403) or "budget" in r.text.lower():
            raise Budget(f"HTTP {r.status_code}: {r.text[:200]}")
        time.sleep(2 ** attempt)
    raise RuntimeError(f"failed {path} {params}")


def ror_type(ror_url):
    rid = ror_url.rsplit("/", 1)[-1]
    cp = os.path.join(RAW, "ror", rid + ".json")
    if os.path.exists(cp):
        d = json.load(open(cp))
    else:
        os.makedirs(os.path.dirname(cp), exist_ok=True)
        r = requests.get(ROR + rid, headers=HEADERS, timeout=30)
        d = r.json() if r.status_code == 200 else {}
        json.dump(d, open(cp, "w"))
        time.sleep(0.2)
    types = d.get("types", [])
    country = ((d.get("locations") or [{}])[0].get("geonames_details") or {}).get("country_code")
    return types, country


def base_filter():
    sf = "|".join(SUBFIELDS)
    return f"authorships.institutions.country_code:GB,authorships.institutions.type:education,publication_year:{YEARS},primary_topic.subfield.id:{sf}"


def funder_route():
    funders = {}
    for sid, name in SUBFIELDS.items():
        d = oa_get("works", {"filter": f"authorships.institutions.country_code:GB,authorships.institutions.type:education,"
                                       f"publication_year:{YEARS},primary_topic.subfield.id:{sid}",
                             "group_by": "funders.id", "per_page": 200}, f"funders_sf{sid}")
        for g in d.get("group_by", []):
            f = funders.setdefault(g["key"], {"name": g["key_display_name"], "n": 0, "subfields": {}})
            f["n"] += g["count"]
            f["subfields"][name] = g["count"]
    print(f"funders seen: {len(funders)}", file=sys.stderr)

    corporate = {}
    for fid, f in funders.items():
        if PUBLIC_NAME.search(f["name"] or "") and not COMPANY_NAME.search(f["name"] or ""):
            continue
        d = oa_get(f"funders/{fid.rsplit('/', 1)[-1]}", {}, f"funder_{fid.rsplit('/', 1)[-1]}")
        types, country = ([], d.get("country_code"))
        ror = d.get("ror") or (d.get("ids") or {}).get("ror")
        if ror:
            types, c2 = ror_type(ror)
            country = country or c2
        is_company = "company" in types or (not types and bool(COMPANY_NAME.search(f["name"] or "")))
        if is_company:
            corporate[fid] = {**f, "ror": ror, "country": country, "via": "ror" if types else "name"}
    print(f"corporate funders: {len(corporate)}", file=sys.stderr)
    json.dump(corporate, open(os.path.join(RAW, "corporate_funders.json"), "w"), indent=1)

    rows = []
    for fid, f in sorted(corporate.items(), key=lambda kv: -kv[1]["n"]):
        d = oa_get("works", {"filter": base_filter() + f",funders.id:{fid.rsplit('/', 1)[-1]}",
                             "group_by": "authorships.institutions.id", "per_page": 200},
                   f"unis_{fid.rsplit('/', 1)[-1]}")
        for g in d.get("group_by", []):
            uni = g["key_display_name"] or ""
            if not ACAD.search(uni):
                continue
            rows.append({"source": "openalex", "evidence_type": "corporate_funder", "company_name": f["name"],
                         "company_ror": f.get("ror"), "company_country": f.get("country"), "university": uni,
                         "university_id": g["key"], "n_papers": g["count"],
                         "subfields": "; ".join(sorted(f["subfields"], key=f["subfields"].get, reverse=True)[:5])})
    return rows


def coauthor_route():
    rows_path = os.path.join(RAW, "coauthor_rows.jsonl")
    if not state.get("coauthor_done") and not API_KEY:
        print("co-author route skipped: set OPENALEX_API_KEY (free key, openalex.org/settings/api) to enable cursor paging",
              file=sys.stderr)
    elif not state.get("coauthor_done"):
        with open(rows_path, "a") as out:
            while state["cursor"]:
                d = oa_get("works", {"filter": base_filter() + ",authorships.institutions.type:company",
                                     "select": "id,publication_year,primary_topic,authorships",
                                     "per_page": 200, "cursor": state["cursor"]},
                           f"coauthor_{hashlib.md5(state['cursor'].encode()).hexdigest()}")
                for w in d.get("results", []):
                    comps, unis = {}, {}
                    n_inst = len({i["id"] for a in w.get("authorships", []) for i in a.get("institutions", [])})
                    if n_inst > MAX_INSTITUTIONS:  # consortium papers are not evidence of a partnership
                        continue
                    for a in w.get("authorships", []):
                        for i in a.get("institutions", []):
                            if i.get("type") == "company":
                                comps[i["id"]] = (i.get("display_name"), i.get("country_code"), i.get("ror"))
                            elif i.get("type") == "education" and i.get("country_code") == "GB":
                                unis[i["id"]] = i.get("display_name")
                    for cid, (cn, cc, cr) in comps.items():
                        for uid, un in unis.items():
                            out.write(json.dumps({"company_name": cn, "company_country": cc, "company_ror": cr,
                                                  "university": un, "university_id": uid,
                                                  "year": w.get("publication_year"),
                                                  "subfield": (w.get("primary_topic") or {}).get("subfield", {}).get("display_name")}) + "\n")
                nxt = d.get("meta", {}).get("next_cursor")
                if nxt == state["cursor"]:
                    raise RuntimeError("cursor did not advance; aborting to avoid a loop")
                state["cursor"] = nxt
                save_state()
                if state["requests"] % 50 == 0:
                    print(f"  coauthor works: {state['requests']} requests so far", file=sys.stderr)
            state["coauthor_done"] = True
            save_state()
    df = pd.read_json(rows_path, lines=True) if os.path.exists(rows_path) else pd.DataFrame()
    if df.empty:
        return []
    g = df.groupby(["company_name", "company_country", "company_ror", "university", "university_id"], dropna=False)
    agg = g.agg(n_papers=("year", "size"), first_year=("year", "min"), last_year=("year", "max"),
                subfields=("subfield", lambda s: "; ".join(s.value_counts().index[:5]))).reset_index()
    agg["source"] = "openalex"; agg["evidence_type"] = "company_coauthor"
    return agg.to_dict("records")


def main():
    rows = []
    try:
        rows += funder_route()
        rows += coauthor_route()
    except Budget as e:
        print(f"OpenAlex budget exhausted after {state['requests']} requests: {e}. Rerun later; cached pages are kept.",
              file=sys.stderr)
    out = pd.DataFrame(rows)
    out.to_csv("data/processed/openalex_evidence.csv", index=False)
    print(f"wrote {len(out)} rows ({state['requests']} requests used)", file=sys.stderr)
    if out.empty:
        return
    print(out.groupby("evidence_type")["company_name"].nunique().to_string(), file=sys.stderr)


if __name__ == "__main__":
    main()
