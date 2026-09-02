"""v2: only trust claims made in PRESCRIPTIVE sections, and add git recency.

v1 over-scored because issues cite existing files/symbols as *context*
("Problem", "Context"), which always resolve. What indicates completion is
whether the things named under "What to build" / "Acceptance criteria"
exist -- plus whether the referenced code actually moved after the issue
was filed.
"""
import os, re, json, subprocess, sys
from pathlib import Path
from collections import defaultdict

REPO = Path("/Users/raalshasan/makaratech/idofthings/ocpp-server")
SKIP = {".git","node_modules",".venv",".next","__pycache__",".scratch","dist",
        "build",".pytest_cache","coverage",".turbo"}
EXT = {".py",".ts",".tsx",".js",".jsx",".mjs",".yml",".yaml",".json",".sql",
       ".sh",".md",".toml",".ini",".example"}

blobs, PATHS = [], set()
for root, dirs, files in os.walk(REPO):
    dirs[:] = [d for d in dirs if d not in SKIP]
    for fn in files:
        p = Path(root)/fn; PATHS.add(str(p.relative_to(REPO)))
        if p.suffix in EXT or fn in ("Makefile","Dockerfile"):
            try:
                if p.stat().st_size <= 2_000_000:
                    blobs.append(p.read_text(errors="ignore"))
            except Exception: pass
CORPUS = "\n".join(blobs)
PATHSET = {p.lower() for p in PATHS}
BASENAMES = {os.path.basename(p) for p in PATHSET}

PRESCRIPTIVE = re.compile(r"^##+\s*(what to build|acceptance criteria|proposed|"
                          r"the fix|implementation|tasks|deliverable)", re.I)
ANY_HEADING  = re.compile(r"^##+\s+", re.M)

RE_TICK = re.compile(r"`([^`\n]{2,90})`")
RE_ADR  = re.compile(r"\bADR\s*(\d{3,4})\b", re.I)
RE_MAKE = re.compile(r"\bmake\s+([a-z][a-z0-9-]{3,40})\b")
RE_ENV  = re.compile(r"\b([A-Z][A-Z0-9]{2,}(?:_[A-Z0-9]+){1,6})\b")
RE_PATHY= re.compile(r"^[\w./\[\]@-]+\.(py|tsx?|jsx?|mjs|ya?ml|sql|sh|json|md)$")
RE_SYM  = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{4,60}$")
NOISE = {"TODO","NOTE","WARNING","HTTP","HTTPS","JSON","NULL","TRUE","FALSE","API",
         "URL","SQL","UTC","IST","GST","OCPP","RDS","AWS","PDF","CSV","NRQL","OTLP"}

def prescriptive_text(text):
    """Slice out only the sections that say what to BUILD."""
    lines = text.splitlines(); keep, on = [], False
    for ln in lines:
        if ANY_HEADING.match(ln):
            on = bool(PRESCRIPTIVE.match(ln))
            continue
        if on: keep.append(ln)
    return "\n".join(keep)

def claims(text):
    out = defaultdict(set)
    for m in RE_TICK.finditer(text):
        t = m.group(1).strip()
        if RE_PATHY.match(t): out["path"].add(t)
        elif RE_SYM.match(t) and ("_" in t or t[0].isupper()):
            # Skip auto-memory wikilinks (project_/feedback_/reference_*) --
            # they are memory filenames, not code symbols.
            if not re.match(r"^(project|feedback|reference)_", t):
                out["symbol"].add(t)
    for m in RE_ADR.finditer(text):  out["adr"].add(m.group(1).zfill(4))
    for m in RE_MAKE.finditer(text):
        # Real targets are hyphenated (staging-release, prod-deploy). Without
        # this, English prose -- "make them", "make future" -- becomes a claim.
        if "-" in m.group(1): out["make"].add(m.group(1))
    for m in RE_ENV.finditer(text):
        if m.group(1) not in NOISE and len(m.group(1)) > 6: out["env"].add(m.group(1))
    return {k: sorted(v) for k, v in out.items()}

def check(kind, c):
    if kind == "path":
        cl = c.lower().lstrip("./")
        return any(p.endswith(cl) or p == cl for p in PATHSET) or os.path.basename(cl) in BASENAMES
    if kind == "adr":  return any(p.startswith(f"docs/adr/{c}") for p in PATHS)
    if kind == "make": return f"\n{c}:" in CORPUS
    return c in CORPUS

def git(*a):
    return subprocess.run(["git",*a], cwd=REPO, capture_output=True, text=True).stdout.strip()

rows = []
for issue in sorted((REPO/".scratch").glob("*/issues/*.md")):
    text = issue.read_text(errors="ignore")
    m = re.search(r"^Status:\s*(.+)$", text, re.M|re.I)
    status = m.group(1).strip() if m else "<none>"
    if not re.match(r"ready-for-(agent|human)\s*$", status, re.I): continue
    tm = re.search(r"^#\s+(.+)$", text, re.M)
    title = tm.group(1).strip() if tm else issue.stem

    presc = prescriptive_text(text)
    cl = claims(presc) if presc.strip() else {}
    hits, miss = [], []
    for kind, items in cl.items():
        for it in items:
            (hits if check(kind,it) else miss).append(f"{kind}:{it}")
    total = len(hits)+len(miss)
    score = len(hits)/total if total else None

    filed = git("log","-1","--format=%cs","--",str(issue.parent)) or None
    # did the code this issue names actually move after it was filed?
    moved = 0
    ref_paths = [c for c in cl.get("path",[]) if check("path",c)]
    for rp in ref_paths[:6]:
        cand = [p for p in PATHS if p.lower().endswith(rp.lower().lstrip("./"))]
        if cand and filed:
            n = git("log","--oneline",f"--since={filed}","--",cand[0])
            moved += len([l for l in n.splitlines() if l.strip()])
    rows.append({"feature":issue.parent.parent.name,"file":str(issue.relative_to(REPO)),
                 "title":title,"status":status,"score":score,"n_claims":total,
                 "hits":hits[:10],"miss":miss[:10],"filed":filed or "uncommitted",
                 "commits_after":moved,"has_presc":bool(presc.strip())})

json.dump(rows, open(sys.argv[1],"w"), indent=1)
print(f"v2 audited {len(rows)} open issues")
