"""Merge every evidence table (Innovate UK, GtR, OpenAlex, scheme pages),
normalise company names, score each company and write the workbook.

Output: data/processed/industry-funders.xlsx with sheets
  master     one row per company, scored and ranked
  evidence   every company x university x project row from both sources
  by_theme   companies ranked within each School theme
"""
import os, re, sys
import pandas as pd, yaml

CFG = yaml.safe_load(open("config/themes.yml"))
LABELS = {k: v["label"] for k, v in CFG["themes"].items()}
ACAD = re.compile("|".join(CFG["academic_patterns"]), re.I)
RTO = re.compile("|".join(CFG.get("rto_patterns", [])), re.I)
PUBRES = re.compile("|".join(CFG.get("public_research_patterns", [])), re.I)
CHARITY = re.compile("|".join(CFG.get("charity_patterns", [])), re.I)
ORG_TYPE_ORDER = ["company", "public_or_rto", "public_research", "charity"]
OA_CFG = yaml.safe_load(open("config/openalex_subfields.yml"))
SUBFIELD_THEME = {OA_CFG["subfields"][sid]: theme for theme, ids in OA_CFG["subfield_themes"].items() for sid in ids}
THEME_SHARE_MIN = 0.2  # a theme is listed for a company when at least this share of its evidence rows carry it
ALIASES = {str(k).upper(): str(v).upper() for k, v in (yaml.safe_load(open("config/aliases.yml")) or {}).items()}
ISO = {"GB": "United Kingdom", "US": "United States", "DE": "Germany", "FR": "France", "CH": "Switzerland", "NL": "Netherlands",
       "BE": "Belgium", "DK": "Denmark", "SE": "Sweden", "NO": "Norway", "FI": "Finland", "IE": "Ireland", "ES": "Spain",
       "IT": "Italy", "PT": "Portugal", "AT": "Austria", "CZ": "Czechia", "HU": "Hungary", "LU": "Luxembourg", "IS": "Iceland",
       "JP": "Japan", "KR": "South Korea", "CN": "China", "HK": "Hong Kong", "IN": "India", "IL": "Israel", "SA": "Saudi Arabia",
       "QA": "Qatar", "AE": "United Arab Emirates", "TH": "Thailand", "AU": "Australia", "NZ": "New Zealand", "CA": "Canada",
       "BR": "Brazil", "ZA": "South Africa", "SG": "Singapore", "TW": "Taiwan", "MX": "Mexico", "AR": "Argentina", "PL": "Poland"}
OA_CAP = {"corporate_funder": 60.0, "company_coauthor": 20.0}  # max points per company from publication counts
SUFFIX = re.compile(r"\b(limited|ltd|plc|llp|llc|inc|gmbh|ag|sa|bv|b\.v|nv|co|company|corp|corporation|"
                    r"uk|u\.k|gb|group|holdings|international|europe|the)\b\.?", re.I)
NW_POSTCODES = ("M", "SK", "OL", "BL", "WN", "WA", "PR", "L", "CH", "FY", "LA", "CA", "BB", "CW")
WEIGHTS = {"studentship": 3.0, "fellowship": 2.0, "ktp": 2.0, "research_grant": 1.0, "innovate_uk": 0.5,
           "scheme_partner": 2.0, "corporate_funder": 0.15, "company_coauthor": 0.05}
PAPER_CAP = 40  # OpenAlex rows carry paper counts; points scale with min(n_papers, cap)


def norm(name):
    s = str(name).upper()
    s = re.sub(r"\(.*?\)", " ", s)          # drop bracketed qualifiers such as (United Kingdom) or (GSK)
    s = re.sub(r"[^A-Z0-9 ]", " ", s)
    s = SUFFIX.sub(" ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return ALIASES.get(s, s)


def evidence_type(r):
    if r["source"] in ("openalex", "scheme"):
        return r["evidence_type"]
    if r["source"] == "innovate_uk":
        return "ktp" if r["is_ktp"] else "innovate_uk"
    gc = str(r["grant_category"]).lower()
    if "studentship" in gc or "training" in gc:
        return "studentship"
    if "fellowship" in gc:
        return "fellowship"
    return "research_grant"


def theme_profile(themes):
    """Share of a company's evidence rows carrying each theme.

    Returns (primary theme label, labels above THEME_SHARE_MIN, profile string).
    Rows with no theme count in the denominator, so a company whose work is
    mostly outside the School's themes shows low shares.
    """
    rows = [str(x) if isinstance(x, str) else "" for x in themes]
    n = len(rows)
    counts = {}
    for r in rows:
        for t in r.split(";"):
            if t:
                counts[t] = counts.get(t, 0) + 1
    if not counts:
        return "", "", ""
    ranked = sorted(counts.items(), key=lambda kv: -kv[1])
    primary = LABELS.get(ranked[0][0], ranked[0][0])
    listed = "; ".join(LABELS.get(t, t) for t, c in ranked if c / n >= THEME_SHARE_MIN)
    profile = "; ".join(f"{LABELS.get(t, t)} {round(100 * c / n)}%" for t, c in ranked[:4])
    return primary, listed or primary, profile


def nw(pc):
    pc = str(pc or "").upper().strip()
    m = re.match(r"([A-Z]{1,2})\d", pc)
    return bool(m) and m.group(1) in NW_POSTCODES


def main():
    parts = [pd.read_csv("data/processed/iuk_evidence.csv", dtype=str),
             pd.read_csv("data/processed/gtr_evidence.csv", dtype=str)]
    if os.path.exists("data/processed/openalex_evidence.csv"):
        oa = pd.read_csv("data/processed/openalex_evidence.csv", dtype=str)
        if len(oa):
            oa["year"] = oa.get("last_year")
            oa["project_title"] = oa["n_papers"].astype(str) + " papers; subfields: " + oa["subfields"].fillna("")
            oa["grant_category"] = oa["evidence_type"]
            oa["org_type"] = "company"
            parts.append(oa)
    if os.path.exists("data/processed/scheme_partners.csv"):
        sc = pd.read_csv("data/processed/scheme_partners.csv", dtype=str)
        sc = sc[sc["company_name"].fillna("").str.strip().ne("")]
        if len(sc):
            parts.append(pd.DataFrame({"source": "scheme", "evidence_type": "scheme_partner",
                                       "company_name": sc["company_name"], "university": sc["university"],
                                       "year": sc["year"], "project_title": sc["award_title"].fillna("") + " (" + sc["person_role"].fillna("") + ")",
                                       "scheme": sc["source"], "grant_category": "scheme_partner",
                                       "project_id": sc["url"], "org_type": "company"}))
    ev = pd.concat(parts, ignore_index=True)
    ev["theme_method"] = "keywords"
    ev["theme_justification"] = ""
    if os.path.exists("data/processed/project_themes.csv"):
        pt = pd.read_csv("data/processed/project_themes.csv", dtype={"project_id": str})
        pt["themes_llm"] = [("" if o else ";".join([p] + [x for x in str(sc).split(";") if x and x != "nan"]))
                            for p, sc, o in zip(pt["primary_theme"], pt["secondary_themes"].fillna(""), pt["outside_scope"])]
        key = ev["source"].astype(str) + "|" + ev["project_id"].astype(str)
        lookup = dict(zip(pt["source"] + "|" + pt["project_id"], zip(pt["themes_llm"], pt["method"], pt["justification"].fillna(""))))
        hit = key.map(lookup)
        m = hit.notna()
        ev.loc[m, "themes"] = hit[m].map(lambda t: t[0])
        ev.loc[m, "theme_method"] = hit[m].map(lambda t: t[1])
        ev.loc[m, "theme_justification"] = hit[m].map(lambda t: t[2])
        print(f"project themes from model: {int(m.sum())} rows ({pt['method'].value_counts().to_dict()})", file=sys.stderr)
    oa = ev["source"].eq("openalex")
    ev.loc[oa, "themes"] = ev.loc[oa, "subfields"].fillna("").map(
        lambda sfs: ";".join(sorted({SUBFIELD_THEME[x.strip()] for x in sfs.split(";") if x.strip() in SUBFIELD_THEME})))
    before = len(ev)
    ev = ev[~ev["company_name"].astype(str).str.contains(ACAD)]
    names = ev["company_name"].astype(str)
    ev["org_type"] = ev["org_type"].where(ev["org_type"].isin(ORG_TYPE_ORDER), "company")
    ev.loc[names.str.contains(CHARITY), "org_type"] = "charity"
    ev.loc[names.str.contains(PUBRES), "org_type"] = "public_research"
    ev.loc[names.str.contains(RTO), "org_type"] = "public_or_rto"
    print(ev.drop_duplicates("company_name").groupby("org_type").size().to_string(), file=sys.stderr)
    print(f"dropped {before - len(ev)} rows naming academic or public bodies", file=sys.stderr)
    ev["n_papers"] = pd.to_numeric(ev.get("n_papers"), errors="coerce")
    ev["is_ktp"] = ev["is_ktp"].astype(str).str.lower().eq("true")
    ev["year"] = pd.to_numeric(ev["year"], errors="coerce")
    ev["award_gbp"] = pd.to_numeric(ev["award_gbp"], errors="coerce")
    ev["name_key"] = ev["company_name"].map(norm)
    ev["university"] = ev["university"].astype(str).map(lambda u: u.title().replace(" Of ", " of ").replace(" And ", " and ").replace(" The ", " the ") if u.isupper() else u)
    ev["evidence_type"] = ev.apply(evidence_type, axis=1)

    # Company key: registration number where known (from either source), else normalised name
    crn = ev.dropna(subset=["company_crn"])
    crn = crn[crn["company_crn"].str.strip().ne("") & crn["company_crn"].str.strip().ne("nan")]
    name_to_crn = crn.groupby("name_key")["company_crn"].agg(lambda s: s.value_counts().index[0]).to_dict()
    ev["company_key"] = ev["name_key"].map(name_to_crn).fillna(ev["name_key"])
    ev["company_country"] = ev.get("company_country").replace({"UK": "United Kingdom"}).map(lambda c: ISO.get(c, c) if isinstance(c, str) else c)
    cc = ev["company_country"]
    ev.loc[cc.isna() & ev["company_postcode"].astype(str).str.match(r"^[A-Z]{1,2}\d"), "company_country"] = "United Kingdom"
    ev["north_west"] = ev["company_postcode"].map(nw) | ev["company_region"].astype(str).str.contains("North West", case=False)

    this_year = pd.Timestamp.today().year
    ev["recency"] = (1 - (this_year - ev["year"].fillna(this_year - 10)).clip(0, 20) / 20)
    ev["points"] = ev["evidence_type"].map(WEIGHTS) * (0.5 + 0.5 * ev["recency"])
    oa_mask = ev["source"].eq("openalex")
    ev.loc[oa_mask, "points"] = ev.loc[oa_mask, "points"] * ev.loc[oa_mask, "n_papers"].fillna(1).clip(upper=PAPER_CAP)
    # cap publication-derived points per company so paper volume supports but never dominates
    for et, cap in OA_CAP.items():
        m = ev["evidence_type"].eq(et)
        tot = ev[m].groupby("company_key")["points"].transform("sum")
        ev.loc[m, "points"] = ev.loc[m, "points"] * (cap / tot).clip(upper=1.0)

    g = ev.groupby("company_key")
    master = pd.DataFrame({
        "company": g["company_name"].agg(lambda s: s.value_counts().index[0]),
        "aliases": g["company_name"].agg(lambda s: "; ".join(sorted(set(s))[:6])),
        "crn": g["company_crn"].agg(lambda s: next((x for x in s if isinstance(x, str) and x not in ("", "nan")), "")),
        "org_type": g["org_type"].agg(lambda s: next((t for t in ("public_or_rto", "public_research", "charity") if (s == t).any()), "company")),
        "country": g["company_country"].agg(lambda s: s.dropna().replace("", pd.NA).dropna().value_counts().index[0] if s.dropna().replace("", pd.NA).dropna().size else ""),
        "size": g["company_size"].agg(lambda s: next((x for x in s if isinstance(x, str) and x not in ("", "nan")), "")),
        "score": g["points"].sum().round(1),
        "n_studentships": g["evidence_type"].agg(lambda s: (s == "studentship").sum()),
        "n_fellowships": g["evidence_type"].agg(lambda s: (s == "fellowship").sum()),
        "n_ktp": g["evidence_type"].agg(lambda s: (s == "ktp").sum()),
        "n_research_grants": g["evidence_type"].agg(lambda s: (s == "research_grant").sum()),
        "n_innovate_uk": g["evidence_type"].agg(lambda s: (s == "innovate_uk").sum()),
        "n_scheme_partner": g["evidence_type"].agg(lambda s: (s == "scheme_partner").sum()),
        "papers_funded": g.apply(lambda d: d.loc[d["evidence_type"] == "corporate_funder", "n_papers"].sum()),
        "papers_coauthored": g.apply(lambda d: d.loc[d["evidence_type"] == "company_coauthor", "n_papers"].sum()),
        "n_universities": g["university"].nunique(),
        "universities": g["university"].agg(lambda s: "; ".join(s.value_counts().index[:8])),
        "worked_with_mmu": g["university"].agg(lambda s: s.astype(str).str.contains("Manchester Metropolitan", case=False).any()),
        "first_year": g["year"].min(), "last_year": g["year"].max(),
        "north_west": g["north_west"].any(),
        "primary_theme": g["themes"].agg(lambda s: theme_profile(s)[0]),
        "themes": g["themes"].agg(lambda s: theme_profile(s)[1]),
        "theme_profile": g["themes"].agg(lambda s: theme_profile(s)[2]),
        "example_projects": g["project_title"].agg(lambda s: " | ".join(s.dropna().astype(str).head(3).str.slice(0, 90))),
    }).sort_values("score", ascending=False).reset_index(drop=True)
    master.insert(0, "rank", master.index + 1)
    master.insert(1, "rank_in_type", master.groupby("org_type").cumcount() + 1)

    theme_rows = []
    for k, label in LABELS.items():
        sub = ev[ev["themes"].astype(str).str.contains(k)]
        s = sub.groupby("company_key").agg(points=("points", "sum"), n=("project_id", "nunique"),
                                            company=("company_name", lambda x: x.value_counts().index[0]))
        s = s.sort_values("points", ascending=False).head(150).reset_index(drop=True)
        s.insert(0, "theme", label); s.insert(1, "rank_in_theme", s.index + 1)
        theme_rows.append(s[["theme", "rank_in_theme", "company", "n", "points"]])
    by_theme = pd.concat(theme_rows, ignore_index=True)

    cols = ["source", "evidence_type", "company_name", "company_crn", "org_type", "n_papers", "company_role", "university", "project_title",
            "grant_category", "scheme", "competition", "year", "start", "end", "award_gbp", "themes",
            "company_postcode", "company_region", "project_id", "grant_reference"]
    ev_out = ev[[c for c in cols if c in ev.columns]].sort_values(["company_name", "year"])
    about = pd.DataFrame({"Industry funders of biological and chemical sciences research at UK universities": [
        "Author: Rémi Zallot, School of Biological and Chemical Sciences, Manchester Metropolitan University",
        f"Built: {pd.Timestamp.today().strftime('%d %B %Y')}",
        "Code, method and documentation: https://github.com/remizallot/industry-funders",
        "",
        "Sheets: master (one row per organisation, ranked), by_theme (top companies per School theme), evidence (every underlying record).",
        "Sources: UKRI Gateway to Research (project partners and collaborators), Innovate UK funded projects since 2004 (participants and KTPs), "
        "OpenAlex (corporate funders and company co-authors of UK university papers), published lists of named partnership schemes.",
        "Scoring: studentship 3, fellowship 2, KTP 2, named partnership 2, research grant 1, other Innovate UK project 0.5, scaled by recency; "
        "papers funded 0.15 and co-authored 0.05 each, capped per company. Companies keyed on Companies House number where known.",
        "org_type: company; public_or_rto (research and technology organisations, catapults); public_research (research institutes, "
        "national facilities, government agencies, international research organisations and funders); charity (charities, foundations, "
        "learned societies). Filter on company for the target list; the other types are co-funders worth knowing.",
        "Suggested citation: Zallot R. (2026). Industry funders of biological and chemical sciences research at UK universities: an evidence-based target list. "
        "Manchester Metropolitan University. https://github.com/remizallot/industry-funders",
    ]})
    with pd.ExcelWriter("data/processed/industry-funders.xlsx", engine="openpyxl") as xw:
        about.to_excel(xw, "about", index=False)
        master.to_excel(xw, "master", index=False)
        by_theme.to_excel(xw, "by_theme", index=False)
        ev_out.to_excel(xw, "evidence", index=False)
    master.to_csv("data/processed/master.csv", index=False)
    ev[["company_key", "org_type", "north_west", "company_country"] + [c for c in cols if c in ev.columns] + ["points", "theme_method", "theme_justification"]].to_csv(
        "data/processed/evidence.csv", index=False)
    print(f"companies {len(master)}, evidence rows {len(ev)}; top 15:", file=sys.stderr)
    print(master.head(15)[["rank", "company", "score", "n_studentships", "n_ktp", "n_research_grants", "n_scheme_partner", "papers_funded", "papers_coauthored"]].to_string(index=False), file=sys.stderr)


if __name__ == "__main__":
    main()
