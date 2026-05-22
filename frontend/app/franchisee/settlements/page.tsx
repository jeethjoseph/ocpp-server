"use client";

import { useState } from "react";
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
import { Banknote, MinusCircle } from "lucide-react";
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
  commission_percent: string | number;
  settlement_status: string;
}

function SettlementsContent() {
  const [currentPage, setCurrentPage] = useState(1);
  const limit = 20;
  const { data, isLoading, error } = usePortalSettlements({
    page: currentPage,
    limit,
  });

  if (isLoading) {
    return (
      <div className="flex items-center justify-center min-h-[400px]">
        <div className="text-center">
          <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-primary mx-auto" />
          <p className="text-muted-foreground mt-2">Loading settlements...</p>
        </div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="flex items-center justify-center min-h-[400px]">
        <div className="text-center">
          <h2 className="text-2xl font-bold text-gray-900 mb-2">
            Failed to load settlements
          </h2>
          <p className="text-gray-600">Please try refreshing the page.</p>
        </div>
      </div>
    );
  }

  const totalPages = data ? Math.ceil(data.total / limit) : 0;

  return (
    <div className="space-y-6">
      <h1 className="text-3xl font-bold">Settlements</h1>

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
              No settlements found.
            </div>
          ) : (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Date</TableHead>
                  <TableHead>Payment Method</TableHead>
                  <TableHead className="text-right">Gross</TableHead>
                  <TableHead className="text-right">Payout</TableHead>
                  <TableHead className="text-right">Commission%</TableHead>
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
                    <TableCell className="text-right">
                      {entry.commission_percent}%
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
