"use client";

import { useParams, useRouter } from "next/navigation";
import { ArrowLeft, Receipt, Activity } from "lucide-react";

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
import { usePortalTransaction } from "@/lib/queries/franchisee-portal";

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

export default function FranchiseeTransactionDetailPage() {
  const params = useParams();
  const router = useRouter();
  const transactionId = Number(params.id);

  const { data, isLoading, error } = usePortalTransaction(transactionId);

  const txn = data?.transaction;
  const meterValues = data?.meter_values || [];

  return (
    <FranchiseeOnly
      fallback={
        <div className="flex items-center justify-center min-h-[400px]">
          <div className="text-center">
            <h2 className="text-2xl font-bold text-gray-900 mb-2">
              Access Denied
            </h2>
            <p className="text-gray-600">
              You need franchisee privileges to view this transaction.
            </p>
          </div>
        </div>
      }
    >
      <div className="space-y-6">
        <Button
          variant="ghost"
          size="sm"
          onClick={() => router.push("/franchisee/transactions")}
        >
          <ArrowLeft className="h-4 w-4 mr-1" />
          Back to Transactions
        </Button>

        {isLoading ? (
          <div className="flex items-center justify-center py-8">
            <div className="text-center">
              <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-primary mx-auto" />
              <p className="text-muted-foreground mt-2">
                Loading transaction...
              </p>
            </div>
          </div>
        ) : error ? (
          <div className="text-center py-8">
            <p className="text-destructive">Failed to load transaction</p>
            <p className="text-muted-foreground text-sm mt-1">
              Please try refreshing the page
            </p>
          </div>
        ) : txn ? (
          <>
            <Card>
              <CardHeader>
                <CardTitle className="flex items-center gap-2">
                  <Receipt className="h-5 w-5" />
                  Transaction #{txn.id}
                  <Badge variant={statusVariant(txn.transaction_status)}>
                    {txn.transaction_status || "Unknown"}
                  </Badge>
                </CardTitle>
              </CardHeader>
              <CardContent>
                <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
                  <div>
                    <p className="text-sm text-muted-foreground">Charger</p>
                    <p className="font-medium">{txn.charger_name || "--"}</p>
                  </div>
                  <div>
                    <p className="text-sm text-muted-foreground">
                      Energy Consumed
                    </p>
                    <p className="font-medium">
                      {txn.energy_consumed_kwh != null
                        ? `${Number(txn.energy_consumed_kwh).toFixed(3)} kWh`
                        : "--"}
                    </p>
                  </div>
                  <div>
                    <p className="text-sm text-muted-foreground">
                      Start Meter
                    </p>
                    <p className="font-medium">
                      {txn.start_meter_kwh != null
                        ? `${txn.start_meter_kwh} kWh`
                        : "--"}
                    </p>
                  </div>
                  <div>
                    <p className="text-sm text-muted-foreground">End Meter</p>
                    <p className="font-medium">
                      {txn.end_meter_kwh != null
                        ? `${txn.end_meter_kwh} kWh`
                        : "--"}
                    </p>
                  </div>
                  <div>
                    <p className="text-sm text-muted-foreground">
                      Energy Charge
                    </p>
                    <p className="font-medium">
                      {formatCurrency(txn.energy_charge)}
                    </p>
                  </div>
                  <div>
                    <p className="text-sm text-muted-foreground">GST</p>
                    <p className="font-medium">
                      {formatCurrency(txn.gst_amount)}
                    </p>
                  </div>
                  <div>
                    <p className="text-sm text-muted-foreground">
                      Total Billed
                    </p>
                    <p className="font-medium text-lg">
                      {formatCurrency(txn.total_billed)}
                    </p>
                  </div>
                  <div>
                    <p className="text-sm text-muted-foreground">Start Time</p>
                    <p className="font-medium">
                      {formatDate(txn.start_time)}
                    </p>
                  </div>
                  <div>
                    <p className="text-sm text-muted-foreground">End Time</p>
                    <p className="font-medium">{formatDate(txn.end_time)}</p>
                  </div>
                  {txn.stop_reason && (
                    <div>
                      <p className="text-sm text-muted-foreground">
                        Stop Reason
                      </p>
                      <p className="font-medium">{txn.stop_reason}</p>
                    </div>
                  )}
                </div>
              </CardContent>
            </Card>

            <Card>
              <CardHeader>
                <CardTitle className="flex items-center gap-2">
                  <Activity className="h-5 w-5" />
                  Meter Values ({meterValues.length})
                </CardTitle>
              </CardHeader>
              <CardContent>
                {meterValues.length > 0 ? (
                  <Table>
                    <TableHeader>
                      <TableRow>
                        <TableHead>Reading (kWh)</TableHead>
                        <TableHead>Current (A)</TableHead>
                        <TableHead>Voltage (V)</TableHead>
                        <TableHead>Power (kW)</TableHead>
                        <TableHead>Time</TableHead>
                      </TableRow>
                    </TableHeader>
                    <TableBody>
                      {meterValues.map(
                        (
                          mv: {
                            reading_kwh: number | null;
                            current: number | null;
                            voltage: number | null;
                            power_kw: number | null;
                            created_at: string;
                          },
                          index: number
                        ) => (
                          <TableRow key={index}>
                            <TableCell>
                              {mv.reading_kwh != null
                                ? Number(mv.reading_kwh).toFixed(3)
                                : "--"}
                            </TableCell>
                            <TableCell>
                              {mv.current != null
                                ? mv.current.toFixed(2)
                                : "--"}
                            </TableCell>
                            <TableCell>
                              {mv.voltage != null
                                ? mv.voltage.toFixed(1)
                                : "--"}
                            </TableCell>
                            <TableCell>
                              {mv.power_kw != null
                                ? mv.power_kw.toFixed(2)
                                : "--"}
                            </TableCell>
                            <TableCell>
                              {formatDate(mv.created_at)}
                            </TableCell>
                          </TableRow>
                        )
                      )}
                    </TableBody>
                  </Table>
                ) : (
                  <p className="text-center text-muted-foreground py-4">
                    No meter values recorded
                  </p>
                )}
              </CardContent>
            </Card>
          </>
        ) : null}
      </div>
    </FranchiseeOnly>
  );
}
