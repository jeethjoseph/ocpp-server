"use client";

import { useState } from "react";
import Link from "next/link";
import { AlertTriangle, ChevronLeft, ChevronRight } from "lucide-react";

import { AdminOnly } from "@/components/RoleWrapper";
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
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";

import { useAdminStuckSettlements } from "@/lib/queries/admin-settlements";
import { SettlementTerminalActions } from "@/components/SettlementTerminalActions";
import { formatINR } from "@/lib/utils";

const STATUS_COLORS: Record<string, string> = {
  PENDING: "bg-yellow-100 text-yellow-800",
  TRANSFER_INITIATED: "bg-blue-100 text-blue-800",
  FAILED: "bg-red-100 text-red-800",
  ON_HOLD: "bg-orange-100 text-orange-800",
};

const STATUS_OPTIONS = ["", "PENDING", "TRANSFER_INITIATED", "FAILED", "ON_HOLD"];

export default function AdminStuckSettlementsPage() {
  const [page, setPage] = useState(1);
  const [olderThanHours, setOlderThanHours] = useState(24);
  const [status, setStatus] = useState<string>("");

  const { data, isLoading, error } = useAdminStuckSettlements({
    page,
    limit: 20,
    older_than_hours: olderThanHours,
    status: status || undefined,
  });

  const totalPages = data ? Math.max(1, Math.ceil(data.total / data.limit)) : 1;

  return (
    <AdminOnly>
      <div className="container mx-auto p-6 space-y-6">
        <div>
          <Link
            href="/admin"
            className="text-sm text-muted-foreground hover:underline inline-flex items-center gap-1"
          >
            <ChevronLeft className="w-3 h-3" /> Admin dashboard
          </Link>
          <h1 className="text-2xl font-bold mt-2 flex items-center gap-2">
            <AlertTriangle className="w-5 h-5 text-amber-600" />
            Stuck Settlements
          </h1>
          <p className="text-sm text-muted-foreground mt-1">
            Settlement ledger entries that have not progressed past a transferable
            state: FAILED or ON_HOLD past retry limit, or PENDING /
            TRANSFER_INITIATED older than the threshold.
          </p>
        </div>

        <Card>
          <CardHeader>
            <CardTitle className="text-base">Filters</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
              <div>
                <label className="text-xs text-muted-foreground">
                  Older than (hours)
                </label>
                <Select
                  value={String(olderThanHours)}
                  onValueChange={(v) => {
                    setOlderThanHours(Number(v));
                    setPage(1);
                  }}
                >
                  <SelectTrigger className="mt-1">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    {[1, 6, 12, 24, 48, 72, 168].map((h) => (
                      <SelectItem key={h} value={String(h)}>
                        {h}h
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
              <div>
                <label className="text-xs text-muted-foreground">Status</label>
                <Select
                  value={status || "ALL"}
                  onValueChange={(v) => {
                    setStatus(v === "ALL" ? "" : v);
                    setPage(1);
                  }}
                >
                  <SelectTrigger className="mt-1">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="ALL">All</SelectItem>
                    {STATUS_OPTIONS.filter((s) => s).map((s) => (
                      <SelectItem key={s} value={s}>
                        {s.replace(/_/g, " ")}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
            </div>
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle className="text-base">
              {isLoading
                ? "Loading…"
                : `${data?.total ?? 0} stuck ${
                    (data?.total ?? 0) === 1 ? "entry" : "entries"
                  }`}
            </CardTitle>
          </CardHeader>
          <CardContent>
            {error && (
              <p className="text-sm text-red-600 py-4">
                Failed to load: {error.message}
              </p>
            )}
            {!error && data && data.data.length === 0 && (
              <p className="text-sm text-muted-foreground py-4 text-center">
                No stuck settlements 🎉
              </p>
            )}
            {!error && data && data.data.length > 0 && (
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>ID</TableHead>
                    <TableHead>Franchisee</TableHead>
                    <TableHead>Status</TableHead>
                    <TableHead className="text-right">Payout</TableHead>
                    <TableHead>Created</TableHead>
                    <TableHead>Retries</TableHead>
                    <TableHead>Reason</TableHead>
                    <TableHead>Actions</TableHead>
                    <TableHead></TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {data.data.map((e) => (
                    <TableRow key={e.id}>
                      <TableCell className="font-mono text-xs text-muted-foreground">
                        #{e.id}
                      </TableCell>
                      <TableCell className="text-sm">
                        <div className="font-medium">
                          {e.franchisee_business_name || `#${e.franchisee_id}`}
                        </div>
                        <div className="text-xs text-muted-foreground">
                          txn #{e.transaction_id ?? "—"}
                        </div>
                      </TableCell>
                      <TableCell>
                        <Badge
                          variant="secondary"
                          className={STATUS_COLORS[e.settlement_status] || ""}
                        >
                          {e.settlement_status.replace(/_/g, " ")}
                        </Badge>
                      </TableCell>
                      <TableCell className="text-right text-sm">
                        {formatINR(e.franchisee_payout)}
                      </TableCell>
                      <TableCell className="text-xs">
                        {new Date(e.created_at).toLocaleString()}
                      </TableCell>
                      <TableCell className="text-xs">{e.retry_count}</TableCell>
                      <TableCell
                        className="text-xs text-red-600 max-w-[200px] truncate"
                        title={e.failure_reason ?? ""}
                      >
                        {e.failure_reason ?? "—"}
                      </TableCell>
                      <TableCell>
                        <SettlementTerminalActions entry={e} />
                      </TableCell>
                      <TableCell>
                        <Link
                          href={`/admin/franchisees/${e.franchisee_id}#settlements`}
                          className="text-xs text-blue-600 hover:underline"
                        >
                          Open
                        </Link>
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            )}

            {totalPages > 1 && (
              <div className="flex justify-between items-center mt-4 text-sm text-muted-foreground">
                <span>
                  Page {page} of {totalPages}
                </span>
                <div className="flex gap-2">
                  <Button
                    variant="outline"
                    size="sm"
                    disabled={page === 1}
                    onClick={() => setPage((p) => p - 1)}
                  >
                    <ChevronLeft className="w-3 h-3 mr-1" />
                    Prev
                  </Button>
                  <Button
                    variant="outline"
                    size="sm"
                    disabled={page === totalPages}
                    onClick={() => setPage((p) => p + 1)}
                  >
                    Next
                    <ChevronRight className="w-3 h-3 ml-1" />
                  </Button>
                </div>
              </div>
            )}
          </CardContent>
        </Card>
      </div>
    </AdminOnly>
  );
}
