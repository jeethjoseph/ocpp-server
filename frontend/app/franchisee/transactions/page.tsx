"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { Receipt, Zap, Banknote, ListChecks } from "lucide-react";

import { FranchiseeOnly } from "@/components/RoleWrapper";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { usePortalTransactions } from "@/lib/queries/franchisee-portal";
import { formatINR } from "@/lib/utils";
import { type DatePreset, presetRange } from "@/lib/date-presets";

const PAGE_SIZE = 20;

// All TransactionStatusEnum values — listed in full so a franchisee can find
// any state (e.g. BILLING_FAILED) rather than a curated subset.
const STATUS_OPTIONS = [
  "STARTED",
  "PENDING_START",
  "RUNNING",
  "SUSPENDED",
  "PENDING_STOP",
  "STOPPED",
  "COMPLETED",
  "CANCELLED",
  "FAILED",
  "BILLING_FAILED",
];

const DATE_PRESETS: { key: DatePreset; label: string }[] = [
  { key: "all", label: "All time" },
  { key: "current", label: "Current month" },
  { key: "last", label: "Last month" },
];

function statusVariant(
  status: string | null
): "default" | "secondary" | "destructive" | "outline" {
  if (!status) return "outline";
  const s = status.toLowerCase();
  if (s === "completed") return "default";
  if (s === "running" || s === "started" || s === "pending_start") return "secondary";
  if (s === "faulted" || s === "failed" || s === "billing_failed") return "destructive";
  return "outline";
}

function formatDate(iso: string | null): string {
  if (!iso) return "--";
  return new Date(iso).toLocaleString();
}

interface TransactionSummary {
  total_energy_kwh: string;
  total_revenue: string;
}

function SummaryCards({
  sessions,
  summary,
}: {
  sessions: number;
  summary: TransactionSummary;
}) {
  return (
    <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
      <Card>
        <CardHeader className="pb-2">
          <CardTitle className="flex items-center gap-2 text-sm font-medium text-muted-foreground">
            <ListChecks className="h-4 w-4" />
            Total Sessions
          </CardTitle>
        </CardHeader>
        <CardContent>
          <p className="text-2xl font-bold">{sessions}</p>
        </CardContent>
      </Card>

      <Card>
        <CardHeader className="pb-2">
          <CardTitle className="flex items-center gap-2 text-sm font-medium text-muted-foreground">
            <Zap className="h-4 w-4" />
            Total Energy
          </CardTitle>
        </CardHeader>
        <CardContent>
          <p className="text-2xl font-bold">
            {summary.total_energy_kwh}{" "}
            <span className="text-base font-normal text-muted-foreground">kWh</span>
          </p>
        </CardContent>
      </Card>

      <Card>
        <CardHeader className="pb-2">
          <CardTitle className="flex items-center gap-2 text-sm font-medium text-muted-foreground">
            <Banknote className="h-4 w-4" />
            Total Revenue
          </CardTitle>
        </CardHeader>
        <CardContent>
          <p className="text-2xl font-bold">{formatINR(summary.total_revenue)}</p>
        </CardContent>
      </Card>
    </div>
  );
}

function TransactionsContent() {
  const [currentPage, setCurrentPage] = useState(1);
  const [preset, setPreset] = useState<DatePreset>("all");
  const [fromDate, setFromDate] = useState("");
  const [toDate, setToDate] = useState("");
  const [status, setStatus] = useState("");

  // Any filter change resets to the first page so the view stays coherent.
  useEffect(() => {
    setCurrentPage(1);
  }, [fromDate, toDate, status]);

  const { data, isLoading, error } = usePortalTransactions({
    page: currentPage,
    limit: PAGE_SIZE,
    status: status || undefined,
    from_date: fromDate || undefined,
    to_date: toDate || undefined,
  });

  const applyPreset = (p: DatePreset) => {
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

  const transactions = data?.data || [];
  const total = data?.total || 0;
  const summary = data?.summary as TransactionSummary | undefined;
  const totalPages = Math.max(1, Math.ceil(total / PAGE_SIZE));

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-3xl font-bold">Transactions</h1>
        <p className="text-muted-foreground">
          Charging sessions across your stations
        </p>
      </div>

      <div className="flex flex-wrap items-center gap-2">
        {DATE_PRESETS.map((p) => (
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
        <select
          aria-label="Status"
          value={status}
          onChange={(e) => setStatus(e.target.value)}
          className="h-9 rounded-md border border-input bg-background px-3 text-sm"
        >
          <option value="">All statuses</option>
          {STATUS_OPTIONS.map((s) => (
            <option key={s} value={s}>
              {s}
            </option>
          ))}
        </select>
      </div>

      {summary && <SummaryCards sessions={total} summary={summary} />}

      {isLoading ? (
        <div className="flex items-center justify-center py-8">
          <div className="text-center">
            <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-primary mx-auto" />
            <p className="text-muted-foreground mt-2">Loading transactions...</p>
          </div>
        </div>
      ) : error ? (
        <div className="text-center py-8">
          <p className="text-destructive">Failed to load transactions</p>
          <p className="text-muted-foreground text-sm mt-1">
            Please try refreshing the page
          </p>
        </div>
      ) : (
        <>
          <Card>
            <CardHeader>
              <CardTitle className="flex items-center gap-2">
                <Receipt className="h-5 w-5" />
                Transactions {total > 0 && `(${total})`}
              </CardTitle>
            </CardHeader>
            <CardContent>
              {transactions.length > 0 ? (
                <Table>
                  <TableHeader>
                    <TableRow>
                      <TableHead>ID</TableHead>
                      <TableHead>Charger</TableHead>
                      <TableHead>Energy (kWh)</TableHead>
                      <TableHead>Total Billed</TableHead>
                      <TableHead>Status</TableHead>
                      <TableHead>Date</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {transactions.map(
                      (txn: {
                        id: number;
                        charger_name: string | null;
                        energy_consumed_kwh: number | null;
                        total_billed: string | null;
                        transaction_status: string | null;
                        start_time: string | null;
                      }) => (
                        <TableRow key={txn.id}>
                          <TableCell className="font-medium">
                            <Link
                              href={`/franchisee/transactions/${txn.id}`}
                              className="text-blue-600 hover:text-blue-800 hover:underline"
                            >
                              #{txn.id}
                            </Link>
                          </TableCell>
                          <TableCell>{txn.charger_name || "--"}</TableCell>
                          <TableCell>
                            {txn.energy_consumed_kwh != null
                              ? txn.energy_consumed_kwh.toFixed(3)
                              : "--"}
                          </TableCell>
                          <TableCell>
                            {txn.total_billed != null
                              ? formatINR(txn.total_billed)
                              : "--"}
                          </TableCell>
                          <TableCell>
                            <Badge variant={statusVariant(txn.transaction_status)}>
                              {txn.transaction_status || "Unknown"}
                            </Badge>
                          </TableCell>
                          <TableCell>{formatDate(txn.start_time)}</TableCell>
                        </TableRow>
                      )
                    )}
                  </TableBody>
                </Table>
              ) : (
                <p className="text-center text-muted-foreground py-4">
                  No transactions found for this period.
                </p>
              )}
            </CardContent>
          </Card>

          {totalPages > 1 && (
            <div className="flex justify-center items-center gap-2">
              <Button
                variant="outline"
                size="sm"
                onClick={() => setCurrentPage((prev) => Math.max(1, prev - 1))}
                disabled={currentPage === 1}
              >
                Previous
              </Button>
              <span className="text-sm text-muted-foreground">
                Page {currentPage} of {totalPages}
              </span>
              <Button
                variant="outline"
                size="sm"
                onClick={() =>
                  setCurrentPage((prev) => Math.min(totalPages, prev + 1))
                }
                disabled={currentPage === totalPages}
              >
                Next
              </Button>
            </div>
          )}
        </>
      )}
    </div>
  );
}

export default function FranchiseeTransactionsPage() {
  return (
    <FranchiseeOnly
      fallback={
        <div className="flex items-center justify-center min-h-[400px]">
          <div className="text-center">
            <h2 className="text-2xl font-bold text-gray-900 mb-2">
              Access Denied
            </h2>
            <p className="text-gray-600">
              You need franchisee privileges to view transactions.
            </p>
          </div>
        </div>
      }
    >
      <TransactionsContent />
    </FranchiseeOnly>
  );
}
