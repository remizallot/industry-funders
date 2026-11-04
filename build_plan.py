from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_JUSTIFY
from reportlab.platypus import (SimpleDocTemplate, Paragraph, Spacer, Table,
                                TableStyle, PageBreak, KeepTogether)
from reportlab.graphics.shapes import (Drawing, Rect, String, Polygon, Line,
                                       Ellipse, Path, Group)

OUT = "/Users/remizallot/claude/industry-funders/industry-funders-plan.pdf"

ss = getSampleStyleSheet()
body = ParagraphStyle("body", parent=ss["Normal"], fontName="Helvetica",
                      fontSize=10, leading=14, alignment=TA_JUSTIFY,
                      spaceAfter=7)
h1 = ParagraphStyle("h1", parent=ss["Heading1"], fontName="Helvetica-Bold",
                    fontSize=15, leading=19, spaceBefore=10, spaceAfter=6,
                    textColor=colors.HexColor("#1F3A5F"))
h2 = ParagraphStyle("h2", parent=ss["Heading2"], fontName="Helvetica-Bold",
                    fontSize=11.5, leading=15, spaceBefore=8, spaceAfter=4,
                    textColor=colors.HexColor("#1F3A5F"))
title = ParagraphStyle("title", parent=ss["Title"], fontName="Helvetica-Bold",
                       fontSize=20, leading=25, spaceAfter=4,
                       textColor=colors.HexColor("#1F3A5F"))
sub = ParagraphStyle("sub", parent=body, fontSize=10.5, leading=14,
                     textColor=colors.HexColor("#555555"), spaceAfter=14)
cell = ParagraphStyle("cell", parent=body, fontSize=8.8, leading=11.5,
                      alignment=0, spaceAfter=0)
cellb = ParagraphStyle("cellb", parent=cell, fontName="Helvetica-Bold")
small = ParagraphStyle("small", parent=body, fontSize=8.5, leading=11,
                       textColor=colors.HexColor("#555555"), alignment=0)

def P(t, s=body):
    return Paragraph(t, s)

def table(rows, widths, header=True):
    data = [[Paragraph(c, cellb if (header and i == 0) else cell)
             for c in r] for i, r in enumerate(rows)]
    t = Table(data, colWidths=widths, repeatRows=1 if header else 0)
    st = [("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#BBBBBB")),
          ("VALIGN", (0, 0), (-1, -1), "TOP"),
          ("LEFTPADDING", (0, 0), (-1, -1), 4),
          ("RIGHTPADDING", (0, 0), (-1, -1), 4),
          ("TOPPADDING", (0, 0), (-1, -1), 3),
          ("BOTTOMPADDING", (0, 0), (-1, -1), 3)]
    if header:
        st.append(("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#E3EAF3")))
    t.setStyle(TableStyle(st))
    return t

# ---------------------------------------------------------------- diagram
C_DATA = colors.HexColor("#DCE9F7")   # external data source
C_PROC = colors.HexColor("#FBE7C6")   # processing step
C_STORE = colors.HexColor("#E2F0D9")  # stored dataset
C_OUT = colors.HexColor("#EADCF4")    # deliverable
EDGE = colors.HexColor("#444444")

def label(g, x, y, w, lines, size=7.4):
    n = len(lines)
    y0 = y + (n - 1) * (size + 1.5) / 2
    for i, ln in enumerate(lines):
        g.add(String(x + w / 2, y0 - i * (size + 1.5) - size / 3, ln,
                     fontName="Helvetica", fontSize=size, textAnchor="middle"))

def para(g, x, y, w, h, fill, lines):
    s = 7
    g.add(Polygon([x + s, y, x + w, y, x + w - s, y + h, x, y + h],
                  fillColor=fill, strokeColor=EDGE, strokeWidth=0.8))
    label(g, x, y + h / 2, w, lines)

def proc(g, x, y, w, h, fill, lines):
    g.add(Rect(x, y, w, h, fillColor=fill, strokeColor=EDGE, strokeWidth=0.8))
    label(g, x, y + h / 2, w, lines)

def store(g, x, y, w, h, fill, lines):
    e = 6
    g.add(Rect(x, y + e / 2, w, h - e, fillColor=fill, strokeColor=None))
    g.add(Line(x, y + e / 2, x, y + h - e / 2, strokeColor=EDGE, strokeWidth=0.8))
    g.add(Line(x + w, y + e / 2, x + w, y + h - e / 2, strokeColor=EDGE, strokeWidth=0.8))
    g.add(Ellipse(x + w / 2, y + e / 2, w / 2, e / 2, fillColor=fill,
                  strokeColor=EDGE, strokeWidth=0.8))
    g.add(Ellipse(x + w / 2, y + h - e / 2, w / 2, e / 2, fillColor=fill,
                  strokeColor=EDGE, strokeWidth=0.8))
    label(g, x, y + h / 2, w, lines)

def doc(g, x, y, w, h, fill, lines):
    p = Path(fillColor=fill, strokeColor=EDGE, strokeWidth=0.8)
    p.moveTo(x, y + 5); p.lineTo(x, y + h); p.lineTo(x + w, y + h)
    p.lineTo(x + w, y + 5)
    p.curveTo(x + w * 0.75, y - 4, x + w * 0.25, y + 12, x, y + 5)
    p.closePath()
    g.add(p)
    label(g, x, y + 4 + (h - 4) / 2, w, lines)

def arrow(g, x1, y1, x2, y2):
    g.add(Line(x1, y1, x2, y2, strokeColor=EDGE, strokeWidth=0.8))
    import math
    a = math.atan2(y2 - y1, x2 - x1); L = 4.5
    g.add(Polygon([x2, y2,
                   x2 - L * math.cos(a - 0.4), y2 - L * math.sin(a - 0.4),
                   x2 - L * math.cos(a + 0.4), y2 - L * math.sin(a + 0.4)],
                  fillColor=EDGE, strokeColor=EDGE))

def diagram():
    W, H = 480, 330
    d = Drawing(W, H)
    g = Group(); d.add(g)
    # Row of sources (top)
    srcs = [["UKRI Gateway", "to Research API"],
            ["Innovate UK funded", "projects spreadsheets"],
            ["OpenAlex / Crossref", "funder metadata"],
            ["Studentship and", "postdoc adverts"],
            ["Scheme and university", "partner pages"]]
    bw, bh, gap = 86, 30, 10
    x0 = (W - (5 * bw + 4 * gap)) / 2
    ytop = H - 40
    sx = []
    for i, s in enumerate(srcs):
        x = x0 + i * (bw + gap)
        para(g, x, ytop, bw, bh, C_DATA, s)
        sx.append(x + bw / 2)
    # processing row
    procs = [["Query by research", "topic; keep Project", "Partners"],
             ["Filter sectors;", "pair companies", "with universities"],
             ["Papers with UK HEI", "author and corporate", "funder or co-author"],
             ["Scrape sponsor,", "host, year,", "discipline"],
             ["Extract named", "industrial", "partners"]]
    yp = ytop - 60
    for i, s in enumerate(procs):
        x = x0 + i * (bw + gap)
        proc(g, x, yp, bw, 36, C_PROC, s)
        arrow(g, sx[i], ytop, sx[i], yp + 36)
    # normalise
    yn = yp - 48
    nw = 200
    nx = (W - nw) / 2
    proc(g, nx, yn, nw, 26, C_PROC,
         ["Normalise company names (Companies House numbers), de-duplicate"])
    for i in range(5):
        arrow(g, sx[i], yp, sx[i], yn + 26)
    # store
    ys = yn - 46
    sw = 170
    store(g, (W - sw) / 2, ys, sw, 32, C_STORE,
          ["Evidence table: company x university", "x scheme x year x amount"])
    arrow(g, W / 2, yn, W / 2, ys + 32)
    # scoring
    yc = ys - 44
    proc(g, (W - 200) / 2, yc, 200, 26, C_PROC,
         ["Map to SBCS themes; score by studentships,", "grants, papers, adverts; flag North West"])
    arrow(g, W / 2, ys, W / 2, yc + 26)
    # outputs
    yo = yc - 50
    outs = [["Ranked target", "list (xlsx)"],
            ["Company profiles", "with evidence"],
            ["Benchmark vs", "peer universities"]]
    ow = 110; og = 20
    ox0 = (W - (3 * ow + 2 * og)) / 2
    for i, s in enumerate(outs):
        x = ox0 + i * (ow + og)
        doc(g, x, yo, ow, 30, C_OUT, s)
        arrow(g, W / 2, yc, x + ow / 2, yo + 30)
    # legend
    ly = 6
    items = [(C_DATA, "External data source"), (C_PROC, "Processing step"),
             (C_STORE, "Stored dataset"), (C_OUT, "Deliverable")]
    lx = 20
    for col, txt in items:
        g.add(Rect(lx, ly, 10, 8, fillColor=col, strokeColor=EDGE, strokeWidth=0.6))
        g.add(String(lx + 14, ly + 1.5, txt, fontName="Helvetica", fontSize=7))
        lx += 112
    return d

# ---------------------------------------------------------------- content
story = []
story.append(P("Mapping companies that fund university research in the biological and chemical sciences", title))
story.append(P("A proposal to build an evidence-based target list of industrial funders of PhD studentships, postdoctoral posts and collaborative research, scoped to the School of Biological and Chemical Sciences, Manchester Metropolitan University. Prepared by Rémi Zallot, November 2026.", sub))

story.append(P("Purpose", h1))
story.append(P(
    "The School wants to grow externally funded PhD studentships and research posts. "
    "Companies that have already paid for doctoral students, postdoctoral researchers or "
    "collaborative projects at UK universities are the most likely to do so again, and a "
    "list of them, with the evidence of what they funded, where and when, would let the "
    "School approach the right firms with a credible case. This document sets out what "
    "public data exists, what does not, and a four-phase plan to build the list in roughly "
    "three to four weeks of part-time effort, mostly through automated downloads rather than "
    "manual searching."))

story.append(P("What we found so far", h1))
story.append(P(
    "<b>Innovate UK publishes no such list.</b> Its open data is organised by project and "
    "participant, not by the type of support a company gave a university. The same holds for "
    "UKRI as a whole. <b>The tax route is closed.</b> Research and development tax relief and "
    "Patent Box claims are confidential; HMRC publishes aggregate statistics only, with no "
    "company names and no counterparties. Corporate donations to universities are likewise "
    "private. The one useful fact from that world is that payments to a university for "
    "subcontracted research qualify for relief, which is an argument to use when approaching "
    "companies rather than a dataset to mine. <b>The information does exist in public, "
    "machine-readable form</b>, spread across five kinds of source, and can be assembled "
    "without any paid aggregator such as Beauhurst or The Data City."))

story.append(P("Data sources", h1))
story.append(table([
    ["Source", "What it gives", "Access", "Signal"],
    ["UKRI Gateway to Research (GtR)",
     "Every BBSRC, EPSRC, MRC and NERC grant, iCASE studentship and fellowship since about 2006, "
     "with organisations and their roles. The <i>Project Partner</i> role identifies companies "
     "that contributed cash or in kind. Research topics allow filtering to biosciences and chemistry.",
     "Free JSON API, no key; Open Government Licence", "High: direct evidence of co-funding"],
    ["Innovate UK funded projects since 2004",
     "Two Excel files, updated 3 November 2026, one row per participant per project: title, "
     "public description, competition, programme (including Knowledge Transfer Partnerships), "
     "enterprise size, award. Universities appear as participants alongside the lead company.",
     "Direct download from UKRI", "Medium: shows collaboration, not studentships as such"],
    ["OpenAlex and Crossref",
     "Funder names from paper acknowledgements and author affiliations. Finds papers with a UK "
     "university author and a corporate funder or co-author, filtered by subject.",
     "Free API", "Medium to high: wide net, needs name cleaning"],
    ["FindAPhD and jobs.ac.uk adverts",
     "Industry-sponsored studentships and postdocs advertised as co-funded, iCASE or in "
     "collaboration with a named company, with host university and year.",
     "Public web pages; scrape within terms of use or export by hand", "High: a company paying for a person"],
    ["Named schemes and partner pages",
     "EPSRC Prosperity Partnerships, BBSRC Industrial Partnership Awards and Collaborative "
     "Training Partnerships, Royal Society Industry Fellowships, Royal Academy of Engineering "
     "Research Chairs, Royal Commission for 1851 Industrial Fellowships, UK Research Partnership "
     "Investment Fund, and the industrial partner pages of DTPs and peer universities.",
     "Public web pages", "High: curated, but small"],
    ["Companies House and HESA HE-BCI",
     "Strategic reports occasionally name university collaborations; HE-BCI gives each "
     "university's income from business but not from whom.",
     "Free API; published tables", "Low: for cross-checks and benchmarking only"],
], [32*mm, 72*mm, 36*mm, 32*mm]))
story.append(Spacer(1, 6))

story.append(P("Pipeline", h1))
story.append(P(
    "The five sources feed a single evidence table in which each row records one company "
    "supporting one university under one scheme in one year, with the amount where known. "
    "Companies are matched across sources by their Companies House number so that trading "
    "names and subsidiaries collapse to one entity. Scoring and theme mapping then produce the "
    "deliverables."))
story.append(KeepTogether([diagram()]))
story.append(Spacer(1, 4))

story.append(P("Work plan", h1))
story.append(P(
    "<b>Phase 1, backbone (one week).</b> Download the two Innovate UK spreadsheets and pull "
    "every GtR project classified under the UKRI research subjects that cover the School's "
    "remit (biological sciences, medical and health interface, chemistry, environmental and "
    "earth sciences, and the relevant parts of materials and energy). The pull is deliberately "
    "broad; themes are assigned afterwards, so nothing is excluded at source. "
    "Extract every non-academic organisation that is a Project Partner on a studentship, grant "
    "or fellowship, or a participant on an Innovate UK project with a university partner. "
    "Record the grant type, host university, dates and value. This phase alone produces a "
    "usable first list."))
story.append(P(
    "<b>Phase 2, wide net (one week).</b> Query OpenAlex for papers since 2015 with at least "
    "one UK university author and a corporate funder or corporate co-author, restricted to "
    "the same subject areas. Count papers per company and per university. This captures "
    "companies whose support does not appear in UKRI data, such as directly funded "
    "studentships and contract research."))
story.append(P(
    "<b>Phase 3, precision (one week).</b> Collect current and archived industry-sponsored "
    "studentship and postdoc adverts, and the published partner lists of the named schemes "
    "and of fifteen to twenty peer universities and doctoral training partnerships strong in "
    "biosciences and chemistry. These confirm that a company has paid for people rather than "
    "only for projects."))
story.append(P(
    "<b>Phase 4, consolidation (three to five days).</b> Normalise company names, merge the "
    "sources into the evidence table, map each company to the School's research themes using "
    "its project titles, descriptions and paper subjects, and score each company by the "
    "number and recency of studentships, grants, co-funded papers and adverts. Flag companies "
    "with sites in Greater Manchester and the North West, and companies that have worked with "
    "post-1992 universities, since both are indicators of approachability."))

story.append(P("Deliverables", h1))
story.append(table([
    ["Deliverable", "Content", "Use"],
    ["Ranked target list", "Spreadsheet of companies with scores, themes, region, size and counts per evidence type, one sheet per source plus a master sheet.",
     "Prioritise approaches; share with academic leads by theme"],
    ["Company profiles", "One page per shortlisted company: what it funded, where, with whom, and the relevant School expertise.",
     "Brief academics before contact; support bids such as iCASE and KTP"],
    ["Benchmark", "How much industry-linked UKRI funding and how many iCASE studentships comparable universities hold in these subjects, against the School's own figures.",
     "Set realistic targets; evidence for School and Faculty planning"],
    ["Reproducible pipeline", "Scripts and documentation so the list can be refreshed each year as the public data is updated.",
     "Keep the list current without repeating the work"],
], [34*mm, 86*mm, 52*mm]))

story.append(P("Scope: the whole of the former Life Sciences and Natural Sciences departments", h1))
story.append(P(
    "The School of Biological and Chemical Sciences brings together the former Departments of "
    "Life Sciences and Natural Sciences, so the search must be at least as wide as both. "
    "Rather than filter the data to a short list of keywords, which would drop whole areas, "
    "the pipeline takes an inclusion-first approach: it pulls everything that UKRI, OpenAlex "
    "and the Research Excellence Framework classify under the broad subject classes below, "
    "and only then tags each record with a School theme. Anything that falls in the classes "
    "but matches no theme is kept and labelled as unassigned for later review. The table lists "
    "the research areas identified from the School's published material and the "
    "classification codes used to capture them."))
story.append(table([
    ["School area", "Research themes identified", "Classifications used for capture"],
    ["Biomedical and health sciences (Life Sciences)",
     "Infection science and clinical microbiology; cardiovascular and vascular biology; ageing and lifelong "
     "health; neuroscience; stem cells and regenerative medicine; genetics and genomics; physiology; "
     "blood sciences and haematology; cancer biology; immunology; nutrition and metabolism; "
     "bioinformatics and computational biology.",
     "UKRI subjects: Medical and health interface; Biological sciences. REF units of assessment 3 (Allied Health "
     "Professions, Dentistry, Nursing and Pharmacy) and 5 (Biological Sciences). OpenAlex: Medicine; "
     "Biochemistry, Genetics and Molecular Biology; Immunology and Microbiology; Neuroscience."],
    ["Molecular biosciences and biotechnology (Life Sciences)",
     "Molecular and cellular biology; biochemistry and enzymology; microbiology, fermentation and industrial "
     "microbiology; synthetic biology; biotechnology and bioprocessing; food and agricultural biosciences.",
     "UKRI subjects: Biological sciences; Agricultural and food science. REF unit 5. OpenAlex: Biochemistry, "
     "Genetics and Molecular Biology; Agricultural and Biological Sciences; Chemical Engineering."],
    ["Organismal biology, ecology and conservation (Natural Sciences)",
     "Ecology, evolution and animal behaviour; conservation, restoration and coastal ecology; biodiversity; "
     "statistical ecology; plant science; nature-based solutions; zoology and wildlife disease.",
     "UKRI subjects: Biological sciences; Environmental sciences (ecology and evolution). REF units 5 and 7. "
     "OpenAlex: Agricultural and Biological Sciences; Environmental Science."],
    ["Environmental and earth sciences (Natural Sciences)",
     "Environmental chemistry and pollution; endocrine-disrupting chemicals; water and soil science; "
     "climate and earth systems; physical geography; environmental monitoring and remote sensing; "
     "waste transformation and the circular economy.",
     "UKRI subjects: Environmental sciences; Earth sciences. REF unit 7 (Earth Systems and Environmental "
     "Sciences). OpenAlex: Environmental Science; Earth and Planetary Sciences."],
    ["Chemistry (Natural Sciences)",
     "Medicinal chemistry and chemical biology; organic and green chemistry; analytical chemistry and "
     "forensic analysis; materials and physical chemistry; electrochemistry, fuel cells and hydrogen; "
     "polymers and additive manufacturing materials; catalysis.",
     "UKRI subjects: Chemistry; Materials sciences; Energy. REF unit 8 (Chemistry). OpenAlex: Chemistry; "
     "Materials Science; Chemical Engineering; Energy."],
    ["Cross-cutting and facility-led",
     "Work linked to the Manchester Fuel Cell Innovation Centre, Print City and the Core Analytical Centre; "
     "drug discovery and pharmacology; biomaterials and medical devices; diagnostics and sensors; "
     "data science applied to any of the above.",
     "Captured through the classes above plus the Innovate UK sectors Health and Life Sciences, Chemicals, "
     "Materials, Energy, Agri-food and Environment."],
], [34*mm, 76*mm, 62*mm]))
story.append(Spacer(1, 6))
story.append(P(
    "Widening further is a matter of adding subject classes, not rewriting the pipeline: "
    "sport and exercise science, psychology or engineering could be included in a second run "
    "if the Faculty wants a cross-school list. All sources are open or published under the "
    "Open Government Licence; website scraping will respect terms of use and robots files, "
    "with manual export as the fallback. The evidence table records organisations, not "
    "individuals, so no personal data is held. The theme list above was compiled from the "
    "School's public pages and recruitment material and should be checked against the "
    "School's own research group list before Phase 1 begins."))

story.append(P("Limitations", h1))
story.append(P(
    "GtR records partner contributions as declared at award, not what was finally paid, and "
    "block-grant doctoral training partnerships list the training grant rather than every "
    "individual industrial student. Innovate UK data shows that a company and a university "
    "worked on the same project but not whether a student or researcher was funded. "
    "Company name matching is imperfect and will need a manual pass over the top few hundred "
    "entities. Directly negotiated studentships that were never advertised and never "
    "produced an acknowledged paper will be missed; this is unavoidable with public data."))

story.append(KeepTogether([P("Decisions needed", h1), P(
    "Three points would benefit from a steer from the Head of Research: confirmation that the "
    "theme table covers every group in the School, and any areas to add; whether the target list should be restricted to companies with a UK "
    "research presence or include overseas parents; and who in the School or the Research and "
    "Knowledge Exchange directorate should own the list once built, so that approaches to "
    "companies are coordinated rather than duplicated.")]))

def footer(canvas, doc_):
    canvas.saveState()
    canvas.setFont("Helvetica", 8)
    canvas.setFillColor(colors.HexColor("#777777"))
    canvas.drawRightString(A4[0] - 20*mm, 12*mm, "Page %d" % doc_.page)
    canvas.drawString(20*mm, 12*mm, "Industrial funders of research in biological and chemical sciences: proposal")
    canvas.restoreState()

docm = SimpleDocTemplate(OUT, pagesize=A4, leftMargin=20*mm, rightMargin=20*mm,
                         topMargin=18*mm, bottomMargin=20*mm,
                         title="Mapping industrial funders of university research",
                         author="Rémi Zallot")
docm.build(story, onFirstPage=footer, onLaterPages=footer)
print(OUT)
