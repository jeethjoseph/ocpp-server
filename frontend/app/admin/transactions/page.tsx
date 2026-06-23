"use client";

import { useState } from "react";
import { AdminOnly } from "@/components/RoleWrapper";
import { Card } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import Link from "next/link";
import { useAdminTransactions } from "@/lib/queries/transactions";

const SESSION_STATUSES = [
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
] as const;

const PAYMENT_STATUSES = [
  "PAID",
  "CHARGING",
  "COMPLETED",
  "REFUNDED",
  "REFUND_FAILED",
  "EXPIRED",
  "FAILED",
] as const;

const FUNDING_SOURCES = ["QR", "WALLET", "NONE"] as const;

const ALL = "__ALL__";

function sessionStatusVariant(
  status: string
): "default" | "secondary" | "destructive" | "outline" {
  switch (status) {
    case "RUNNING":
    case "STARTED":
    case "COMPLETED":
      return "default";
    case "SUSPENDED":
    case "PENDING_START":
    case "PENDING_STOP":
    case "STOPPED":
      return "secondary";
    case "FAILED":
    case "BILLING_FAILED":
    case "CANCELLED":
      return "destructive";
    default:
      return "outline";
  }
}

function paymentStatusVariant(
  status: string
): "default" | "secondary" | "destructive" | "outline" {
  switch (status) {
    case "PAID":
    case "COMPLETED":
      return "default";
    case "CHARGING":
    case "REFUNDED":
      return "secondary";
    case "FAILED":
    case "REFUND_FAILED":
    case "EXPIRED":
      return "destructive";
    default:
      return "outline";
  }
}

function fundingSourceVariant(
  source: string
): "default" | "secondary" | "outline" {
  switch (source) {
    case "QR":
      return "default";
    case "WALLET":
      return "secondary";
    default:
      return "outline";
  }
}

function SummaryCards({
  summary,
}: {
  summary?: {
    total_energy_consumed: number | string; // Decimal — serialized as a string by the API
    active_sessions: number;
    suspended_sessions: number;
    completed_sessions: number;
  };
}) {
  return (
    <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
      <Card className="p-4">
        <h4 className="text-sm font-medium text-gray-600">Active Sessions</h4>
        <p className="text-2xl font-bold text-green-600">
          {summary?.active_sessions ?? 0}
        </p>
      </Card>
      <Card className="p-4">
        <h4 className="text-sm font-medium text-gray-600">Suspended</h4>
        <p className="text-2xl font-bold text-orange-600">
          {summary?.suspended_sessions ?? 0}
        </p>
      </Card>
      <Card className="p-4">
        <h4 className="text-sm font-medium text-gray-600">Completed</h4>
        <p className="text-2xl font-bold">{summary?.completed_sessions ?? 0}</p>
      </Card>
      <Card className="p-4">
        <h4 className="text-sm font-medium text-gray-600">Total Energy</h4>
        <p className="text-2xl font-bold">
          {Number(summary?.total_energy_consumed ?? 0).toFixed(2)} kWh
        </p>
      </Card>
    </div>
  );
}

function TransactionsConsole() {
  const [currentPage, setCurrentPage] = useState(1);
  const [statusFilter, setStatusFilter] = useState<string | undefined>(
    undefined
  );
  const [paymentStatusFilter, setPaymentStatusFilter] = useState<
    string | undefined
  >(undefined);
  const [fundingSources, setFundingSources] = useState<string[]>([]);
  const [startDate, setStartDate] = useState("");
  const [endDate, setEndDate] = useState("");

  const limit = 20;

  const { data, isLoading, error } = useAdminTransactions({
    page: currentPage,
    limit,
    status: statusFilter,
    payment_status: paymentStatusFilter,
    funding_source: fundingSources.length ? fundingSources : undefined,
    start_date: startDate || undefined,
    end_date: endDate || undefined,
  });

  const toggleFundingSource = (source: string) => {
    setCurrentPage(1);
    setFundingSources((prev) =>
      prev.includes(source)
        ? prev.filter((s) => s !== source)
        : [...prev, source]
    );
  };

  const rows = data?.data || [];
  const total = data?.total || 0;
  const totalPages = Math.max(1, Math.ceil(total / limit));

  return (
    <div className="space-y-4">
      <SummaryCards summary={data?.summary} />

      {/* Filters */}
      <div className="flex flex-col gap-4">
        <div className="flex flex-wrap gap-4 items-end">
          <div className="space-y-1">
            <label className="text-xs font-medium text-gray-600">
              Session Status
            </label>
            <Select
              value={statusFilter ?? ALL}
              onValueChange={(value) => {
                setCurrentPage(1);
                setStatusFilter(value === ALL ? undefined : value);
              }}
            >
              <SelectTrigger className="w-48">
                <SelectValue placeholder="All" />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value={ALL}>All</SelectItem>
                {SESSION_STATUSES.map((s) => (
                  <SelectItem key={s} value={s}>
                    {s}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>

          <div className="space-y-1">
            <label className="text-xs font-medium text-gray-600">
              Payment Status
            </label>
            <Select
              value={paymentStatusFilter ?? ALL}
              onValueChange={(value) => {
                setCurrentPage(1);
                setPaymentStatusFilter(value === ALL ? undefined : value);
              }}
            >
              <SelectTrigger className="w-48">
                <SelectValue placeholder="All" />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value={ALL}>All</SelectItem>
                {PAYMENT_STATUSES.map((s) => (
                  <SelectItem key={s} value={s}>
                    {s}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>

          <div className="space-y-1">
            <label className="text-xs font-medium text-gray-600">
              Start Date
            </label>
            <Input
              type="date"
              value={startDate}
              onChange={(e) => {
                setCurrentPage(1);
                setStartDate(e.target.value);
              }}
              className="w-44"
            />
          </div>

          <div className="space-y-1">
            <label className="text-xs font-medium text-gray-600">
              End Date
            </label>
            <Input
              type="date"
              value={endDate}
              onChange={(e) => {
                setCurrentPage(1);
                setEndDate(e.target.value);
              }}
              className="w-44"
            />
          </div>
        </div>

        <div className="space-y-1">
          <label className="text-xs font-medium text-gray-600">
            Funding Source
          </label>
          <div className="flex gap-2">
            {FUNDING_SOURCES.map((source) => (
              <Button
                key={source}
                variant={
                  fundingSources.includes(source) ? "default" : "outline"
                }
                size="sm"
                onClick={() => toggleFundingSource(source)}
              >
                {source}
              </Button>
            ))}
          </div>
        </div>
      </div>

      {/* Table */}
      {isLoading ? (
        <div className="flex items-center justify-center py-8">
          <div className="text-center">
            <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-primary mx-auto"></div>
            <p className="text-muted-foreground mt-2">Loading sessions...</p>
          </div>
        </div>
      ) : error ? (
        <div className="text-center py-8">
          <p className="text-red-600">Failed to load charging sessions</p>
        </div>
      ) : rows.length === 0 ? (
        <Card className="p-6 text-center">
          <p className="text-gray-600">
            No charging sessions match the current filters.
          </p>
        </Card>
      ) : (
        <Card>
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>ID</TableHead>
                <TableHead>User</TableHead>
                <TableHead>Charger</TableHead>
                <TableHead>Funding Source</TableHead>
                <TableHead>Session Status</TableHead>
                <TableHead>Payment Status</TableHead>
                <TableHead>Energy</TableHead>
                <TableHead>Start Time</TableHead>
                <TableHead></TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {rows.map((tx) => {
                const startTime = new Date(tx.start_time);
                return (
                  <TableRow key={tx.id}>
                    <TableCell className="font-mono text-xs text-muted-foreground">
                      #{tx.id}
                    </TableCell>
                    <TableCell>
                      <Link
                        href={`/admin/users/${tx.user_id}`}
                        className="text-blue-600 hover:text-blue-800"
                      >
                        #{tx.user_id}
                      </Link>
                    </TableCell>
                    <TableCell>
                      <Link
                        href={`/admin/chargers/${tx.charger_id}`}
                        className="text-blue-600 hover:text-blue-800"
                      >
                        #{tx.charger_id}
                      </Link>
                    </TableCell>
                    <TableCell>
                      <Badge variant={fundingSourceVariant(tx.funding_source)}>
                        {tx.funding_source}
                      </Badge>
                    </TableCell>
                    <TableCell>
                      <Badge
                        variant={sessionStatusVariant(tx.transaction_status)}
                      >
                        {tx.transaction_status}
                      </Badge>
                    </TableCell>
                    <TableCell>
                      {tx.payment_status ? (
                        <Badge
                          variant={paymentStatusVariant(tx.payment_status)}
                        >
                          {tx.payment_status}
                        </Badge>
                      ) : (
                        <span className="text-gray-400">—</span>
                      )}
                      {(tx.refund_speed != null || tx.refund_amount != null) && (
                        <div className="mt-1 text-xs text-gray-400">
                          {tx.refund_speed === "instant"
                            ? "Instant"
                            : tx.refund_speed === "normal"
                            ? "Normal"
                            : "—"}
                          {tx.refund_amount != null
                            ? ` · ₹${Number(tx.refund_amount).toFixed(2)}`
                            : ""}
                        </div>
                      )}
                    </TableCell>
                    <TableCell>
                      {tx.energy_consumed_kwh != null ? (
                        <span>{Number(tx.energy_consumed_kwh).toFixed(2)} kWh</span>
                      ) : (
                        <span className="text-gray-400">—</span>
                      )}
                    </TableCell>
                    <TableCell>
                      <div>
                        <div>{startTime.toLocaleDateString()}</div>
                        <div className="text-sm text-gray-600">
                          {startTime.toLocaleTimeString()}
                        </div>
                      </div>
                    </TableCell>
                    <TableCell>
                      <Link
                        href={`/admin/transactions/${tx.id}`}
                        className="text-blue-600 hover:text-blue-800 font-medium"
                      >
                        ▸
                      </Link>
                    </TableCell>
                  </TableRow>
                );
              })}
            </TableBody>
          </Table>
        </Card>
      )}

      {/* Pagination */}
      {totalPages > 1 && (
        <div className="flex items-center justify-between">
          <div className="text-sm text-gray-600">
            Showing {rows.length} of {total} sessions
          </div>
          <div className="flex items-center gap-2">
            <Button
              variant="outline"
              size="sm"
              onClick={() => setCurrentPage((prev) => Math.max(prev - 1, 1))}
              disabled={currentPage === 1}
            >
              Previous
            </Button>
            <span className="text-sm px-3 py-1 bg-gray-100 rounded">
              {currentPage} of {totalPages}
            </span>
            <Button
              variant="outline"
              size="sm"
              onClick={() =>
                setCurrentPage((prev) => Math.min(prev + 1, totalPages))
              }
              disabled={currentPage === totalPages}
            >
              Next
            </Button>
          </div>
        </div>
      )}
    </div>
  );
}

export default function AdminTransactionsPage() {
  return (
    <AdminOnly
      fallback={
        <div className="flex items-center justify-center min-h-[400px]">
          <div className="text-center">
            <h2 className="text-2xl font-bold text-gray-900 mb-2">
              Access Denied
            </h2>
            <p className="text-gray-600 mb-4">
              You need administrator privileges to view charging sessions.
            </p>
            <Link href="/dashboard" className="text-blue-600 hover:text-blue-800">
              Go to Dashboard →
            </Link>
          </div>
        </div>
      }
    >
      <div className="space-y-6">
        <div>
          <h1 className="text-3xl font-bold">Transactions Console</h1>
          <p className="text-gray-600 mt-1">
            All charging sessions across every funding source and status. A
            triage view, not a money ledger.
          </p>
        </div>

        <TransactionsConsole />
      </div>
    </AdminOnly>
  );
}
