#!/usr/bin/env python3
"""Phase 3: scrape named industry-academic partnership schemes.

Reads config/scheme_sources.yml, fetches each page politely (robots.txt
checked per host, fixed delay, identifying User-Agent), parses it with the
strategy named in the config and writes data/processed/scheme_partners.csv
with the columns

    source, company_name, university, year, award_title, person_role, url, notes

One row per (company, university, award). A page that cannot be fetched or
parsed, or a source known to have no scrapable list, produces a row with
company_name blank so the gap stays visible. Nothing is invented: every
company name is taken from the page text.

Run from the project directory with the venv Python:

    .venv/bin/python scripts/07_scrape_schemes.py
"""
from __future__ import annotations

import csv
import io
import logging
import re
import sys
import time
import traceback
import urllib.robotparser
from pathlib import Path
from urllib.parse import urljoin, urlparse

import pandas as pd
import requests
import yaml
from bs4 import BeautifulSoup

ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "config" / "scheme_sources.yml"
RAW_DIR = ROOT / "data" / "raw" / "schemes"
OUT = ROOT / "data" / "processed" / "scheme_partners.csv"
COLUMNS = ["source", "company_name", "university", "year", "award_title",
           "person_role", "url", "notes"]

log = logging.getLogger("schemes")

ACADEMIC_RE = re.compile(
    r"\b(Universit(y|ies)|College|Institute|School of|Centre for|"
    r"Center for|Polytechnic|Francis Crick|Rothamsted|John Innes|EPCC|Imperial|"
    r"UCL|LSE|Hutton|SRUC)\b",
    re.I)
# public research bodies: neither a company nor a university, dropped from pairs
PUBLIC_RE = re.compile(
    r"\b(Dstl|Defence Science and Technology Laboratory|Facilities Council|Research Council|"
    r"Diamond Light Source|Catapult|National Physical Laboratory|UKRI|EPSRC|BBSRC|MRC|STFC|Met Office)\b", re.I)
# names that contain ' and ' and must not be split
COMPOUND_NAMES = [
    "Defence Science and Technology Laboratory", "Science and Technology Facilities Council",
    "Engineering and Physical Sciences Research Council", "Biotechnology and Biological Sciences Research Council",
    "ISIS Neutron and Muon Source", "Oxfam and Water For People",
]
# words that regex extraction must never return as a company
STOP_ORGS = {
    "government", "business", "academia", "industry", "the uk", "uk", "ukri",
    "epsrc", "bbsrc", "mrc", "nerc", "stfc", "ahrc", "esrc", "research england",
    "innovate uk", "hefce", "uk research and innovation", "the university",
    "businesses", "universities", "the government", "scotland", "england", "wales",
    "northern ireland", "the", "and", "research", "the project", "the centre",
}


# --------------------------------------------------------------------- fetch
class Fetcher:
    def __init__(self, user_agent: str, delay: float):
        self.session = requests.Session()
        self.session.headers["User-Agent"] = user_agent
        self.delay = delay
        self._robots: dict[str, urllib.robotparser.RobotFileParser | None] = {}
        self._last = 0.0

    def _wait(self, host_delay: float | None = None):
        gap = max(self.delay, host_delay or 0)
        now = time.monotonic()
        if now - self._last < gap:
            time.sleep(gap - (now - self._last))
        self._last = time.monotonic()

    def _robot(self, url: str):
        host = urlparse(url).scheme + "://" + urlparse(url).netloc
        if host not in self._robots:
            rp = urllib.robotparser.RobotFileParser()
            try:
                self._wait()
                r = self.session.get(host + "/robots.txt", timeout=30)
                if r.status_code == 200 and "<html" not in r.text[:500].lower():
                    rp.parse(r.text.splitlines())
                else:
                    rp = None  # no usable robots.txt: everything allowed
            except requests.RequestException:
                rp = None
            self._robots[host] = rp
        return self._robots[host]

    def allowed(self, url: str) -> bool:
        rp = self._robot(url)
        if rp is None:
            return True
        return rp.can_fetch(self.session.headers["User-Agent"], url) and rp.can_fetch("*", url)

    def crawl_delay(self, url: str) -> float | None:
        rp = self._robot(url)
        if rp is None:
            return None
        try:
            return rp.crawl_delay("*")
        except Exception:
            return None

    def get(self, url: str, **kw) -> requests.Response:
        if not self.allowed(url):
            raise PermissionError(f"disallowed by robots.txt: {url}")
        self._wait(self.crawl_delay(url))
        r = self.session.get(url, timeout=60, **kw)
        if r.status_code == 403:
            raise PermissionError(f"HTTP 403 for {url}")
        r.raise_for_status()
        return r

    def post(self, url: str, data: dict) -> requests.Response:
        if not self.allowed(url):
            raise PermissionError(f"disallowed by robots.txt: {url}")
        self._wait(self.crawl_delay(url))
        r = self.session.post(url, data=data, timeout=60,
                              headers={"X-Requested-With": "XMLHttpRequest"})
        if r.status_code == 403:
            raise PermissionError(f"HTTP 403 for {url}")
        r.raise_for_status()
        return r


# ------------------------------------------------------------------- helpers
def soup_of(html: str) -> BeautifulSoup:
    s = BeautifulSoup(html, "lxml")
    for t in s(["script", "style", "noscript"]):
        t.decompose()
    return s


def main_of(s: BeautifulSoup):
    return s.find("main") or s.find("article") or s.body or s


def text_lines(node) -> list[str]:
    return [ln.strip() for ln in node.get_text("\n").splitlines() if ln.strip()]


def clean(s: str) -> str:
    s = re.sub(r"\s+", " ", s or "").strip("  ,;:.")
    return s


def strip_the(s: str) -> str:
    return re.sub(r"^(the|The)\s+", "", clean(s))


def is_academic(name: str) -> bool:
    return bool(ACADEMIC_RE.search(name))


def split_orgs(s: str, split_with: bool = False) -> list[str]:
    """Split 'A, B and the C' into organisation names.

    'Universities of Liverpool and Oxford' becomes two universities; compound
    names such as 'Defence Science and Technology Laboratory' stay whole.
    """
    s = clean(s)
    s = re.sub(r"\s*\(\s*(?:[A-Za-z]{2,8})\s*\)", "", s)  # drop (UCL), ( dstl )
    for name in COMPOUND_NAMES:
        s = s.replace(name, name.replace(" and ", " AND_ "))
    # Universities of A, B and C -> University of A, University of B, University of C
    def _expand(m):
        places = re.split(r",\s*|\s+and\s+", m.group(1))
        return ", ".join("University of " + p.strip() for p in places if p.strip())
    s = re.sub(r"Universities of ((?:[A-Z][\w'’\-]+(?:,\s*|\s+and\s+))*[A-Z][\w'’\-]+)", _expand, s)
    pattern = r",\s*|\s+and\s+|\s*&\s*" + (r"|\s+with\s+" if split_with else "")
    parts = re.split(pattern, s)
    out = []
    for p in parts:
        p = strip_the(p.replace(" AND_ ", " and "))
        if p and p.lower() not in STOP_ORGS and len(p) > 1 and not PUBLIC_RE.search(p):
            out.append(p)
    return out


def looks_like_org(p: str) -> bool:
    """A short name starting with a capital, as written in a list of partners."""
    return bool(re.match(r"^[A-Z0-9]", p)) and len(p.split()) <= 7 and not re.search(
        r"\b(said|will|aims?|is|are|has|have|set|part|using|could|help|led|new|today|between|include)\b", p)


def row(src: dict, **kw) -> dict:
    r = {c: "" for c in COLUMNS}
    r["source"] = src["source"]
    r["url"] = src.get("url", "")
    r["year"] = str(src.get("year", "") or "")
    r["university"] = src.get("university", "")
    r["person_role"] = src.get("person_role", "")
    for k, v in kw.items():
        if v is not None:
            r[k] = clean(str(v)) if k != "notes" else str(v).strip()
    return r


def gap_row(src: dict, why: str) -> dict:
    note = "; ".join(x for x in [src.get("notes", ""), why] if x)
    return row(src, company_name="", notes=f"GAP: {note}")


def pair_rows(src: dict, orgs: list[str], **kw) -> list[dict]:
    """Pair every non-academic org with every academic org in the list."""
    acad = [o for o in orgs if is_academic(o)]
    comp = [o for o in orgs if not is_academic(o)]
    rows = []
    for c in comp:
        if acad:
            for a in acad:
                rows.append(row(src, company_name=c, university=a, **kw))
        else:
            rows.append(row(src, company_name=c, university="", **kw))
    return rows


# ---------------------------------------------------------------- strategies
def s_ukri_led_by_blocks(src, f: Fetcher):
    s = soup_of(f.get(src["url"]).text)
    rows, title, lead, lead_uni = [], "", "", ""
    for el in main_of(s).find_all(["h2", "h3", "h4", "p"]):
        t = clean(el.get_text(" ", strip=True))
        if el.name in ("h2", "h3", "h4"):
            title, lead, lead_uni = t, "", ""
            continue
        m = re.match(r"^Led by:?\s*(.+)$", t)
        if m and not lead:
            body = m.group(1)
            # "Prof A, EPCC, The University of Edinburgh" -> last comma chunk
            chunks = [c.strip() for c in body.split(",")]
            lead_uni = strip_the(chunks[-1]) if len(chunks) > 1 else ""
            lead = chunks[0]
            continue
        m = re.match(r"^Business partner:?\s*(.+)$", t)
        if m:
            body = m.group(1)
            chunks = [c.strip() for c in body.split(",")]
            company = chunks[-1] if len(chunks) > 1 else chunks[0]
            contact = chunks[0] if len(chunks) > 1 else ""
            role = f"Lead: {lead}" if lead else ""
            if contact:
                role += f"; business contact: {contact}"
            rows.append(row(src, company_name=company, university=lead_uni,
                            award_title=title, person_role=role.strip("; ")))
    return rows


def s_ukri_title_then_partners(src, f: Fetcher):
    s = soup_of(f.get(src["url"]).text)
    lines = text_lines(main_of(s))
    try:
        start = next(i for i, ln in enumerate(lines) if re.match(r"^The projects?\b", ln))
    except StopIteration:
        start = 0
    rows, prev = [], ""
    for ln in lines[start + 1:]:
        if len(ln) < 160 and " and " in ln and is_academic(ln) and not ln.endswith("."):
            rows += pair_rows(src, split_orgs(ln), award_title=prev)
        prev = ln
    return rows


PROSE_PATTERNS = [
    r"partnership between (?P<a>[^.;]+?) and (?P<b>[^.;]+?)(?=,| designed| will| aims| could| to\b|\.|$)",
    r"collaboration between (?P<a>[^.;]+?) and (?P<b>[^.;]+?)(?=,| will| aims| could|\.|$)",
    r"(?P<a>(?:[A-Z][\w&'’.\-]+\s+){0,4}[A-Z][\w&'’.\-]+) will partner with (?P<b>[^.;]+?)(?= to\b| in\b|,|\.|$)",
    r"(?P<a>(?:[A-Z][\w&'’.\-]+\s+){0,4}[A-Z][\w&'’.\-]+),? in partnership with (?P<b>[^.;]+?)(?=,| aim| will|\.|$)",
    r"led by (?P<a>[A-Z][^.;]+?) (?:with|and) (?P<b>(?:the )?(?:Universit|Imperial|Brunel)[^.;]*?)(?=\.|$)",
]


def s_prose_pairs(src, f: Fetcher):
    s = soup_of(f.get(src["url"]).text)
    m = main_of(s)
    rows = []
    for el in m.find_all(["p", "li", "h3", "h4"]):
        raw = el.get_text(" ", strip=True)
        t = clean(raw)
        if not t:
            continue
        # 1. short structured list lines "A, B and the University of X"
        if 10 < len(t) < 170 and " and " in t and is_academic(t) and not raw.rstrip().endswith((".", ":")):
            orgs = split_orgs(t)
            if orgs and all(looks_like_org(o) for o in orgs) and any(not is_academic(o) for o in orgs):
                rows += pair_rows(src, orgs, notes="structured list line")
                continue
        # 2. prose sentences within this element
        for pat in PROSE_PATTERNS:
            for mt in re.finditer(pat, t):
                orgs = split_orgs(mt.group("a"), split_with=True) + split_orgs(mt.group("b"), split_with=True)
                orgs = [o for o in orgs if looks_like_org(o)]
                if any(is_academic(o) for o in orgs) and any(not is_academic(o) for o in orgs):
                    rows += pair_rows(src, orgs, notes=f"regex from prose: '{clean(mt.group(0))[:120]}'")
    return rows


def s_rs_case_studies(src, f: Fetcher):
    base = src["url"]
    s = soup_of(f.get(base).text)
    links = set()
    for a in s.find_all("a", href=True):
        href = urljoin(base, a["href"])
        if href.startswith(base) and href != base and "short-industry" not in href \
                and not href.endswith((".pdf", ".jpg")) and "innovation-through" not in href:
            links.add(href.rstrip("/") + "/")
    rows = []
    for href in sorted(links):
        try:
            page = soup_of(f.get(href).text)
        except Exception as e:  # noqa: BLE001
            rows.append(gap_row(src, f"{href}: {e}"))
            continue
        lines = text_lines(main_of(page))
        name = next((ln.split(":", 1)[1].strip() for ln in lines if ln.startswith("Case study:")), "")
        meta = next((ln for ln in lines if ln.startswith("Awarded:")), "")
        m = re.search(r"Awarded:\s*(\d{4})[^,]*,\s*Employer:\s*(.+?),\s*Host:\s*(.+)$", meta)
        if not m:
            rows.append(gap_row(src, f"{href}: no Awarded/Employer/Host line"))
            continue
        year, employer, host = m.group(1), clean(m.group(2)), clean(m.group(3))
        orgs = [employer, host]
        acad = [o for o in orgs if is_academic(o)]
        comp = [o for o in orgs if not is_academic(o)]
        r = row(src, company_name=comp[0] if comp else "", university=acad[0] if acad else "",
                year=year, award_title="Royal Society Industry Fellowship",
                person_role=f"Industry Fellow: {name}" if name else "Industry Fellow", url=href,
                notes="case study page" + ("" if comp else f"; employer {employer}, host {host}"))
        rows.append(r)
    return rows


def s_raeng_filter(src, f: Fetcher):
    # The listing page carries the hidden form fields; read them first so the
    # ids stay current.
    listing = soup_of(f.get(src["listing_page"]).text)
    form = listing.find("form", id="filter-content-search-form")
    data = {}
    if form:
        for inp in form.find_all("input", type="hidden"):
            data[inp.get("name")] = inp.get("value", "")
    data.update({"ItemsPerPage": "500", "Term": "", "SelectedCategories": src["category_id"]})
    s = soup_of(f.post(src["url"], data).text)
    rows = []
    for card in s.select(".card-body"):
        a = card.find("a", href=True)
        if not a:
            continue
        head = clean(a.get_text(" ", strip=True))
        body = clean(card.select_one(".card-text").get_text(" ", strip=True)) if card.select_one(".card-text") else ""
        href = urljoin("https://raeng.org.uk/", a["href"])
        ym = re.search(r"(20\d\d)", href)
        year = ym.group(1) if ym else ""
        # Research Chairs: head "Name, University"; body "Sponsor/Royal Academy of Engineering Research Chair in X"
        m = re.match(r"^(.*?)\s*/\s*(?:Royal Academy of Engineering|RAEng)\s*(.*)$", body) \
            or (re.match(r"^([^/]{2,80}?)\s+/\s+(.*)$", body) if "/" not in head else None)
        if m:
            sponsor, title = m.group(1), m.group(2)
            name, uni = (head.rsplit(",", 1) + [""])[:2] if "," in head else (head, "")
            for comp in split_orgs(sponsor):
                rows.append(row(src, company_name=comp, university=strip_the(uni), year=year,
                                award_title=title, person_role=f"Awardee: {name}", url=href))
            continue
        # Industrial Fellowships: head "Name, University / Company"; body = project title
        if "/" in head:
            left, right = head.split("/", 1)
            name, org1 = (left.rsplit(",", 1) + [""])[:2] if "," in left else (left, "")
            orgs = [strip_the(org1)] + split_orgs(right)
            acad = [o for o in orgs if is_academic(o)]
            comp = [o for o in orgs if o and not is_academic(o)]
            for c in comp:
                rows.append(row(src, company_name=c, university=acad[0] if acad else "", year=year,
                                award_title=body, person_role=f"Awardee: {name}", url=href))
        else:
            rows.append(gap_row(src, f"card without sponsor: '{head}' / '{body[:60]}' {href}"))
    return rows


def s_rc1851_list(src, f: Fetcher):
    s = soup_of(f.get(src["url"]).text)
    lines = text_lines(main_of(s))
    year = str(src.get("year", ""))
    try:
        start = next(i for i, ln in enumerate(lines)
                     if re.search(r"list of (\d{4} )?Industrial Fellows", ln, re.I))
        ym = re.search(r"(20\d\d)", lines[start])
        if ym:
            year = ym.group(1)
    except StopIteration:
        return [gap_row(src, "no 'list of Industrial Fellows' heading found")]
    pat = re.compile(r"^(?P<name>[^,]+?),\s*(?P<company>.+?)\s+and\s+(?:the\s+)?(?P<uni>.+)$")
    rows, i = [], start + 1
    while i < len(lines):
        m = pat.match(lines[i])
        if m and len(lines[i]) < 160 and is_academic(m.group("uni")):
            title = ""
            if i + 1 < len(lines) and not pat.match(lines[i + 1]) and len(lines[i + 1]) < 200:
                title = lines[i + 1]
                i += 1
            rows.append(row(src, company_name=m.group("company"), university=m.group("uni"),
                            year=year, award_title=title,
                            person_role=f"Industrial Fellow: {m.group('name')}"))
        elif rows and len(lines[i]) > 200:
            break  # back into prose after the list
        i += 1
    return rows


ORG_SUFFIX = r"(?:Ltd|Limited|plc|PLC|Inc|LLP|Group|AG|SE|GmbH|Corporation|Company|Co\.)"
CAP_WORD = r"[A-Z][\w&'’\-]*"
ORG_NAME = rf"(?:{CAP_WORD}(?:\s+(?:{CAP_WORD}|of|and|&|the|for|de))*\s+{ORG_SUFFIX}|{CAP_WORD}(?:\s+(?:{CAP_WORD}|of|for|the|de|&)){{1,5}}|[A-Z]{{2,6}}|[A-Z][a-z]{{3,}}[\w&'’\-]*)"
PLACE_WORDS = {
    "cambridge", "oxford", "leeds", "sheffield", "manchester", "birmingham", "bristol", "glasgow", "edinburgh",
    "nottingham", "warwick", "liverpool", "southampton", "bath", "exeter", "dundee", "strathclyde", "york", "durham",
    "lancaster", "newcastle", "cardiff", "swansea", "surrey", "sussex", "kent", "essex", "leicester", "loughborough",
    "hull", "aberdeen", "belfast", "coventry", "london", "britain", "malaysia", "china", "india", "usa", "europe",
    "africa", "japan", "korea", "germany", "france", "america", "bill", "harwell", "daresbury", "midlands",
}
UKRPIF_CUES = re.compile(
    rf"(?:partnership with|collaboration with|collaboration between|in collaboration with|together with|"
    rf"partners?(?:\s+(?:include|including|such as|are|from|from both))?[,:]?|co-funded by|co-investment from|"
    rf"funded by|investment from|support(?:ed)? by|alongside|working with|working alongside|with|and)\s+"
    rf"(?P<org>(?:the\s+)?{ORG_NAME}(?:(?:,\s*|\s+and\s+)(?:the\s+)?{ORG_NAME})*)")
UKRPIF_DROP = re.compile(
    r"\b(Universit|College|Institute|Centre|Center|Hub|Campus|Research|Innovation|Science|UKRPIF|HEFCE|UKRI|"
    r"Research England|Fund|England|Scotland|Wales|Northern Ireland|London|UK|North|South|East|West|Midlands|"
    r"Yorkshire|Humber|Government|Council|NHS|Trust|Facility|Laboratory|Technology|Engineering|Medicine|"
    r"Manufacturing|Materials|Health|Programme|Project|Building|Phase|Round|The|This|These|It|Its|In|By|"
    r"Hospital|Foundation Trust|Partnership|Network|Catapult|Partners|Partner|Students|Academy|Future|"
    r"Digital|Data|Energy|Bio|Quantum|Advanced|Applied|Integrated|Global|National|International|Royal|"
    r"Industrial Strategy|Strategy|Economy|Industry|Sector|Business|Businesses|Investors|Companies|"
r"Industries|Enterprises|SMEs|Society|Agency|Department|Ministry|Office)\b")


def s_ukrpif_ods(src, f: Fetcher):
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    r = f.get(src["url"])
    path = RAW_DIR / Path(urlparse(src["url"]).path).name
    path.write_bytes(r.content)
    df = pd.read_excel(io.BytesIO(r.content), engine="odf", header=None)
    hdr = next(i for i in range(min(10, len(df)))
               if str(df.iloc[i, 0]).strip().lower().startswith("project title"))
    df.columns = [str(c).strip() for c in df.iloc[hdr]]
    df = df.iloc[hdr + 1:].dropna(how="all")
    rows = []
    for _, rec in df.iterrows():
        title = clean(str(rec.get("Project title", "")))
        uni = clean(str(rec.get("Higher Education Provider", "")))
        rnd = clean(str(rec.get("Round", "")))
        summary = str(rec.get("Summary", "") or "")
        if not title or title == "nan":
            continue
        found = []
        acronym = "".join(w[0] for w in re.findall(r"\b[A-Z]\w*", title))
        for m in UKRPIF_CUES.finditer(summary):
            cue = m.group(0)[: m.start("org") - m.start()].strip().lower()
            if cue in ("with", "and") and not re.search(
                    r"collaborat|partner|co-fund|co-invest|jointly|match|alongside|industr|compan",
                    summary[max(0, m.start() - 90): m.start()], re.I):
                continue
            for org in re.split(r",\s*|\s+and\s+", m.group("org")):
                org = strip_the(org)
                if (len(org) < 3 or UKRPIF_DROP.search(org) or org.lower() in STOP_ORGS
                        or is_academic(org) or PUBLIC_RE.search(org) or org in found
                        or org.lower() in title.lower() or org == acronym
                        or org.lower() in PLACE_WORDS):
                    continue
                if re.fullmatch(r"[A-Z]{2,6}", org) and not re.search(rf"\b{org}\b[^.]*\b(Ltd|plc|company|firm|industr|partner|co-fund|invest)", summary, re.I):
                    continue  # bare acronym with no company cue nearby
                found.append(org)
        for org in found:
            rows.append(row(src, company_name=org, university=uni, award_title=title,
                            notes=f"UKRPIF round {rnd}; candidate partner from summary text, check by hand",
                            url=src.get("publication_page", src["url"])))
        if not found:
            rows.append(row(src, company_name="", university=uni, award_title=title,
                            notes=f"UKRPIF round {rnd}; no partner name found in summary",
                            url=src.get("publication_page", src["url"])))
    return rows


def s_list_after_heading(src, f: Fetcher):
    s = soup_of(f.get(src["url"]).text)
    lines = text_lines(main_of(s))
    want = src["heading"].lower()
    try:
        start = next(i for i, ln in enumerate(lines) if ln.lower() == want)
    except StopIteration:
        return [gap_row(src, f"heading '{src['heading']}' not found")]
    rows, buf = [], []
    for ln in lines[start + 1:]:
        if len(ln) > 90 and not buf:
            continue  # intro sentence
        if len(ln) > 90:
            break
        buf.append(ln)
    # the NLD page splits "Centre for Process Innovation" over two lines
    items, i = [], 0
    while i < len(buf):
        item = buf[i]
        if i + 1 < len(buf) and buf[i + 1][0].islower() or (i + 1 < len(buf) and buf[i + 1] == "Innovation"):
            item = item + " " + buf[i + 1]
            i += 1
        items.append(item)
        i += 1
    for it in items:
        rows.append(row(src, company_name=it, notes="named on DTP partner page"))
    return rows


def s_mibtp_case(src, f: Fetcher):
    s = soup_of(f.get(src["url"]).text)
    lines = text_lines(main_of(s))
    rows = []
    for i, ln in enumerate(lines):
        if ln == "Partner:" and i > 0 and lines[i - 1] == "Industry" and i + 1 < len(lines):
            company = lines[i + 1]
            # walk back for University: and the title before "Primary"
            uni, title = "", ""
            for j in range(i - 1, max(i - 12, 0), -1):
                if lines[j] == "University:" and j + 1 < len(lines):
                    uni = lines[j + 1]
                if lines[j] == "Primary" and j > 0:
                    title = lines[j - 1]
                    break
            rows.append(row(src, company_name=company, university=uni or src.get("university", ""),
                            award_title=title, person_role="DTP industrial partner (CASE project)",
                            notes=f"MIBTP CASE project page; DTP lead {src.get('university', '')}"))
    return rows


def s_logo_alts(src, f: Fetcher):
    s = soup_of(f.get(src["url"]).text)
    rows = []
    for a in s.select("a.oxfcms-image-link img[alt], main a img[alt]"):
        alt = clean(a.get("alt", ""))
        if not alt or re.search(r"University|UKRI|BBSRC|DTP|Research Council", alt):
            continue
        rows.append(row(src, company_name=alt, notes="partner logo alt text on DTP industrial partners page"))
    return rows


def s_gap(src, f: Fetcher):
    return [gap_row(src, "not scraped")]


STRATEGIES = {
    "ukri_led_by_blocks": s_ukri_led_by_blocks,
    "ukri_title_then_partners": s_ukri_title_then_partners,
    "prose_pairs": s_prose_pairs,
    "rs_case_studies": s_rs_case_studies,
    "raeng_filter": s_raeng_filter,
    "rc1851_list": s_rc1851_list,
    "ukrpif_ods": s_ukrpif_ods,
    "list_after_heading": s_list_after_heading,
    "mibtp_case": s_mibtp_case,
    "logo_alts": s_logo_alts,
    "gap": s_gap,
}


# ------------------------------------------------------------------------ main
def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    cfg = yaml.safe_load(CONFIG.read_text(encoding="utf-8"))
    f = Fetcher(cfg["user_agent"], float(cfg.get("request_delay_seconds", 1.5)))
    all_rows: list[dict] = []
    summary = []
    for src in cfg["sources"]:
        strat = STRATEGIES.get(src.get("strategy"))
        label = f"{src['source']} <{src.get('url', '')}>"
        if strat is None:
            all_rows.append(gap_row(src, f"unknown strategy {src.get('strategy')}"))
            summary.append((label, "unknown strategy", 0))
            continue
        try:
            rows = strat(src, f)
            if not rows:
                rows = [gap_row(src, "page fetched but nothing parseable")]
            n = sum(1 for r in rows if r["company_name"])
            log.info("%s: %d rows", label, n)
            summary.append((label, "ok" if n else "no rows", n))
        except Exception as e:  # noqa: BLE001  one bad page must not stop the run
            log.warning("%s failed: %s", label, e)
            log.debug(traceback.format_exc())
            rows = [gap_row(src, f"{type(e).__name__}: {e}")]
            summary.append((label, f"failed: {e}", 0))
        all_rows.extend(rows)

    # dedupe on the identifying columns, keep first occurrence
    seen, out = set(), []
    for r in all_rows:
        key = tuple(clean(r[c]).lower() for c in ("source", "company_name", "university", "year", "award_title"))
        if key in seen:
            continue
        seen.add(key)
        out.append(r)
    out.sort(key=lambda r: (r["source"], r["company_name"].lower(), r["university"].lower(), r["year"]))

    OUT.parent.mkdir(parents=True, exist_ok=True)
    with OUT.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=COLUMNS)
        w.writeheader()
        w.writerows(out)
    log.info("wrote %d rows (%d with a company) to %s", len(out),
             sum(1 for r in out if r["company_name"]), OUT.relative_to(ROOT))
    print("\nSummary")
    for label, status, n in summary:
        print(f"  {n:4d}  {status:<28.28}  {label}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
