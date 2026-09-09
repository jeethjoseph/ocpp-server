# Tracker reconciliation

`REPORT.md` is the output. Regenerate after any status edits:

```bash
python3 .scratch/tracker-reconciliation/audit.py  /tmp/audit.json
python3 .scratch/tracker-reconciliation/report.py /tmp/audit.json .scratch/tracker-reconciliation/REPORT.md
```

`audit.py` reads claims **only from prescriptive sections** of each open issue
(`What to build`, `Acceptance criteria`, `The fix`, …) and checks them against the
live repo. Reading the whole issue does not work — issues cite existing files and
symbols as context, so everything scores as complete.

The **misses** are the signal, not the score. See the accuracy section in `REPORT.md`.
