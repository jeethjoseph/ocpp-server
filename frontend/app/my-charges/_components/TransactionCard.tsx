"use client";

import { Card, CardContent } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import {
  Zap,
  Clock,
  IndianRupee,
  AlertCircle,
  Download,
} from "lucide-react";
import { QRTransactionItem } from "@/lib/api-services";
import { viewPublicInvoicePDF } from "@/lib/queries/public-qr-transactions";
import { RefundLifecycle } from "./RefundLifecycle";

function getStatusBadgeClass(status: string) {
  switch (status) {
    case "COMPLETED":
      return "bg-green-100 text-green-800 dark:bg-green-900/20 dark:text-green-400";
    case "CHARGING":
      return "bg-blue-100 text-blue-800 dark:bg-blue-900/20 dark:text-blue-400";
    case "PAID":
      return "bg-amber-100 text-amber-800 dark:bg-amber-900/20 dark:text-amber-400";
    case "REFUNDED":
      return "bg-purple-100 text-purple-800 dark:bg-purple-900/20 dark:text-purple-400";
    case "FAILED":
    case "REFUND_FAILED":
      return "bg-red-100 text-red-800 dark:bg-red-900/20 dark:text-red-400";
    case "EXPIRED":
      return "bg-gray-100 text-gray-800 dark:bg-gray-900/20 dark:text-gray-400";
    default:
      return "bg-muted text-muted-foreground";
  }
}

function formatDuration(minutes: number): string {
  if (minutes < 60) return `${Math.round(minutes)} min`;
  const hours = Math.floor(minutes / 60);
  const mins = Math.round(minutes % 60);
  return mins > 0 ? `${hours}h ${mins}m` : `${hours}h`;
}

function formatDate(isoString: string): string {
  return new Date(isoString).toLocaleDateString("en-IN", {
    day: "numeric",
    month: "short",
    year: "numeric",
  });
}

function formatTime(isoString: string): string {
  return new Date(isoString).toLocaleTimeString("en-IN", {
    hour: "2-digit",
    minute: "2-digit",
  });
}

function formatINRBare(val: string | null): string {
  if (!val) return "—";
  const num = parseFloat(val);
  return isNaN(num) ? "—" : num.toFixed(2);
}

export function TransactionCard({ txn, vpa }: { txn: QRTransactionItem; vpa: string }) {
  return (
    <Card className="border-0 shadow-md bg-card">
      <CardContent className="p-4 space-y-3">
        <div className="flex justify-between items-start">
          <div>
            <p className="text-sm font-medium text-card-foreground">
              {formatDate(txn.created_at)}
            </p>
            <p className="text-xs text-muted-foreground">
              {formatTime(txn.created_at)}
            </p>
          </div>
          <Badge className={`border-0 ${getStatusBadgeClass(txn.status)}`}>
            {txn.status.replace("_", " ")}
          </Badge>
        </div>

        <div className="grid grid-cols-2 gap-3">
          <div className="flex items-center gap-2 p-2 bg-muted/50 rounded-lg">
            <IndianRupee className="h-4 w-4 text-muted-foreground" />
            <div>
              <p className="text-xs text-muted-foreground">Paid</p>
              <p className="font-semibold text-card-foreground">
                {formatINRBare(txn.amount_paid)}
              </p>
            </div>
          </div>
          <div className="flex items-center gap-2 p-2 bg-muted/50 rounded-lg">
            <Zap className="h-4 w-4 text-muted-foreground" />
            <div>
              <p className="text-xs text-muted-foreground">Energy</p>
              <p className="font-semibold text-card-foreground">
                {txn.energy_consumed_kwh != null
                  ? `${txn.energy_consumed_kwh.toFixed(2)} kWh`
                  : "N/A"}
              </p>
            </div>
          </div>
        </div>

        <div className="grid grid-cols-2 gap-3">
          {txn.duration_minutes != null && (
            <div className="flex items-center gap-2 text-sm text-muted-foreground">
              <Clock className="h-3.5 w-3.5" />
              <span>{formatDuration(txn.duration_minutes)}</span>
            </div>
          )}
          {txn.charger_name && (
            <div className="flex items-center gap-2 text-sm text-muted-foreground truncate">
              <Zap className="h-3.5 w-3.5 flex-shrink-0" />
              <span className="truncate">
                {txn.charger_name}
                {txn.station_name ? ` · ${txn.station_name}` : ""}
              </span>
            </div>
          )}
          {txn.franchisee_name && (
            <div className="text-xs text-muted-foreground truncate pl-5">
              Operator: <span className="font-medium">{txn.franchisee_name}</span>
            </div>
          )}
        </div>

        {txn.energy_cost && (
          <div className="border-t border-border pt-2 space-y-1 text-sm">
            <div className="flex justify-between text-muted-foreground">
              <span>Energy cost</span>
              <span>{formatINRBare(txn.energy_cost)}</span>
            </div>
            {txn.gst_amount && (
              <div className="flex justify-between text-muted-foreground">
                <span>GST</span>
                <span>{formatINRBare(txn.gst_amount)}</span>
              </div>
            )}
            {txn.platform_fee && (
              <div className="flex justify-between text-muted-foreground">
                <span>Platform fee{txn.fee_source === 'estimated' ? ' (est.)' : ''}</span>
                <span>{formatINRBare(txn.platform_fee)}</span>
              </div>
            )}
          </div>
        )}

        <RefundLifecycle txn={txn} />

        {txn.failure_reason &&
          (txn.status === "FAILED" || txn.status === "REFUND_FAILED") && (
            <div className="flex items-start gap-2 p-2 bg-red-50 dark:bg-red-900/20 border border-red-200 dark:border-red-700 rounded-lg">
              <AlertCircle className="h-4 w-4 text-red-600 dark:text-red-400 mt-0.5 flex-shrink-0" />
              <span className="text-sm text-red-800 dark:text-red-300">
                {txn.failure_reason}
              </span>
            </div>
          )}

        {(txn.status === "COMPLETED" || txn.status === "REFUNDED") && (
          <Button
            variant="outline"
            size="sm"
            className="w-full mt-2"
            onClick={async () => {
              try {
                await viewPublicInvoicePDF(txn.id, vpa);
              } catch (e) {
                alert(`PDF download failed: ${(e as Error).message}`);
              }
            }}
          >
            <Download className="h-4 w-4 mr-2" />
            Download GST Invoice
          </Button>
        )}
      </CardContent>
    </Card>
  );
}
