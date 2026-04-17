"use client";

import { useState } from "react";
import Link from "next/link";
import { Receipt } from "lucide-react";

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

const PAGE_SIZE = 20;

function statusVariant(
  status: string | null
): "default" | "secondary" | "destructive" | "outline" {
  if (!status) return "outline";
  const s = status.toLowerCase();
  if (s === "completed") return "default";
  if (s === "running" || s === "started" || s === "pending_start") return "secondary";
  if (s === "faulted" || s === "failed") return "destructive";
  return "outline";
}

function formatDate(iso: string | null): string {
  if (!iso) return "--";
  return new Date(iso).toLocaleString();
}

function formatCurrency(value: string | null): string {
  if (!value) return "--";
  return `Rs. ${parseFloat(value).toFixed(2)}`;
}

export default function FranchiseeTransactionsPage() {
  const [currentPage, setCurrentPage] = useState(1);

  const { data, isLoading, error } = usePortalTransactions({
    page: currentPage,
    limit: PAGE_SIZE,
  });

  const transactions = data?.data || [];
  const total = data?.total || 0;
  const totalPages = Math.max(1, Math.ceil(total / PAGE_SIZE));

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
      <div className="space-y-6">
        <div>
          <h1 className="text-3xl font-bold">Transactions</h1>
          <p className="text-muted-foreground">
            Charging sessions across your stations
          </p>
        </div>

        {isLoading ? (
          <div className="flex items-center justify-center py-8">
            <div className="text-center">
              <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-primary mx-auto" />
              <p className="text-muted-foreground mt-2">
                Loading transactions...
              </p>
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
                  Transactions
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
                            <TableCell>
                              {txn.charger_name || "--"}
                            </TableCell>
                            <TableCell>
                              {txn.energy_consumed_kwh != null
                                ? txn.energy_consumed_kwh.toFixed(3)
                                : "--"}
                            </TableCell>
                            <TableCell>
                              {formatCurrency(txn.total_billed)}
                            </TableCell>
                            <TableCell>
                              <Badge
                                variant={statusVariant(txn.transaction_status)}
                              >
                                {txn.transaction_status || "Unknown"}
                              </Badge>
                            </TableCell>
                            <TableCell>
                              {formatDate(txn.start_time)}
                            </TableCell>
                          </TableRow>
                        )
                      )}
                    </TableBody>
                  </Table>
                ) : (
                  <p className="text-center text-muted-foreground py-4">
                    No transactions found
                  </p>
                )}
              </CardContent>
            </Card>

            {totalPages > 1 && (
              <div className="flex justify-center items-center gap-2">
                <Button
                  variant="outline"
                  size="sm"
                  onClick={() =>
                    setCurrentPage((prev) => Math.max(1, prev - 1))
                  }
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
                    setCurrentPage((prev) =>
                      Math.min(totalPages, prev + 1)
                    )
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
    </FranchiseeOnly>
  );
}
