"use client";

import { Card, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Zap, Clock } from "lucide-react";
import { QRActiveSessionItem } from "@/lib/api-services";
import { formatAmount } from "@/lib/utils";
import { useElapsedSince } from "@/lib/hooks/useNowTick";

const SUB_STATE_META: Record<
  QRActiveSessionItem["sub_state"],
  { label: string; pill: string; dot: string }
> = {
  waiting: {
    label: "Waiting to plug in",
    pill: "bg-amber-100 text-amber-900 dark:bg-amber-900/30 dark:text-amber-200",
    dot: "bg-amber-500",
  },
  charging: {
    label: "Charging",
    pill: "bg-green-100 text-green-900 dark:bg-green-900/30 dark:text-green-200",
    dot: "bg-green-500",
  },
  paused: {
    label: "Paused",
    pill: "bg-amber-100 text-amber-900 dark:bg-amber-900/30 dark:text-amber-200",
    dot: "bg-amber-500",
  },
  stopping: {
    label: "Stopping…",
    pill: "bg-blue-100 text-blue-900 dark:bg-blue-900/30 dark:text-blue-200",
    dot: "bg-blue-500",
  },
};

function formatStartedAt(iso: string): { date: string; time: string } {
  const d = new Date(iso);
  return {
    date: d.toLocaleDateString("en-IN", { day: "numeric", month: "short", year: "numeric" }),
    time: d.toLocaleTimeString("en-IN", { hour: "2-digit", minute: "2-digit" }),
  };
}

function formatRemainingMinutes(seconds: number | undefined): string {
  if (!seconds || seconds <= 0) return "shortly";
  const m = Math.ceil(seconds / 60);
  return m === 1 ? "1 minute" : `${m} minutes`;
}

export function ActiveSessionCard({ session }: { session: QRActiveSessionItem }) {
  const meta = SUB_STATE_META[session.sub_state];
  const duration = useElapsedSince(session.started_at);
  const started = formatStartedAt(session.started_at);

  const amountPaidNum = Number(session.amount_paid);
  const spentNum = session.spent_so_far ? Number(session.spent_so_far) : 0;
  const budgetPct =
    amountPaidNum > 0
      ? Math.min(100, Math.max(0, (spentNum / amountPaidNum) * 100))
      : 0;

  return (
    <Card className="border-0 shadow-md bg-card">
      <CardContent className="p-4 space-y-3">
        <div className="flex items-start justify-between gap-2">
          <div className="space-y-0.5">
            <Badge className={`border-0 ${meta.pill}`}>
              <span className={`inline-block w-1.5 h-1.5 rounded-full mr-1.5 ${meta.dot}`} />
              {meta.label}
            </Badge>
            <p className="text-sm font-medium text-card-foreground mt-1">
              {session.charger_name}
              {session.station_name ? ` · ${session.station_name}` : ""}
            </p>
            {session.franchisee_name && (
              <p className="text-xs text-muted-foreground">
                Operator: <span className="font-medium">{session.franchisee_name}</span>
              </p>
            )}
          </div>
          <div className="text-right text-[11px] text-muted-foreground">
            Started {started.date}
            <br />
            {started.time}
          </div>
        </div>

        {session.sub_state === "waiting" ? (
          <div className="p-3 bg-amber-50 dark:bg-amber-900/10 border border-amber-200 dark:border-amber-700/40 rounded-lg">
            <div className="text-base font-semibold text-amber-900 dark:text-amber-200">
              ₹{formatAmount(session.amount_paid)} paid · waiting to start
            </div>
            <div className="text-xs text-amber-800 dark:text-amber-300 mt-1">
              Plug in your car to start charging. We&apos;ll auto-refund in{" "}
              {formatRemainingMinutes(session.stale_threshold_seconds)} if you don&apos;t
              plug in.
            </div>
          </div>
        ) : (
          <>
            <div className="grid grid-cols-2 gap-3">
              <div className="p-2 bg-muted/50 rounded-lg">
                <p className="text-xs text-muted-foreground">Energy delivered</p>
                <p className="font-semibold text-card-foreground">
                  {session.energy_kwh != null
                    ? `${Number(session.energy_kwh).toFixed(2)} kWh`
                    : "—"}
                </p>
              </div>
              <div className="p-2 bg-muted/50 rounded-lg">
                <p className="text-xs text-muted-foreground">Spent so far</p>
                <p className="font-semibold text-card-foreground">
                  ₹{formatAmount(session.spent_so_far)}
                </p>
              </div>
            </div>

            <div className="flex items-center justify-between text-xs text-muted-foreground">
              <div className="flex items-center gap-1.5">
                <Zap className="h-3.5 w-3.5" />
                <span>
                  {session.sub_state === "paused"
                    ? "0 kW"
                    : session.power_kw != null
                      ? `${session.power_kw.toFixed(1)} kW`
                      : "—"}
                </span>
              </div>
              <div className="flex items-center gap-1.5">
                <Clock className="h-3.5 w-3.5" />
                <span>{duration}</span>
              </div>
            </div>

            <div className="border-t border-border pt-2 space-y-2 text-sm">
              <div className="flex justify-between">
                <span className="text-muted-foreground">Refund if you stop now:</span>
                <span className="font-medium text-card-foreground">
                  ₹{formatAmount(session.refund_if_stopped_now)}
                </span>
              </div>
              <div>
                <div className="flex justify-between text-xs text-muted-foreground mb-1">
                  <span>Budget</span>
                  <span>
                    ₹{formatAmount(session.spent_so_far)} / ₹{formatAmount(session.amount_paid)}
                  </span>
                </div>
                <div className="h-1.5 w-full bg-muted rounded-full overflow-hidden">
                  <div
                    className="h-full bg-green-500 dark:bg-green-400 transition-all"
                    style={{ width: `${budgetPct}%` }}
                  />
                </div>
              </div>
            </div>

            {session.sub_state === "paused" && (
              <p className="text-xs text-amber-700 dark:text-amber-300">
                Charger lost contact — your session is on hold and will auto-resume
                when it reconnects.
              </p>
            )}
            {session.sub_state === "stopping" && (
              <p className="text-xs text-blue-700 dark:text-blue-300">
                Wrapping up — final bill in a moment.
              </p>
            )}
          </>
        )}
      </CardContent>
    </Card>
  );
}

export function ActiveSessionSkeleton() {
  return (
    <Card className="border-0 shadow-md bg-card">
      <CardContent className="p-4 space-y-3 animate-pulse">
        <div className="flex justify-between items-start">
          <div className="space-y-2">
            <div className="h-5 w-24 bg-muted rounded" />
            <div className="h-4 w-40 bg-muted rounded" />
          </div>
          <div className="h-3 w-16 bg-muted rounded" />
        </div>
        <div className="grid grid-cols-2 gap-3">
          <div className="h-12 bg-muted/50 rounded-lg" />
          <div className="h-12 bg-muted/50 rounded-lg" />
        </div>
        <div className="h-1.5 w-full bg-muted rounded-full" />
      </CardContent>
    </Card>
  );
}
