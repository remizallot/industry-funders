"""Extract company x university pairs from the Gateway to Research pull.

Reads data/raw/gtr/{projects,organisations,funds}.jsonl.gz and writes
data/processed/gtr_evidence.csv with one row per (non-academic partner,
lead organisation, project). Scope is inclusion-first: a project is kept
if its lead funder is wholly in scope, or any of its UKRI research subjects
or topics map to a School theme, or a theme keyword matches the title or
abstract.
"""
import gzip, json, re, sys
import pandas as pd, yaml

CFG = yaml.safe_load(open("config/themes.yml"))
THEMES = CFG["themes"]
ACAD = re.compile("|".join(CFG["academic_patterns"]), re.I)
FUNDERS_ALWAYS = set(CFG["gtr_funders_always"])
FUNDERS_SUBJECT_ONLY = set(CFG["gtr_funders_subject_only"])
KW = {k: re.compile("|".join(v["keywords"]), re.I) for k, v in THEMES.items()}
SUBJ = {k: set(v["ukri_subjects"]) for k, v in THEMES.items()}
TOPIC = {k: re.compile("|".join(v["ukri_topics"]), re.I) if v["ukri_topics"] else None
         for k, v in THEMES.items()}
PARTNER_ROLES = {"PP_ORG": "project_partner", "COLLAB_ORG": "collaborator"}


def read_jsonl(path):
    try:
        with gzip.open(path, "rt") as fh:
            for line in fh:
                try:
                    yield json.loads(line)
                except json.JSONDecodeError:
                    return
    except (EOFError, FileNotFoundError):
        return


def classify(p):
    """Return (strong tags, all tags, subjects, topics).

    Strong tags come from UKRI subjects, topics or the title and decide scope;
    all tags add abstract matches and are recorded as themes.
    """
    strong, weak, classified = set(), set(), set()
    subjects = [s["text"] for s in p.get("researchSubjects", {}).get("researchSubject", []) or []]
    topics = [t["text"] for t in p.get("researchTopics", {}).get("researchTopic", []) or []]
    title = p.get("title") or ""
    abstract = p.get("abstractText") or ""
    for k in THEMES:
        if SUBJ[k] & set(subjects) or (TOPIC[k] and any(TOPIC[k].search(t) for t in topics)):
            classified.add(k)
        if KW[k].search(title):
            strong.add(k)
        elif KW[k].search(abstract):
            weak.add(k)
    return classified, strong | classified, strong | weak | classified, subjects, topics


def main():
    orgs = {}
    for o in read_jsonl("data/raw/gtr/organisations.jsonl.gz"):
        addr = (o.get("addresses") or {}).get("address") or [{}]
        a = addr[0] if addr else {}
        orgs[o["id"]] = {"name": o.get("name"), "reg": o.get("regNumber"),
                         "postcode": a.get("postCode"), "region": a.get("region"),
                         "country": a.get("country")}
    print(f"organisations: {len(orgs)}", file=sys.stderr)

    fund_by_project = {}
    for f in read_jsonl("data/raw/gtr/funds.jsonl.gz"):
        for l in (f.get("links") or {}).get("link") or []:
            if l.get("rel") == "FUNDED":
                pid = l["href"].rsplit("/", 1)[-1]
                amt = ((f.get("valuePounds") or {}).get("amount")) or 0
                fund_by_project[pid] = fund_by_project.get(pid, 0) + amt
    print(f"funds: {len(fund_by_project)} projects", file=sys.stderr)

    rows, n_proj, n_scope = [], 0, 0
    for p in read_jsonl("data/raw/gtr/projects.jsonl.gz"):
        n_proj += 1
        classified, strong, tags, subjects, topics = classify(p)
        funder = p.get("leadFunder") or ""
        if funder in FUNDERS_ALWAYS:
            pass
        elif funder in FUNDERS_SUBJECT_ONLY:
            if not classified:
                continue
        elif not strong:
            continue
        tags = sorted(tags)
        n_scope += 1
        links = (p.get("links") or {}).get("link") or []
        lead, partners, start, end = None, [], None, None
        for l in links:
            oid = l["href"].rsplit("/", 1)[-1]
            if l["rel"] == "LEAD_ORG":
                lead = oid
            elif l["rel"] in PARTNER_ROLES:
                partners.append((oid, PARTNER_ROLES[l["rel"]]))
            elif l["rel"] == "FUND":
                start, end = l.get("start"), l.get("end")
        if not partners:
            continue
        lead_o = orgs.get(lead, {"name": lead})
        gref = ""
        for i in (p.get("identifiers") or {}).get("identifier") or []:
            gref = i.get("value") or gref
        for oid, role in partners:
            o = orgs.get(oid)
            name = (o or {}).get("name") or oid
            if ACAD.search(name or ""):
                continue
            rows.append({
                "source": "gtr", "company_name": name, "company_crn": (o or {}).get("reg"),
                "company_size": None, "org_type": "company", "company_postcode": (o or {}).get("postcode"),
                "company_region": (o or {}).get("region"), "company_is_lead": False,
                "company_role": role, "university": lead_o.get("name"),
                "project_id": p["id"], "grant_reference": gref,
                "project_title": p.get("title"), "scheme": funder,
                "competition": None, "sector": ";".join(subjects),
                "grant_category": p.get("grantCategory"),
                "year": pd.to_datetime(start, unit="ms").year if start else None,
                "start": pd.to_datetime(start, unit="ms").date() if start else None,
                "end": pd.to_datetime(end, unit="ms").date() if end else None,
                "award_gbp": fund_by_project.get(p["id"]),
                "themes": ";".join(tags), "topics": ";".join(topics),
                "is_ktp": False,
            })
    out = pd.DataFrame(rows).drop_duplicates()
    out.to_csv("data/processed/gtr_evidence.csv", index=False)
    print(f"projects {n_proj}, in scope {n_scope}, partner rows {len(out)}, companies {out['company_name'].nunique()}",
          file=sys.stderr)


if __name__ == "__main__":
    main()
