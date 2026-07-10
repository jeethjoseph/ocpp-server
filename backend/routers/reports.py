"""Admin analytical reports.

Read-only, admin-only views computed **live on every request** — no snapshot
table and no server-side cache (see ADR 0025). The "refresh only when asked"
behaviour and the "last refreshed" label live entirely on the client; this
layer just runs the aggregation and returns a plain payload.

First report: QR customer retention cohorts (the Churn Report).
"""

import logging
import time
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from tortoise.transactions import in_transaction

from auth_middleware import require_admin
from models import User
from services.monitoring_service import MetricsCollector

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/admin/reports", tags=["reports"])

# QR customer identity = UPI handle, falling back to phone — the same key the
# parked analytics/refund_churn study uses. Appless QR customers are often not
# `User` rows, so we never key on user_id here.
_CK = "COALESCE(NULLIF(customer_vpa,''), NULLIF(customer_contact,''))"
_SUCCESS = "status IN ('PAID','CHARGING','COMPLETED','REFUNDED')"

# Cohort calendar periods are IST periods: `created_at` is stored UTC, but this
# is an India-only business, so a period boundary is an IST midnight. Without
# `AT TIME ZONE`, a charge just after IST-midnight buckets into the prior
# UTC period. See ADR 0025 / the CLAUDE.md timestamp rule.
_PERIOD = "date_trunc('{grain}', created_at AT TIME ZONE 'Asia/Kolkata')::date"

# grain -> the expression giving whole-periods-elapsed between a cohort's first
# period and an activity period. Whitelisted; no user-supplied string ever
# reaches the SQL string.
_GRAINS = {
    "week": "((p.period - c.cohort_period)/7)::int",
    "month": (
        "(EXTRACT(YEAR FROM age(p.period, c.cohort_period))*12"
        " + EXTRACT(MONTH FROM age(p.period, c.cohort_period)))::int"
    ),
}

# Bound the analytical scan so it can never compete unboundedly with live OCPP
# traffic on the shared instance if qr_payment ever grows (ADR 0025).
_STATEMENT_TIMEOUT_MS = 5000


def _cohort_sql(grain: str, offset_expr: str) -> str:
    period = _PERIOD.format(grain=grain)
    return f"""
    WITH p AS (
      SELECT {_CK} AS ck, {period} AS period
      FROM qr_payment WHERE {_SUCCESS} AND {_CK} IS NOT NULL
    ),
    cohort AS (SELECT ck, min(period) AS cohort_period FROM p GROUP BY ck),
    sizes AS (SELECT cohort_period, count(*) AS cohort_size FROM cohort GROUP BY cohort_period),
    activity AS (
      SELECT DISTINCT p.ck, c.cohort_period, {offset_expr} AS period_offset
      FROM p JOIN cohort c USING (ck)
    )
    SELECT to_char(a.cohort_period,'YYYY-MM-DD') AS cohort_period,
           s.cohort_size, a.period_offset, count(DISTINCT a.ck) AS active
    FROM activity a JOIN sizes s USING (cohort_period)
    GROUP BY 1,2,3 ORDER BY 1,3;
    """


def _summary_sql(grain: str) -> str:
    period = _PERIOD.format(grain=grain)
    return f"""
    WITH perc AS (
      SELECT {_CK} AS ck, count(*) AS sessions,
             sum(amount_paid - COALESCE(refund_amount,0)) AS net
      FROM qr_payment WHERE {_SUCCESS} AND {_CK} IS NOT NULL
      GROUP BY ck
    )
    SELECT count(*) AS customers,
           count(*) FILTER (WHERE sessions=1) AS one_time,
           count(*) FILTER (WHERE sessions>=2) AS repeat,
           round(avg(sessions),2) AS avg_sessions,
           round(avg(net),2) AS avg_ltv,
           round((percentile_cont(0.5) WITHIN GROUP (ORDER BY net))::numeric,2) AS median_ltv,
           sum(sessions) AS successful_sessions,
           round(sum(net),2) AS net_revenue,
           (SELECT to_char(max({period}),'YYYY-MM-DD')
              FROM qr_payment WHERE {_SUCCESS}) AS latest_period
    FROM perc;
    """


async def _run_report(grain: str):
    """Run both aggregations in one bounded, consistent read snapshot.

    REPEATABLE READ pins a single MVCC snapshot so the cohort grid and the
    summary can't disagree; the statement timeout is a scale guard-rail.
    """
    start = time.perf_counter()
    async with in_transaction("default") as conn:
        await conn.execute_query(f"SET LOCAL statement_timeout = {_STATEMENT_TIMEOUT_MS}")
        await conn.execute_query("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ")
        _, cohort_rows = await conn.execute_query(_cohort_sql(grain, _GRAINS[grain]))
        _, summary_rows = await conn.execute_query(_summary_sql(grain))
    MetricsCollector.record_metric(
        "Custom/Reports/QrChurn/DurationMs", (time.perf_counter() - start) * 1000
    )
    MetricsCollector.increment_counter("Custom/Reports/QrChurn/Request")
    return cohort_rows, summary_rows


def _shape_cohorts(rows) -> list[dict]:
    by_period: dict[str, dict] = {}
    for r in rows:
        c = by_period.setdefault(
            r["cohort_period"],
            {"cohort": r["cohort_period"], "size": int(r["cohort_size"]), "cells": []},
        )
        c["cells"].append({"offset": int(r["period_offset"]), "active": int(r["active"])})
    return sorted(by_period.values(), key=lambda c: c["cohort"])


def _shape_summary(row: dict) -> dict:
    def s(v):
        return None if v is None else str(v)

    return {
        "customers": int(row["customers"] or 0),
        "one_time": int(row["one_time"] or 0),
        "repeat": int(row["repeat"] or 0),
        "avg_sessions": s(row["avg_sessions"]),
        "avg_ltv": s(row["avg_ltv"]),
        "median_ltv": s(row["median_ltv"]),
        "successful_sessions": int(row["successful_sessions"] or 0),
        "net_revenue": s(row["net_revenue"]),
        "latest_period": row["latest_period"],
    }


@router.get("/qr-churn")
async def qr_churn_report(
    grain: str = Query("week", description="Cohort grain: week or month"),
    _admin: User = Depends(require_admin()),
):
    """QR customer retention cohorts, computed live in IST periods (ADR 0025)."""
    if grain not in _GRAINS:
        raise HTTPException(status_code=400, detail="grain must be 'week' or 'month'")

    cohort_rows, summary_rows = await _run_report(grain)
    cohorts = _shape_cohorts(cohort_rows)
    max_offset = max(
        (cell["offset"] for c in cohorts for cell in c["cells"]), default=0
    )
    summary = _shape_summary(summary_rows[0]) if summary_rows else {}
    return {
        "grain": grain,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "latest_period": summary.get("latest_period"),
        "max_offset": max_offset,
        "summary": summary,
        "cohorts": cohorts,
    }
