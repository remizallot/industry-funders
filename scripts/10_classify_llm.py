"""Optional stage: classify projects into School themes with a local language
model served by Ollama, replacing the keyword tags for GtR and Innovate UK
rows.

Two passes:
  1. Embeddings. Every project (title + abstract) and every theme description
     are embedded with a small embedding model; cosine similarity gives a
     primary theme, secondary themes and a confidence margin. Fast (tens of
     milliseconds per project on a laptop CPU).
  2. Chat model. Projects behind direct evidence (studentships, fellowships,
     KTPs, named partnerships) and projects whose embedding margin is small
     are re-read by a small instruction-tuned model that returns JSON with a
     primary theme, secondary themes, an outside-scope flag and a one-line
     justification. Slower (seconds per project on CPU); bounded by --max-llm.

Every model answer is cached in data/processed/llm_cache.jsonl, so reruns
only classify new projects. Output: data/processed/project_themes.csv, read
by 08_merge_all.py when present.

Environment: OLLAMA_HOST (default http://localhost:11434).
"""
import argparse, gzip, json, os, sys, time
import numpy as np, pandas as pd, requests, yaml

OLLAMA = os.environ.get("OLLAMA_HOST", "http://localhost:11434").rstrip("/")
CFG = yaml.safe_load(open("config/themes.yml"))
THEMES = CFG["themes"]
KEYS = list(THEMES)
OUTSIDE = CFG.get("outside_scope_description", "Outside the School's remit.")
CACHE = "data/processed/llm_cache.jsonl"
DIRECT = {"studentship", "fellowship", "ktp", "scheme_partner"}


# ----------------------------------------------------------------- Ollama
def ensure_model(name):
    have = {m["name"] for m in requests.get(f"{OLLAMA}/api/tags", timeout=30).json().get("models", [])}
    if name in have or f"{name}:latest" in have:
        return
    print(f"pulling {name} (first run only)", file=sys.stderr)
    r = requests.post(f"{OLLAMA}/api/pull", json={"name": name, "stream": False}, timeout=3600)
    r.raise_for_status()


def embed(model, texts):
    r = requests.post(f"{OLLAMA}/api/embed", json={"model": model, "input": texts}, timeout=600)
    r.raise_for_status()
    return np.array(r.json()["embeddings"], dtype=np.float32)


def chat_json(model, system, user, retries=2):
    for attempt in range(retries + 1):
        r = requests.post(f"{OLLAMA}/api/chat", json={
            "model": model, "stream": False, "format": "json",
            "options": {"temperature": 0, "num_ctx": 4096},
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}]}, timeout=600)
        r.raise_for_status()
        try:
            return json.loads(r.json()["message"]["content"])
        except (json.JSONDecodeError, KeyError):
            if attempt == retries:
                return None


# --------------------------------------------------------------- projects
def load_projects():
    ev = pd.read_csv("data/processed/evidence.csv", low_memory=False, dtype={"project_id": str})
    ev = ev[ev["source"].isin(["gtr", "innovate_uk"])]
    direct = ev.groupby(["source", "project_id"])["evidence_type"].agg(lambda s: bool(set(s) & DIRECT))
    want = direct.reset_index().rename(columns={"evidence_type": "direct"})
    gtr_ids = set(want.loc[want["source"] == "gtr", "project_id"])
    iuk_ids = set(want.loc[want["source"] == "innovate_uk", "project_id"])

    texts = {}
    with gzip.open("data/raw/gtr/projects.jsonl.gz", "rt") as fh:
        for line in fh:
            p = json.loads(line)
            if p["id"] in gtr_ids:
                texts[("gtr", p["id"])] = (p.get("title") or "", p.get("abstractText") or "")
    for f in ["data/raw/iuk_2016_to_present.xlsx", "data/raw/iuk_2004_to_2016.xlsx"]:
        df = pd.read_excel(f, usecols=["Project Number", "Project Title", "Public Description"]).drop_duplicates("Project Number")
        for pn, t, d in df.itertuples(index=False):
            pid = str(pn)
            if pid in iuk_ids and ("innovate_uk", pid) not in texts:
                texts[("innovate_uk", pid)] = (str(t) if pd.notna(t) else "", str(d) if pd.notna(d) else "")
    want["title"] = [texts.get((s, p), ("", ""))[0] for s, p in zip(want["source"], want["project_id"])]
    want["abstract"] = [texts.get((s, p), ("", ""))[1] for s, p in zip(want["source"], want["project_id"])]
    want = want[want["title"].str.strip().ne("")]
    print(f"projects to classify: {len(want)} ({want['direct'].sum()} behind direct evidence)", file=sys.stderr)
    return want.reset_index(drop=True)


def project_text(title, abstract, limit=1800):
    return f"{title}\n\n{abstract[:limit]}"


# ------------------------------------------------------------ pass 1: embed
def embed_pass(df, model, batch=32):
    ensure_model(model)
    theme_texts = [f"{THEMES[k]['label']}. {THEMES[k].get('description', '')}" for k in KEYS] + [OUTSIDE]
    T = embed(model, theme_texts)
    T /= np.linalg.norm(T, axis=1, keepdims=True)
    sims = np.zeros((len(df), len(theme_texts)), dtype=np.float32)
    t0 = time.time()
    for i in range(0, len(df), batch):
        chunk = [project_text(t, a) for t, a in zip(df["title"].iloc[i:i + batch], df["abstract"].iloc[i:i + batch])]
        E = embed(model, chunk)
        E /= np.linalg.norm(E, axis=1, keepdims=True)
        sims[i:i + batch] = E @ T.T
        if (i // batch) % 50 == 0:
            print(f"  embedded {min(i + batch, len(df))}/{len(df)} ({time.time() - t0:.0f}s)", file=sys.stderr)
    order = np.argsort(-sims[:, :len(KEYS)], axis=1)
    top = sims[np.arange(len(df)), order[:, 0]]
    second = sims[np.arange(len(df)), order[:, 1]]
    df["emb_primary"] = [KEYS[j] for j in order[:, 0]]
    df["emb_secondary"] = [";".join(KEYS[j] for j in row[1:3] if sims[i, j] >= top[i] - 0.03) for i, row in enumerate(order)]
    df["emb_margin"] = top - second
    df["emb_outside"] = sims[:, len(KEYS)] > top
    return df


# ------------------------------------------------------------- pass 2: LLM
SYSTEM = ("You classify research project descriptions into the research themes of a university school of "
          "biological and chemical sciences. Answer with JSON only.")


def llm_prompt(title, abstract):
    themes = "\n".join(f"- {k}: {THEMES[k]['label']}. {THEMES[k].get('description', '')}" for k in KEYS)
    return (f"Themes:\n{themes}\n- outside_scope: {OUTSIDE}\n\n"
            f"Project title: {title}\nProject description: {abstract[:2500]}\n\n"
            "Return JSON with keys: primary (one theme key, or \"outside_scope\"), secondary (list of up to two other theme keys, "
            "may be empty), justification (one sentence, under 30 words, saying what in the project supports the primary theme).")


def load_cache():
    out = {}
    if os.path.exists(CACHE):
        for line in open(CACHE):
            try:
                r = json.loads(line); out[(r["source"], r["project_id"], r["model"])] = r
            except json.JSONDecodeError:
                pass
    return out


def llm_pass(df, model, max_llm, margin):
    ensure_model(model)
    cache = load_cache()
    todo = df[(df["direct"] | (df["emb_margin"] < margin))].copy()
    todo = todo.sort_values(["direct", "emb_margin"], ascending=[False, True])
    todo = todo[[(s, p, model) not in cache for s, p in zip(todo["source"], todo["project_id"])]]
    print(f"LLM pass: {len(todo)} projects not yet cached; running up to {max_llm}", file=sys.stderr)
    t0 = time.time()
    with open(CACHE, "a") as fh:
        for n, r in enumerate(todo.head(max_llm).itertuples(index=False)):
            ans = chat_json(model, SYSTEM, llm_prompt(r.title, r.abstract))
            if not ans or not isinstance(ans, dict):
                continue
            prim = ans.get("primary")
            if prim not in KEYS and prim != "outside_scope":
                continue
            sec = [x for x in (ans.get("secondary") or []) if x in KEYS and x != prim][:2]
            rec = {"source": r.source, "project_id": r.project_id, "model": model, "primary": prim, "secondary": sec,
                   "justification": str(ans.get("justification", ""))[:300]}
            fh.write(json.dumps(rec) + "\n"); fh.flush()
            cache[(r.source, r.project_id, model)] = rec
            if n % 20 == 0:
                rate = (n + 1) / max(time.time() - t0, 1)
                print(f"  llm {n + 1}/{min(max_llm, len(todo))} ({rate * 60:.1f}/min)", file=sys.stderr)
    return cache


# ------------------------------------------------------------------- main
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--embed-model", default="nomic-embed-text")
    ap.add_argument("--llm-model", default="qwen2.5:3b")
    ap.add_argument("--max-llm", type=int, default=3000, help="maximum chat-model calls this run (0 skips the pass)")
    ap.add_argument("--llm-margin", type=float, default=0.02, help="embedding margin below which the chat model re-reads")
    ap.add_argument("--limit", type=int, default=0, help="only classify the first N projects (for benchmarking)")
    a = ap.parse_args()

    df = load_projects()
    if a.limit:
        df = df.head(a.limit)
    df = embed_pass(df, a.embed_model)
    cache = llm_pass(df, a.llm_model, a.max_llm, a.llm_margin) if a.max_llm > 0 else load_cache()

    rows = []
    for r in df.itertuples(index=False):
        c = cache.get((r.source, r.project_id, a.llm_model))
        if c:
            prim, sec, method, just = c["primary"], c["secondary"], "llm", c["justification"]
        else:
            prim, sec, method, just = ("outside_scope" if r.emb_outside else r.emb_primary), \
                [x for x in r.emb_secondary.split(";") if x], "embedding", ""
        rows.append({"source": r.source, "project_id": r.project_id, "primary_theme": prim,
                     "secondary_themes": ";".join(sec), "outside_scope": prim == "outside_scope",
                     "method": method, "confidence": round(float(r.emb_margin), 4), "justification": just,
                     "direct_evidence": bool(r.direct)})
    out = pd.DataFrame(rows)
    out.to_csv("data/processed/project_themes.csv", index=False)
    print(f"wrote project_themes.csv: {len(out)} projects; by method {out['method'].value_counts().to_dict()}; "
          f"outside scope {int(out['outside_scope'].sum())}", file=sys.stderr)
    print(out["primary_theme"].value_counts().to_string(), file=sys.stderr)


if __name__ == "__main__":
    main()
