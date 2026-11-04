"""Extract company x university pairs from the Innovate UK funded-projects
spreadsheets, restricted to the School's subject scope (inclusion-first).

Output: data/processed/iuk_evidence.csv, one row per (company, academic
partner, project).
"""
import re, sys
import pandas as pd, yaml

CFG = yaml.safe_load(open("config/themes.yml"))
THEMES = CFG["themes"]
ACAD = re.compile("|".join(CFG["academic_patterns"]), re.I)
ALWAYS = set(CFG["innovate_uk_sectors_always"])
KW = {k: re.compile("|".join(v["keywords"]), re.I) for k, v in THEMES.items()}


def theme_tags(text):
    return [k for k, rx in KW.items() if rx.search(text or "")]


def main():
    files = ["data/raw/iuk_2016_to_present.xlsx", "data/raw/iuk_2004_to_2016.xlsx"]
    df = pd.concat([pd.read_excel(f) for f in files], ignore_index=True)
    df.columns = [c.strip() for c in df.columns]
    df["Participant Name"] = df["Participant Name"].astype(str).str.strip()
    df["is_academic"] = (df["Enterprise Size"].astype(str).str.strip().eq("Academic")
                         | df["Participant Name"].str.contains(ACAD))
    df["text"] = df["Project Title"].fillna("") + " " + df["Public Description"].fillna("")
    df["themes"] = df["text"].map(theme_tags)
    df["title_themes"] = df["Project Title"].fillna("").map(theme_tags)
    df["in_scope"] = df["Sector"].isin(ALWAYS) | df["themes"].map(bool)

    # Project-level: keep projects in scope with at least one academic and one company participant
    g = df.groupby("Project Number")
    scope_proj = g["in_scope"].any()
    has_acad = g["is_academic"].any()
    has_comp = g["is_academic"].apply(lambda s: (~s).any())
    keep = scope_proj[scope_proj & has_acad & has_comp].index
    sub = df[df["Project Number"].isin(keep)].copy()
    print(f"rows {len(df)}, projects {df['Project Number'].nunique()}, in-scope projects with company+academic {len(keep)}",
          file=sys.stderr)

    acad = sub[sub["is_academic"]][["Project Number", "Participant Name"]].rename(columns={"Participant Name": "university"})
    comp = sub[~sub["is_academic"]].copy()
    rows = comp.merge(acad, on="Project Number", how="inner")
    out = pd.DataFrame({
        "source": "innovate_uk",
        "company_name": rows["Participant Name"],
        "company_crn": rows["CRN"].astype("string").str.strip(),
        "company_size": rows["Enterprise Size"],
        "org_type": rows["Enterprise Size"].astype(str).str.strip().map(
            lambda z: "public_or_rto" if z in ("RTO", "Catapult", "PSO", "PSRE", "Charity", "Academic") else "company"),
        "company_postcode": rows["Postcode"],
        "company_region": rows["Address Region"],
        "company_is_lead": rows["Is Lead Participant"].eq("Yes"),
        "university": rows["university"],
        "project_id": rows["Project Number"].astype(str),
        "project_title": rows["Project Title"],
        "scheme": rows["Programme Title"],
        "competition": rows["Competition Title"],
        "sector": rows["Sector"],
        "grant_category": rows["Innovate UK Product Type"],
        "year": pd.to_datetime(rows["Project Start Date"], errors="coerce").dt.year,
        "start": pd.to_datetime(rows["Project Start Date"], errors="coerce").dt.date,
        "end": pd.to_datetime(rows["Project End Date"], errors="coerce").dt.date,
        "award_gbp": rows["Award Offered (£)"],
        "themes": rows["themes"].map(lambda t: ";".join(t)),
        "is_ktp": rows["Programme Title"].astype(str).str.contains("KTP|Knowledge Transfer", case=False),
    })
    out = out.drop_duplicates()
    out.to_csv("data/processed/iuk_evidence.csv", index=False)
    print(f"wrote {len(out)} rows, {out['company_name'].nunique()} companies, {out['university'].nunique()} academic partners",
          file=sys.stderr)


if __name__ == "__main__":
    main()
