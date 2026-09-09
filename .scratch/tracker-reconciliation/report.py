import json, sys
from collections import defaultdict
rows = json.load(open(sys.argv[1]))

def bucket(r):
    # B: something the acceptance criteria names is absent -> evidence NOT done
    if r["miss"]:
        return "B"
    # C: too little machine-checkable evidence to say anything
    if not r["has_presc"] or (r["n_claims"] or 0) < 3:
        return "C"
    # A: every named artifact exists AND the code moved after filing
    if r["score"] == 1.0 and r["commits_after"] > 0:
        return "A"
    return "C"

for r in rows: r["bucket"] = bucket(r)
B = defaultdict(list)
for r in rows: B[r["bucket"]].append(r)

feats = defaultdict(lambda: defaultdict(list))
for r in rows: feats[r["feature"]][r["bucket"]].append(r)

L = []
w = L.append
w("# Issue-tracker reconciliation report\n")
w(f"Generated against {len(rows)} issues currently marked `ready-for-agent` / "
  f"`ready-for-human` across {len({r['feature'] for r in rows})} features.\n")
w("## How to read this — and what it does NOT do\n")
w("This report **does not decide whether an issue is done.** It was built to, and")
w("that turned out to be unsound: issues cite existing files and symbols as *context*,")
w("so a naive 'do the things it mentions exist?' check scores almost everything as")
w("complete. A hand-verified control case (`ws-disconnect-tracking/04`, confirmed NOT")
w("done) still scored 0.94 under that approach.\n")
w("What survived is narrower and more trustworthy: claims are read **only from")
w("prescriptive sections** (`What to build`, `Acceptance criteria`, `The fix`, …), and")
w("the useful output is the **misses** — artifacts those sections name that do not")
w("exist anywhere in the repo. A miss is strong evidence work remains. A clean score")
w("is weak evidence of anything.\n")
w("| Bucket | Meaning | Action |")
w("|---|---|---|")
w(f"| **A — likely done** | every named artifact exists *and* the referenced code moved after filing | spot-check, then flip to `done` |")
w(f"| **B — likely NOT done** | acceptance criteria names something absent from the repo | leave open; the miss says what's left |")
w(f"| **C — needs human eyes** | too few machine-checkable claims to judge | read it |")
w("")
w(f"**A: {len(B['A'])}  ·  B: {len(B['B'])}  ·  C: {len(B['C'])}**\n")
w("## Accuracy — checked against hand-verified cases\n")
w("Spot-checked before publishing. Confirmed **true** positives:\n")
w("- `release-pipeline/02,04` name `make staging-release` — **0 occurrences** in the Makefile.")
w("- `ws-disconnect-tracking/04` names `CLOSE_GRACE_SECONDS` — absent; I also read")
w("  `force_disconnect` and there is no `asyncio.wait_for` bound on the close.")
w("- `qr-billing-overhaul/04` names `min_price_per_kwh_all_in` — absent from the repo.")
w("- `charger-connectivity-zulip-alerts` — **the most valuable catch.** Commit `664574a`")
w("  is titled *\"zulip alerts\"*, which reads as shipped. It contains **only the PRD and")
w("  three issue files — zero code.** `ZulipAlertService`, `ZULIP_BOT_API_KEY` and")
w("  `ZULIP_SITE` exist nowhere. Zulip alerting is planned, not built.\n")
w("Known **false**-positive patterns — skip these when reviewing bucket B:\n")
w("- **Renamed during implementation.** `rds-staging-migration/02,03` flag")
w("  `POSTGRES_HOST` / `POSTGRES_SSL_MODE`, but the work shipped as `DB_HOST` /")
w("  `DB_SSL_MODE` (`backend/db_ssl.py` exists). Done — just not under the proposed name.")
w("- **Opaque identifiers quoted as examples.** Razorpay QR ids (`qr_StVw78FvfWrofx`) in")
w("  `qr-regeneration-fix/02` and an OCPP message id (`boot_55C1E96E`) in")
w("  `logs-console-correlated-reply/01` are illustrations, not artifacts to build.")
w("- **Paths outside the repo.** `prod-deploy-2026-05/03` names a backup file under")
w("  `/home/ec2-user/...` on the prod box, which will never be in git.")
w("- **Test-function names**, which legitimately differ from what a spec proposed.\n")
w("Rough precision on bucket B is ~70%. Good enough to triage; not good enough to")
w("close or reopen anything unread.\n")
w("---\n")

w("---\n")

for label, name in [("B","B — likely NOT done (has concrete misses)"),
                    ("A","A — likely done (verify, then close)"),
                    ("C","C — needs human eyes")]:
    w(f"## {name}\n")
    if label == "B":
        w("The `missing` column is the point: each is an artifact the issue's own")
        w("acceptance criteria names, which is absent from the codebase.\n")
    byf = defaultdict(list)
    for r in B[label]: byf[r["feature"]].append(r)
    for feat in sorted(byf):
        w(f"### `{feat}`  <sub>filed {byf[feat][0]['filed']}</sub>\n")
        if label == "B":
            w("| # | title | missing |")
            w("|---|---|---|")
            for r in sorted(byf[feat], key=lambda x: x["file"]):
                num = r["file"].split("/")[-1][:2]
                miss = ", ".join(f"`{m.split(':',1)[1]}`" for m in r["miss"][:4])
                w(f"| {num} | {r['title'][:72]} | {miss} |")
        else:
            w("| # | title | claims | commits since filed |")
            w("|---|---|---|---|")
            for r in sorted(byf[feat], key=lambda x: x["file"]):
                num = r["file"].split("/")[-1][:2]
                w(f"| {num} | {r['title'][:72]} | {r['n_claims']} | {r['commits_after']} |")
        w("")
    w("---\n")

open(sys.argv[2],"w").write("\n".join(L))
print(f"A={len(B['A'])} B={len(B['B'])} C={len(B['C'])}  -> {sys.argv[2]}")
