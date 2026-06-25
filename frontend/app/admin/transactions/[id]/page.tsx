"use client";

import { useParams } from "next/navigation";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { CreditCard } from "lucide-react";
import { AdminOnly } from "@/components/RoleWrapper";
import Link from "next/link";
import { useAdminTransaction } from "@/lib/queries/transactions";

export default function AdminTransactionDetailPage() {
  const params = useParams();
  const transactionId = parseInt(params.id as string);

  const {
    data: transactionData,
    isLoading,
    error,
  } = useAdminTransaction(transactionId);

  const transaction = transactionData?.transaction;

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
          <Link
            href="/admin/transactions"
            className="text-blue-600 hover:text-blue-800 text-sm mb-2 inline-block"
          >
            ← Back to Transactions Console
          </Link>
          <h1 className="text-3xl font-bold">
            Charging Session #{transactionId}
          </h1>
        </div>

        {isLoading ? (
          <div className="flex items-center justify-center py-8">
            <div className="text-center">
              <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-primary mx-auto"></div>
              <p className="text-muted-foreground mt-2">
                Loading session details...
              </p>
            </div>
          </div>
        ) : error || !transaction ? (
          <div className="text-center py-8">
            <p className="text-destructive">Failed to load session details</p>
          </div>
        ) : (
          <>
            {/* Session Overview */}
            <Card>
              <CardHeader>
                <CardTitle>Session Details</CardTitle>
              </CardHeader>
              <CardContent>
                <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
                  <div>
                    <p className="text-sm font-medium">Transaction ID</p>
                    <p className="text-2xl font-bold flex items-center gap-2">
                      <span>{transaction.id}</span>
                      {transactionData?.funding_source === "QR" && (
                        <Badge variant="secondary" className="text-xs">
                          QR
                        </Badge>
                      )}
                    </p>
                  </div>
                  <div>
                    <p className="text-sm font-medium">Session Status</p>
                    <Badge>{transaction.transaction_status}</Badge>
                  </div>
                  <div>
                    <p className="text-sm font-medium">Started</p>
                    <p className="text-sm">
                      {transaction.start_time
                        ? new Date(transaction.start_time).toLocaleString()
                        : "—"}
                    </p>
                  </div>
                  <div>
                    <p className="text-sm font-medium">Ended</p>
                    <p className="text-sm">
                      {transaction.end_time
                        ? new Date(transaction.end_time).toLocaleString()
                        : "—"}
                    </p>
                  </div>
                  <div>
                    <p className="text-sm font-medium">Energy Consumed</p>
                    <p className="text-2xl font-bold">
                      {transactionData?.live_energy_kwh != null
                        ? `${Number(transactionData.live_energy_kwh).toFixed(2)} kWh`
                        : transaction.energy_consumed_kwh != null
                        ? `${Number(transaction.energy_consumed_kwh).toFixed(2)} kWh`
                        : "—"}
                    </p>
                  </div>
                  <div>
                    <p className="text-sm font-medium">Funding Source</p>
                    <p className="text-sm">
                      {transactionData?.funding_source ?? "—"}
                    </p>
                  </div>
                  <div>
                    <p className="text-sm font-medium">Payment Status</p>
                    <p className="text-sm">
                      {transactionData?.payment_status ?? "—"}
                    </p>
                  </div>
                  <div>
                    <p className="text-sm font-medium">Settlement Status</p>
                    <p className="text-sm">
                      {transactionData?.settlement_status ?? "—"}
                    </p>
                  </div>
                  {(transactionData?.refund_amount != null ||
                    transactionData?.refund_speed != null) && (
                    <>
                      <div>
                        <p className="text-sm font-medium">Refund Amount</p>
                        <p className="text-sm">
                          {transactionData?.refund_amount != null
                            ? `₹${Number(transactionData.refund_amount).toFixed(2)}`
                            : "—"}
                        </p>
                      </div>
                      <div>
                        <p className="text-sm font-medium">Refund Speed</p>
                        <p className="text-sm">
                          {transactionData?.refund_speed === "instant"
                            ? "Instant"
                            : transactionData?.refund_speed === "normal"
                            ? "Normal"
                            : "—"}
                        </p>
                      </div>
                    </>
                  )}
                </div>
              </CardContent>
            </Card>

            {/* Revenue Breakdown — read-only per-session money tally */}
            {transactionData?.revenue && (
              <Card>
                <CardHeader>
                  <CardTitle>Revenue Breakdown</CardTitle>
                </CardHeader>
                <CardContent>
                  {(() => {
                    const r = transactionData.revenue;
                    const money = (v?: number | null) =>
                      v != null ? `₹${Number(v).toFixed(2)}` : "—";
                    const rows: { label: string; value: string }[] = [
                      { label: "Paid Amount", value: money(r.paid_amount) },
                      {
                        label: "Energy Consumed",
                        value:
                          r.energy_consumed_kwh != null
                            ? `${Number(r.energy_consumed_kwh).toFixed(2)} kWh`
                            : "—",
                      },
                      { label: "Energy Amount", value: money(r.energy_amount) },
                      {
                        label: `GST${
                          r.gst_rate_percent != null
                            ? ` (${Number(r.gst_rate_percent).toFixed(0)}%)`
                            : ""
                        }`,
                        value: money(r.gst_amount),
                      },
                      { label: "Total Billed", value: money(r.total_billed) },
                      { label: "Invoice Number", value: r.invoice_number ?? "—" },
                      { label: "Razorpay Fee", value: money(r.razorpay_fee) },
                      { label: "Refund", value: money(r.refund_amount) },
                      {
                        label: "Settlement Amount",
                        value: money(r.settlement_amount),
                      },
                      { label: "TDS", value: money(r.tds_amount) },
                    ];
                    return (
                      <div className="grid grid-cols-2 md:grid-cols-3 gap-4">
                        {rows.map((row) => (
                          <div key={row.label}>
                            <p className="text-sm font-medium text-muted-foreground">
                              {row.label}
                            </p>
                            <p className="text-sm">{row.value}</p>
                          </div>
                        ))}
                      </div>
                    );
                  })()}
                </CardContent>
              </Card>
            )}

            {/* User & Charger */}
            <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
              <Card>
                <CardHeader>
                  <CardTitle>User</CardTitle>
                </CardHeader>
                <CardContent className="space-y-2">
                  <div className="flex justify-between">
                    <span className="text-sm font-medium">ID</span>
                    <Link
                      href={`/admin/users/${transactionData?.user.id}`}
                      className="text-blue-600 hover:text-blue-800 text-sm"
                    >
                      #{transactionData?.user.id}
                    </Link>
                  </div>
                  {transactionData?.user.full_name && (
                    <div className="flex justify-between">
                      <span className="text-sm font-medium">Name</span>
                      <span className="text-sm">
                        {transactionData.user.full_name}
                      </span>
                    </div>
                  )}
                  {transactionData?.user.email && (
                    <div className="flex justify-between">
                      <span className="text-sm font-medium">Email</span>
                      <span className="text-sm">
                        {transactionData.user.email}
                      </span>
                    </div>
                  )}
                  {transactionData?.customer_vpa && (
                    <div className="flex justify-between">
                      <span className="text-sm font-medium">UPI ID</span>
                      <span className="text-sm">
                        {transactionData.customer_vpa}
                      </span>
                    </div>
                  )}
                  {transactionData?.user.phone_number && (
                    <div className="flex justify-between">
                      <span className="text-sm font-medium">Phone</span>
                      <span className="text-sm">
                        {transactionData.user.phone_number}
                      </span>
                    </div>
                  )}
                </CardContent>
              </Card>

              <Card>
                <CardHeader>
                  <CardTitle>Charger</CardTitle>
                </CardHeader>
                <CardContent className="space-y-2">
                  <div className="flex justify-between">
                    <span className="text-sm font-medium">ID</span>
                    <Link
                      href={`/admin/chargers/${transactionData?.charger.id}`}
                      className="text-blue-600 hover:text-blue-800 text-sm"
                    >
                      #{transactionData?.charger.id}
                    </Link>
                  </div>
                  <div className="flex justify-between">
                    <span className="text-sm font-medium">Name</span>
                    <span className="text-sm">
                      {transactionData?.charger.name}
                    </span>
                  </div>
                  <div className="flex justify-between">
                    <span className="text-sm font-medium">String ID</span>
                    <span className="text-sm font-mono">
                      {transactionData?.charger.charge_point_string_id}
                    </span>
                  </div>
                </CardContent>
              </Card>
            </div>

            {/* Billing Information */}
            {transactionData?.wallet_transactions &&
              transactionData.wallet_transactions.length > 0 && (
                <Card>
                  <CardHeader>
                    <CardTitle className="flex items-center gap-2">
                      <CreditCard className="h-5 w-5" />
                      Billing Information
                    </CardTitle>
                  </CardHeader>
                  <CardContent>
                    <div className="space-y-3">
                      {transactionData.wallet_transactions.map((walletTx) => (
                        <div
                          key={walletTx.id}
                          className="flex justify-between items-start p-3 bg-gray-50 dark:bg-gray-800 rounded-lg"
                        >
                          <div className="flex-1">
                            <p className="font-medium">
                              {walletTx.type === "CHARGE_DEDUCT"
                                ? "Charging Bill"
                                : walletTx.type}
                            </p>
                            {walletTx.description && (
                              <p className="text-sm text-muted-foreground mt-1">
                                {walletTx.description}
                              </p>
                            )}
                            <p className="text-xs text-muted-foreground mt-1">
                              {new Date(walletTx.created_at).toLocaleString()}
                            </p>
                          </div>
                          <div className="text-right ml-4">
                            <p
                              className={`text-lg font-bold ${
                                walletTx.type === "CHARGE_DEDUCT"
                                  ? "text-red-600"
                                  : "text-green-600"
                              }`}
                            >
                              {walletTx.type === "CHARGE_DEDUCT" ? "-" : "+"}₹
                              {Math.abs(walletTx.amount).toFixed(2)}
                            </p>
                            <p className="text-xs text-muted-foreground">
                              {walletTx.type === "CHARGE_DEDUCT"
                                ? "Deducted"
                                : "Added"}
                            </p>
                          </div>
                        </div>
                      ))}
                    </div>
                  </CardContent>
                </Card>
              )}
          </>
        )}
      </div>
    </AdminOnly>
  );
}
