"use client";

import { useEffect, useState } from "react";
import { FranchiseeOnly } from "@/components/RoleWrapper";
import { usePortalSettlements } from "@/lib/queries/franchisee-portal";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { Banknote, MinusCircle, AlertTriangle } from "lucide-react";
import Link from "next/link";
import { formatINR } from "@/lib/utils";

const STATUS_COLORS: Record<string, string> = {
  PENDING: "bg-yellow-100 text-yellow-800",
  TRANSFER_PROCESSED: "bg-green-100 text-green-800",
  FAILED: "bg-red-100 text-red-800",
  ON_HOLD: "bg-orange-100 text-orange-800",
  SETTLED: "bg-blue-100 text-blue-800",
  BELOW_THRESHOLD: "bg-slate-100 text-slate-700",
};

function SettlementStatusBadge({ status }: { status: string }) {
  return (
    <Badge
      variant="secondary"
      className={`${STATUS_COLORS[status] || ""} inline-flex items-center gap-1`}
    >
      {status === "BELOW_THRESHOLD" && <MinusCircle className="h-3 w-3" />}
      {status.replace(/_/g, " ")}
    </Badge>
  );
}

interface SettlementEntry {
  id: number;
  created_at: string;
  payment_method?: string | null;
  gross_amount: string | number;
  franchisee_payout: string | number;
  settlement_status: string;
}

interface SettlementSummary {
  total_gross: string;
  total_payout: string;
  payout_settled: string;
  payout_pending: string;
  total_tds: string;
  failed_count: number;
}

type Preset = "all" | "current" | "last" | "custom";

const pad = (n: number) => String(n).padStart(2, "0");

// "Today" as the franchisee perceives it — IST calendar date, regardless of
// the browser's timezone. en-CA formats as YYYY-MM-DD.
function istToday(): { y: number; m: number; d: number } {
  const s = new Intl.DateTimeFormat("en-CA", {
    timeZone: "Asia/Kolkata",
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  }).format(new Date());
  const [y, m, d] = s.split("-").map(Number);
  return { y, m, d };
}

// Inclusive IST date range for a preset (backend interprets these as IST).
function presetRange(preset: Preset): { from?: string; to?: string } {
  const { y, m, d } = istToday();
  if (preset === "current") {
    return { from: `${y}-${pad(m)}-01`, to: `${y}-${pad(m)}-${pad(d)}` };
  }
  if (preset === "last") {
    const py = m === 1 ? y - 1 : y;
    const pm = m === 1 ? 12 : m - 1;
    const lastDay = new Date(py, pm, 0).getDate();
    return { from: `${py}-${pad(pm)}-01`, to: `${py}-${pad(pm)}-${pad(lastDay)}` };
  }
  return {};
}

function SummaryCards({ summary }: { summary: SettlementSummary }) {
  return (
    <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
      <Card>
        <CardHeader className="pb-2">
          <CardTitle className="text-sm font-medium text-muted-foreground">
            Total Gross
          </CardTitle>
        </CardHeader>
        <CardContent>
          <p className="text-2xl font-bold">{formatINR(summary.total_gross)}</p>
        </CardContent>
      </Card>

      <Card>
        <CardHeader className="pb-2">
          <CardTitle className="text-sm font-medium text-muted-foreground">
            Total Payout
          </CardTitle>
        </CardHeader>
        <CardContent>
          <p className="text-2xl font-bold text-green-600">
            {formatINR(summary.total_payout)}
          </p>
          <div className="mt-1 flex flex-col gap-0.5 text-xs text-muted-foreground">
            <span>Settled: {formatINR(summary.payout_settled)}</span>
            <span>Pending: {formatINR(summary.payout_pending)}</span>
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardHeader className="pb-2">
          <CardTitle className="text-sm font-medium text-muted-foreground">
            Total TDS
          </CardTitle>
        </CardHeader>
        <CardContent>
          <p className="text-2xl font-bold">{formatINR(summary.total_tds)}</p>
        </CardContent>
      </Card>
    </div>
  );
}

function SettlementsContent() {
  const [currentPage, setCurrentPage] = useState(1);
  const [preset, setPreset] = useState<Preset>("all");
  const [fromDate, setFromDate] = useState("");
  const [toDate, setToDate] = useState("");
  const limit = 20;

  // Any filter change resets to the first page so the view stays coherent.
  useEffect(() => {
    setCurrentPage(1);
  }, [fromDate, toDate]);

  const { data, isLoading, error } = usePortalSettlements({
    page: currentPage,
    limit,
    from_date: fromDate || undefined,
    to_date: toDate || undefined,
  });

  const applyPreset = (p: Preset) => {
    setPreset(p);
    if (p === "custom") return;
    const { from, to } = presetRange(p);
    setFromDate(from ?? "");
    setToDate(to ?? "");
  };

  const onCustomDate = (which: "from" | "to", value: string) => {
    setPreset("custom");
    if (which === "from") setFromDate(value);
    else setToDate(value);
  };

  const summary = data?.summary as SettlementSummary | undefined;
  const totalPages = data ? Math.ceil(data.total / limit) : 0;

  const PRESETS: { key: Preset; label: string }[] = [
    { key: "all", label: "All time" },
    { key: "current", label: "Current month" },
    { key: "last", label: "Last month" },
  ];

  return (
    <div className="space-y-6">
      <h1 className="text-3xl font-bold">Settlements</h1>

      <div className="flex flex-wrap items-center gap-2">
        {PRESETS.map((p) => (
          <Button
            key={p.key}
            variant={preset === p.key ? "default" : "outline"}
            size="sm"
            onClick={() => applyPreset(p.key)}
          >
            {p.label}
          </Button>
        ))}
        <div className="flex items-center gap-2 sm:ml-2">
          <input
            type="date"
            aria-label="From date"
            value={fromDate}
            onChange={(e) => onCustomDate("from", e.target.value)}
            className="h-9 rounded-md border border-input bg-background px-3 text-sm"
          />
          <span className="text-muted-foreground text-sm">to</span>
          <input
            type="date"
            aria-label="To date"
            value={toDate}
            onChange={(e) => onCustomDate("to", e.target.value)}
            className="h-9 rounded-md border border-input bg-background px-3 text-sm"
          />
        </div>
      </div>

      {summary && <SummaryCards summary={summary} />}

      {summary && summary.failed_count > 0 && (
        <div className="flex items-center gap-2 rounded-md border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-800">
          <AlertTriangle className="h-4 w-4 shrink-0" />
          {summary.failed_count} payout{summary.failed_count > 1 ? "s" : ""} failed
          and need attention — these are included in Pending above.
        </div>
      )}

      {isLoading ? (
        <div className="flex items-center justify-center min-h-[300px]">
          <div className="text-center">
            <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-primary mx-auto" />
            <p className="text-muted-foreground mt-2">Loading settlements...</p>
          </div>
        </div>
      ) : error ? (
        <div className="flex items-center justify-center min-h-[300px]">
          <div className="text-center">
            <h2 className="text-2xl font-bold text-gray-900 mb-2">
              Failed to load settlements
            </h2>
            <p className="text-gray-600">Please try refreshing the page.</p>
          </div>
        </div>
      ) : (
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <Banknote className="h-5 w-5" />
              Settlement History {data && `(${data.total})`}
            </CardTitle>
          </CardHeader>
          <CardContent>
            {!data?.data.length ? (
              <div className="text-center py-8 text-muted-foreground">
                No settlements found for this period.
              </div>
            ) : (
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Date</TableHead>
                    <TableHead>Payment Method</TableHead>
                    <TableHead className="text-right">Gross</TableHead>
                    <TableHead className="text-right">Payout</TableHead>
                    <TableHead>Status</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {(data.data as SettlementEntry[]).map((entry) => (
                    <TableRow key={entry.id}>
                      <TableCell className="text-sm">
                        {new Date(entry.created_at).toLocaleDateString()}
                      </TableCell>
                      <TableCell className="text-sm">
                        {entry.payment_method || "-"}
                      </TableCell>
                      <TableCell className="text-right font-medium">
                        {formatINR(entry.gross_amount)}
                      </TableCell>
                      <TableCell className="text-right font-medium text-green-600">
                        {formatINR(entry.franchisee_payout)}
                      </TableCell>
                      <TableCell>
                        <SettlementStatusBadge status={entry.settlement_status} />
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            )}

            {totalPages > 1 && (
              <div className="flex justify-between items-center mt-4">
                <p className="text-sm text-muted-foreground">
                  Page {currentPage} of {totalPages}
                </p>
                <div className="flex gap-2">
                  <Button
                    variant="outline"
                    size="sm"
                    onClick={() => setCurrentPage((p) => Math.max(1, p - 1))}
                    disabled={currentPage === 1}
                  >
                    Previous
                  </Button>
                  <Button
                    variant="outline"
                    size="sm"
                    onClick={() =>
                      setCurrentPage((p) => Math.min(totalPages, p + 1))
                    }
                    disabled={currentPage === totalPages}
                  >
                    Next
                  </Button>
                </div>
              </div>
            )}
          </CardContent>
        </Card>
      )}
    </div>
  );
}

export default function SettlementsPage() {
  return (
    <FranchiseeOnly
      fallback={
        <div className="flex items-center justify-center min-h-[400px]">
          <div className="text-center">
            <h2 className="text-2xl font-bold text-gray-900 mb-2">
              Access Denied
            </h2>
            <p className="text-gray-600 mb-4">
              You need franchisee privileges to access this page.
            </p>
            <Link
              href="/dashboard"
              className="text-blue-600 hover:text-blue-800"
            >
              Go to Dashboard
            </Link>
          </div>
        </div>
      }
    >
      <SettlementsContent />
    </FranchiseeOnly>
  );
}
