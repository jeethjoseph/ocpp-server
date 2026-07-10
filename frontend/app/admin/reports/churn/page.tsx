"use client";

import { useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { RefreshCw, ArrowLeft } from "lucide-react";
import { AdminOnly } from "@/components/RoleWrapper";
import { Button } from "@/components/ui/button";
import {
  useQRChurnReport,
  type Grain,
  type Cohort,
  type QRChurnReport,
} from "@/lib/queries/admin-reports";

// ---- formatting helpers -------------------------------------------------

/** Whole periods between two calendar-date period starts (YYYY-MM-DD). */
function periodsBetween(from: string, to: string, grain: Grain): number {
  const a = new Date(from + "T00:00:00Z");
  const b = new Date(to + "T00:00:00Z");
  if (grain === "week") return Math.round((+b - +a) / (7 * 864e5));
  return (
    (b.getUTCFullYear() - a.getUTCFullYear()) * 12 +
    (b.getUTCMonth() - a.getUTCMonth())
  );
}

function periodLabel(iso: string, grain: Grain): string {
  const d = new Date(iso + "T00:00:00Z");
  return grain === "week"
    ? d.toLocaleDateString("en-GB", { day: "2-digit", month: "short", timeZone: "UTC" })
    : d.toLocaleDateString("en-GB", { month: "short", year: "numeric", timeZone: "UTC" });
}

/** Relative "x ago" for the last-refreshed label. */
function timeAgo(ms: number): string {
  const s = Math.max(0, Math.round((Date.now() - ms) / 1000));
  if (s < 45) return "just now";
  const m = Math.round(s / 60);
  if (m < 60) return `${m} min ago`;
  const h = Math.round(m / 60);
  if (h < 24) return `${h} hour${h > 1 ? "s" : ""} ago`;
  const d = Math.round(h / 24);
  return `${d} day${d > 1 ? "s" : ""} ago`;
}

function istAbsolute(ms: number): string {
  return new Date(ms).toLocaleString("en-IN", { timeZone: "Asia/Kolkata" }) + " IST";
}

// ---- derived cohort math ------------------------------------------------

function cellMap(c: Cohort): Map<number, number> {
  return new Map(c.cells.map((cell) => [cell.offset, cell.active]));
}

/** Blended retention: for each offset, % of customers (across cohorts old
 * enough to have reached it) who were active. Denominator excludes cohorts
 * that cannot yet have observed that offset. */
function blendedCurve(report: QRChurnReport, maxK: number) {
  const latest = report.latest_period;
  const pts: { k: number; pct: number; den: number }[] = [];
  for (let k = 0; k <= maxK; k++) {
    let num = 0;
    let den = 0;
    for (const c of report.cohorts) {
      const obs = latest ? periodsBetween(c.cohort, latest, report.grain) : 0;
      if (obs < k) continue;
      den += c.size;
      num += cellMap(c).get(k) ?? 0;
    }
    pts.push({ k, pct: den ? (100 * num) / den : 0, den });
  }
  return pts;
}

// ---- page ---------------------------------------------------------------

export default function ChurnReportPage() {
  const [grain, setGrain] = useState<Grain>("week");
  const q = useQRChurnReport(grain);
  const report = q.data;

  // Re-render every 30s so "last refreshed x ago" stays current.
  const [, tick] = useState(0);
  useEffect(() => {
    const id = setInterval(() => tick((n) => n + 1), 30_000);
    return () => clearInterval(id);
  }, []);

  const unit = grain === "week" ? "week" : "month";

  return (
    <AdminOnly fallback={<p className="p-6 text-muted-foreground">Admins only.</p>}>
      <div className="churn mx-auto max-w-5xl px-4 py-8">
        <ChurnStyles />

        <Link
          href="/admin/reports"
          className="mb-4 inline-flex items-center gap-1 text-sm text-muted-foreground hover:text-foreground"
        >
          <ArrowLeft className="size-4" /> Reports
        </Link>

        <header className="mb-5 flex flex-wrap items-end justify-between gap-4">
          <div>
            <h1 className="text-2xl font-semibold tracking-tight">
              Customer churn &amp; retention
            </h1>
            <p className="mt-1 max-w-2xl text-sm text-muted-foreground">
              QR customers grouped by the {unit} of their first charge, and the
              share who came back and paid again. Identity is the customer&apos;s
              UPI handle / phone. Prod, live from Postgres.
            </p>
          </div>
          <div className="flex items-center gap-3">
            <div className="inline-flex rounded-lg border p-0.5">
              {(["week", "month"] as Grain[]).map((g) => (
                <button
                  key={g}
                  onClick={() => setGrain(g)}
                  aria-pressed={grain === g}
                  className={`rounded-md px-3 py-1 text-sm capitalize transition-colors ${
                    grain === g
                      ? "bg-primary text-primary-foreground"
                      : "text-muted-foreground hover:text-foreground"
                  }`}
                >
                  {g}ly
                </button>
              ))}
            </div>
            <Button
              variant="outline"
              size="sm"
              onClick={() => q.refetch()}
              disabled={q.isFetching}
            >
              <RefreshCw
                className={`size-4 ${q.isFetching ? "animate-spin" : ""}`}
              />
              Refresh
            </Button>
          </div>
        </header>

        <p className="mb-6 text-xs text-muted-foreground">
          {q.isFetching ? (
            "Refreshing…"
          ) : q.dataUpdatedAt ? (
            <>
              Last refreshed{" "}
              <span title={istAbsolute(q.dataUpdatedAt)} className="font-medium text-foreground">
                {timeAgo(q.dataUpdatedAt)}
              </span>
            </>
          ) : null}
        </p>

        {q.isLoading && <SkeletonBlock />}
        {q.isError && (
          <p className="rounded-lg border border-destructive/40 bg-destructive/5 p-4 text-sm text-destructive">
            Couldn&apos;t load the report. Hit Refresh to try again.
          </p>
        )}

        {report && report.cohorts.length === 0 && !q.isFetching && <EmptyState />}

        {report && report.cohorts.length > 0 && (
          <>
            <SummaryTiles report={report} />
            <CohortTriangle report={report} />
            <div className="mt-6 grid gap-5 md:grid-cols-[1.15fr_.85fr]">
              <RetentionCurve report={report} />
              <SmallNNote />
            </div>
          </>
        )}
      </div>
    </AdminOnly>
  );
}

// ---- summary tiles ------------------------------------------------------

function SummaryTiles({ report }: { report: QRChurnReport }) {
  const s = report.summary;
  const repeatPct = s.customers ? Math.round((100 * s.repeat) / s.customers) : 0;
  const p1 = blendedCurve(report, 1)[1];
  // No cohort is old enough to have a next-period observation yet → "—", not
  // a misleading 0% (which would read as "nobody returned").
  const nextReturn = p1 && p1.den > 0 ? `${Math.round(p1.pct)}%` : "—";
  const unit = report.grain === "week" ? "week" : "month";

  const tiles = [
    { k: "QR customers", v: String(s.customers), sub: "distinct UPI identities" },
    { k: "Ever repeat", v: `${repeatPct}%`, sub: `${s.repeat} charged ≥ 2×` },
    { k: `Next-${unit} return`, v: nextReturn, sub: `came back the next ${unit}` },
    { k: "Avg sessions", v: s.avg_sessions ?? "—", sub: "per customer" },
  ];

  return (
    <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
      {tiles.map((t) => (
        <div key={t.k} className="rounded-xl border bg-card p-4">
          <p className="text-[11px] uppercase tracking-wide text-muted-foreground">
            {t.k}
          </p>
          <p className="mt-2 text-3xl font-semibold tabular-nums leading-none">
            {t.v}
          </p>
          <p className="mt-1.5 text-xs text-muted-foreground">{t.sub}</p>
        </div>
      ))}
    </div>
  );
}

// ---- cohort triangle ----------------------------------------------------

function CohortTriangle({ report }: { report: QRChurnReport }) {
  const unit = report.grain === "week" ? "Weeks" : "Months";
  const cols = Array.from({ length: report.max_offset + 1 }, (_, i) => i);

  return (
    <div className="mt-6 rounded-xl border bg-card p-5">
      <h2 className="text-sm font-semibold">Retention cohort triangle</h2>
      <p className="mt-0.5 text-xs text-muted-foreground">
        Cell = % of the cohort active that {report.grain} (small number = customer
        count). Hatched = not yet observable. · = observed, none returned.
      </p>
      <div className="mt-4 overflow-x-auto pb-1">
        <table className="cohort-heat">
          <thead>
            <tr>
              <th className="rowhead">First-charge {report.grain}</th>
              {cols.map((k) => (
                <th key={k}>{k}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {report.cohorts.map((c) => (
              <CohortRow key={c.cohort} cohort={c} report={report} cols={cols} />
            ))}
          </tbody>
        </table>
      </div>
      <div className="mt-4 flex flex-wrap items-center gap-x-5 gap-y-2 text-[11px] text-muted-foreground">
        <span className="inline-flex items-center gap-2">
          Retention
          <span className="heat-ramp" />0% → 100%
        </span>
        <span>
          <span className="sw sw-zero" /> observed, none returned
        </span>
        <span>
          <span className="sw sw-na" /> not yet observable
        </span>
        <span className="ml-auto">Grain: {unit.toLowerCase()} since first charge</span>
      </div>
    </div>
  );
}

function CohortRow({
  cohort,
  report,
  cols,
}: {
  cohort: Cohort;
  report: QRChurnReport;
  cols: number[];
}) {
  const map = useMemo(() => cellMap(cohort), [cohort]);
  const obs = report.latest_period
    ? periodsBetween(cohort.cohort, report.latest_period, report.grain)
    : 0;

  return (
    <tr>
      <td className="rowhead">
        <span className="wk">{periodLabel(cohort.cohort, report.grain)}</span>
        <span className="sz">n={cohort.size}</span>
      </td>
      {cols.map((k) => {
        if (k > obs) return <td key={k} className="na" />;
        const n = map.get(k) ?? 0;
        if (n === 0)
          return (
            <td key={k} className="zero">
              ·
            </td>
          );
        const pct = Math.round((100 * n) / cohort.size);
        const r = Math.sqrt(pct / 100);
        return (
          <td
            key={k}
            className={`cell${r > 0.52 ? " hot" : ""}`}
            style={{ ["--r" as string]: r.toFixed(3) }}
            title={`${periodLabel(cohort.cohort, report.grain)} · +${k}: ${n}/${cohort.size}`}
          >
            <span className="pct">{pct}</span>
            <span className="n">{n}</span>
          </td>
        );
      })}
    </tr>
  );
}

// ---- blended retention curve -------------------------------------------

function RetentionCurve({ report }: { report: QRChurnReport }) {
  const maxK = Math.min(report.max_offset, report.grain === "week" ? 8 : 6);
  const pts = blendedCurve(report, maxK);
  const W = 460;
  const H = 220;
  const ml = 34;
  const mr = 14;
  const mt = 16;
  const mb = 30;
  const iw = W - ml - mr;
  const ih = H - mt - mb;
  const x = (k: number) => ml + (maxK ? (k / maxK) * iw : 0);
  const y = (p: number) => mt + (1 - p / 100) * ih;
  const line = pts
    .map((p, i) => `${i ? "L" : "M"}${x(p.k).toFixed(1)},${y(p.pct).toFixed(1)}`)
    .join(" ");
  const area =
    `M${x(0)},${y(0)} ` +
    pts.map((p) => `L${x(p.k).toFixed(1)},${y(p.pct).toFixed(1)}`).join(" ") +
    ` L${x(maxK)},${y(0)} Z`;
  const unit = report.grain === "week" ? "weeks" : "months";

  return (
    <div className="rounded-xl border bg-card p-5">
      <h2 className="text-sm font-semibold">Blended retention curve</h2>
      <p className="mt-0.5 text-xs text-muted-foreground">
        All cohorts pooled — % still returning N {unit} after their first charge.
      </p>
      <svg className="curve mt-3 w-full" viewBox={`0 0 ${W} ${H}`} role="img" aria-label="Blended retention curve">
        {[0, 25, 50, 75, 100].map((g) => (
          <g key={g}>
            <line className="cv-grid" x1={ml} y1={y(g)} x2={W - mr} y2={y(g)} />
            <text className="cv-axis" x={ml - 6} y={y(g) + 3} textAnchor="end">
              {g}
            </text>
          </g>
        ))}
        {pts.map((p) => (
          <text key={p.k} className="cv-axis" x={x(p.k)} y={H - 10} textAnchor="middle">
            {p.k}
          </text>
        ))}
        <path className="cv-area" d={area} />
        <path className="cv-line" d={line} />
        {pts.map((p, i) => (
          <g key={p.k}>
            {(i === 0 || i === 1 || i === pts.length - 1) && (
              <text className="cv-lab" x={x(p.k)} y={y(p.pct) - 9} textAnchor="middle">
                {Math.round(p.pct)}%
              </text>
            )}
            <circle className="cv-dot" cx={x(p.k)} cy={y(p.pct)} r={3.4} />
          </g>
        ))}
      </svg>
    </div>
  );
}

function SmallNNote() {
  return (
    <div className="space-y-3">
      <div className="rounded-xl border border-amber-500/40 bg-amber-500/10 p-4 text-sm">
        <p>
          <b className="text-amber-600 dark:text-amber-400">Small cohorts — read directionally.</b>{" "}
          Cohorts run a few dozen customers, so one person can swing a cell many
          points. Trust the shape, not the decimals. Because charging cadence is
          monthly, the <b>monthly</b> view is usually the more honest retention read.
        </p>
      </div>
      <div className="rounded-xl border bg-muted/30 p-4 text-xs text-muted-foreground">
        <p className="mb-1 font-medium text-foreground">How a customer is counted</p>
        <p>
          Identity is the UPI handle, falling back to phone — a customer who pays
          via both may appear twice (inflating counts, understating retention).
          A customer counts from their first captured payment; a fully-refunded
          session still counts as an engaged customer at ₹0 net. Periods are IST
          calendar weeks / months.
        </p>
      </div>
    </div>
  );
}

function EmptyState() {
  return (
    <div className="rounded-xl border bg-card p-10 text-center">
      <p className="text-sm font-medium">No QR customer data yet</p>
      <p className="mx-auto mt-1 max-w-sm text-sm text-muted-foreground">
        Once QR charging sessions are recorded, retention cohorts will appear
        here. Hit Refresh after the first payments land.
      </p>
    </div>
  );
}

function SkeletonBlock() {
  return (
    <div className="animate-pulse space-y-4">
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        {[0, 1, 2, 3].map((i) => (
          <div key={i} className="h-24 rounded-xl border bg-muted/40" />
        ))}
      </div>
      <div className="h-72 rounded-xl border bg-muted/40" />
    </div>
  );
}

// ---- scoped visual tokens for the heatmap & curve ----------------------

function ChurnStyles() {
  return (
    <style>{`
      .churn {
        --heat-weak: #edf5f2; --heat-strong: #0d5f4f;
        --hot-ink: #eafaf5; --cold-ink: #21302c;
        --hl: #e0e8e5; --na: #eef2f1; --accent: #0f6b5a;
      }
      .dark .churn, [data-theme="dark"] .churn {
        --heat-weak: #16211e; --heat-strong: #46e0bd;
        --hot-ink: #06201a; --cold-ink: #b9c9c4;
        --hl: #24302d; --na: #131c1a; --accent: #4fd0b0;
      }
      .cohort-heat { border-collapse: separate; border-spacing: 3px;
        font-variant-numeric: tabular-nums;
        font-family: ui-monospace, "SF Mono", Menlo, monospace; }
      .cohort-heat th { font-weight: 600; font-size: 11px; color: var(--muted-foreground, #6b7280);
        font-family: inherit; padding: 0 4px 6px; text-align: center; }
      .cohort-heat th.rowhead { text-align: left; }
      .cohort-heat td.rowhead { text-align: left; white-space: nowrap; padding-right: 12px; }
      .cohort-heat .rowhead .wk { font-size: 12.5px; font-weight: 550; }
      .cohort-heat .rowhead .sz { font-size: 11px; opacity: .55; margin-left: 7px; }
      .cohort-heat td.cell { width: 46px; height: 40px; text-align: center; vertical-align: middle;
        border-radius: 7px; font-size: 12.5px; font-weight: 600; color: var(--cold-ink);
        background: color-mix(in oklab, var(--heat-strong) calc(var(--r) * 100%), var(--heat-weak)); }
      .cohort-heat td.cell.hot { color: var(--hot-ink); }
      .cohort-heat td.cell .pct { display: block; line-height: 1; }
      .cohort-heat td.cell .n { display: block; font-size: 9.5px; opacity: .72; margin-top: 2px; font-weight: 500; }
      .cohort-heat td.zero { background: var(--heat-weak); opacity: .6; border-radius: 7px; width: 46px; height: 40px; }
      .cohort-heat td.na { border-radius: 7px;
        background: repeating-linear-gradient(-45deg, transparent, transparent 5px,
          color-mix(in oklab, var(--hl) 65%, transparent) 5px,
          color-mix(in oklab, var(--hl) 65%, transparent) 6px); }
      .heat-ramp { display: inline-block; width: 120px; height: 10px; border-radius: 5px;
        border: 1px solid var(--hl);
        background: linear-gradient(90deg, var(--heat-weak), var(--heat-strong)); vertical-align: -1px; }
      .sw { display: inline-block; width: 13px; height: 13px; border-radius: 3px; vertical-align: -2px; margin-right: 4px; border: 1px solid var(--hl); }
      .sw-zero { background: var(--heat-weak); }
      .sw-na { background: repeating-linear-gradient(-45deg, transparent, transparent 3px, var(--hl) 3px, var(--hl) 4px); }
      .curve .cv-axis { fill: var(--muted-foreground, #6b7280); font-size: 10px; font-family: ui-monospace, monospace; }
      .curve .cv-grid { stroke: var(--hl); stroke-width: 1; }
      .curve .cv-area { fill: color-mix(in oklab, var(--accent) 16%, transparent); }
      .curve .cv-line { fill: none; stroke: var(--accent); stroke-width: 2.4; stroke-linejoin: round; stroke-linecap: round; }
      .curve .cv-dot { fill: var(--card, #fff); stroke: var(--accent); stroke-width: 2; }
      .curve .cv-lab { fill: currentColor; font-size: 10.5px; font-weight: 650; font-family: ui-monospace, monospace; }
    `}</style>
  );
}
