"""Build a self-contained HTML explorer for the ranked list.

Reads data/processed/master.csv and data/processed/evidence.csv, embeds a
compact JSON payload into scripts/explorer_template.html and writes
data/processed/industry-funders-explorer.html (also copied to the project
root). Open the file in a browser; no server is needed.
"""
import base64, json, os, shutil, sys
import pandas as pd, yaml

THEMES = yaml.safe_load(open("config/themes.yml"))["themes"]
THEME_KEYS = list(THEMES)
ISO = {"GB": "United Kingdom", "US": "United States", "DE": "Germany", "FR": "France", "CH": "Switzerland", "NL": "Netherlands",
       "BE": "Belgium", "DK": "Denmark", "SE": "Sweden", "NO": "Norway", "FI": "Finland", "IE": "Ireland", "ES": "Spain",
       "IT": "Italy", "PT": "Portugal", "AT": "Austria", "CZ": "Czechia", "HU": "Hungary", "LU": "Luxembourg", "IS": "Iceland",
       "JP": "Japan", "KR": "South Korea", "CN": "China", "HK": "Hong Kong", "IN": "India", "IL": "Israel", "SA": "Saudi Arabia",
       "QA": "Qatar", "AE": "United Arab Emirates", "TH": "Thailand", "AU": "Australia", "NZ": "New Zealand", "CA": "Canada",
       "BR": "Brazil", "ZA": "South Africa", "SG": "Singapore", "TW": "Taiwan", "MX": "Mexico", "AR": "Argentina", "PL": "Poland"}
TYPE_CODES = {"studentship": "S", "fellowship": "F", "ktp": "K", "scheme_partner": "P", "research_grant": "G",
              "innovate_uk": "I", "corporate_funder": "A", "company_coauthor": "C"}


def main():
    master = pd.read_csv("data/processed/master.csv", dtype={"crn": str})
    ev = pd.read_csv("data/processed/evidence.csv", low_memory=False, dtype={"company_key": str, "company_crn": str})
    master["key"] = master.apply(lambda r: r["crn"] if isinstance(r["crn"], str) and r["crn"].strip() else None, axis=1)
    # company_key in evidence is the CRN where known, else the normalised name; rebuild the same key for master rows
    keys = ev.groupby("company_key")["company_name"].agg(lambda s: s.value_counts().index[0])
    name_to_key = {v: k for k, v in keys.items()}
    master["key"] = master["company"].map(name_to_key)
    master = master.dropna(subset=["key"])

    unis = sorted(ev["university"].dropna().astype(str).unique())
    uni_idx = {u: i for i, u in enumerate(unis)}
    ev["scheme"] = ev["scheme"].where(ev["source"] != "innovate_uk",
                                      ev["evidence_type"].map({"ktp": "Innovate UK (KTP)"}).fillna("Innovate UK"))
    ev.loc[ev["source"] == "openalex", "scheme"] = "OpenAlex"
    ev.loc[ev["year"] < 2004, "year"] = pd.NA
    schemes = sorted(ev["scheme"].dropna().astype(str).unique())
    scheme_idx = {u: i for i, u in enumerate(schemes)}

    def theme_mask(t):
        if not isinstance(t, str):
            return 0
        return sum(1 << THEME_KEYS.index(k) for k in t.split(";") if k in THEME_KEYS)

    companies = []
    key_pos = {}
    for i, r in enumerate(master.itertuples(index=False)):
        key_pos[r.key] = i
        companies.append([r.company, r.org_type, ISO.get(r.country, r.country) if isinstance(r.country, str) else "",
                          int(bool(r.north_west)), int(bool(r.worked_with_mmu)),
                          r.size if isinstance(r.size, str) else "", r.aliases if isinstance(r.aliases, str) else ""])
    rows = []
    for r in ev.itertuples(index=False):
        ci = key_pos.get(r.company_key)
        if ci is None:
            continue
        title = r.project_title if isinstance(r.project_title, str) else ""
        rows.append([ci, TYPE_CODES.get(r.evidence_type, "?"),
                     int(r.year) if pd.notna(r.year) else 0,
                     uni_idx.get(r.university, -1), title[:100],
                     scheme_idx.get(r.scheme, -1) if isinstance(r.scheme, str) else -1,
                     round(float(r.points), 3) if pd.notna(r.points) else 0,
                     theme_mask(r.themes), int(r.n_papers) if pd.notna(r.n_papers) else 0])
    payload = {"companies": companies, "rows": rows, "unis": unis, "schemes": schemes,
               "themes": [THEMES[k]["label"] for k in THEME_KEYS],
               "types": {v: k.replace("_", " ") for k, v in TYPE_CODES.items()},
               "built": pd.Timestamp.today().strftime("%d %B %Y"),
               "pdf": base64.b64encode(open("industry-funders-plan.pdf", "rb").read()).decode()
               if os.path.exists("industry-funders-plan.pdf") else ""}
    tpl = open("scripts/explorer_template.html").read()
    html = tpl.replace("/*__DATA__*/null", json.dumps(payload, separators=(",", ":")))
    out = "data/processed/industry-funders-explorer.html"
    open(out, "w").write(html)
    shutil.copy(out, "industry-funders-explorer.html")
    print(f"wrote {out}: {len(companies)} companies, {len(rows)} evidence rows, {len(html)/1e6:.1f} MB", file=sys.stderr)


if __name__ == "__main__":
    main()
