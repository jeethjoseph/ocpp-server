"use client";

import { AlertCircle, RefreshCw } from "lucide-react";
import { QRTransactionItem } from "@/lib/api-services";
import { formatINR } from "@/lib/utils";

function formatRefundDate(iso: string): string {
  return new Date(iso).toLocaleString("en-IN", {
    day: "numeric",
    month: "short",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

export function RefundLifecycle({ txn }: { txn: QRTransactionItem }) {
  if (!txn.refund_amount) return null;

  const amount = formatINR(txn.refund_amount);

  // Sub-₹1 forfeit: Razorpay can't process amounts below ₹1, so there is no
  // refund to track. Show a calm, factual note — not the red "failed" or the
  // purple "initiated · awaiting confirmation" states (it never confirms).
  if (txn.refund_below_minimum) {
    return (
      <div className="p-2 bg-muted/50 border border-border rounded-lg">
        <span className="text-xs text-muted-foreground">
          {amount} unused — below Razorpay&apos;s ₹1 minimum, so it can&apos;t be refunded.
        </span>
      </div>
    );
  }

  if (txn.refund_failure_reason) {
    return (
      <div className="p-2 bg-red-50 dark:bg-red-900/20 border border-red-200 dark:border-red-700 rounded-lg space-y-1">
        <div className="flex items-center gap-2">
          <AlertCircle className="h-4 w-4 text-red-600 dark:text-red-400" />
          <span className="text-sm font-medium text-red-800 dark:text-red-300">
            Refund failed · {amount}
          </span>
        </div>
        <div className="text-xs text-red-700 dark:text-red-400 pl-6">
          {txn.refund_failure_reason}
        </div>
        {txn.razorpay_refund_id && (
          <div className="text-[11px] text-red-700/80 dark:text-red-400/80 pl-6">
            Ref: {txn.razorpay_refund_id}
          </div>
        )}
      </div>
    );
  }

  const processed = txn.refund_processed_at;
  const speed = txn.razorpay_refund_speed_processed;

  if (!processed) {
    return (
      <div className="p-2 bg-purple-50 dark:bg-purple-900/20 border border-purple-200 dark:border-purple-700 rounded-lg space-y-1">
        <div className="flex items-center gap-2">
          <RefreshCw className="h-4 w-4 text-purple-600 dark:text-purple-400" />
          <span className="text-sm font-medium text-purple-800 dark:text-purple-300">
            Refund initiated · {amount}
          </span>
        </div>
        <div className="text-xs text-purple-700 dark:text-purple-400 pl-6">
          Awaiting confirmation from Razorpay.
        </div>
      </div>
    );
  }

  const when = formatRefundDate(processed);
  const headline =
    speed === "instant"
      ? `Refunded to your account · ${amount}`
      : `Refund sent to your bank · ${amount}`;
  const detail =
    speed === "instant"
      ? `Processed on ${when}.`
      : speed === "normal"
        ? `Sent on ${when}. Banks usually credit within 5–10 working days.`
        : `Processed on ${when}.`;

  return (
    <div className="p-2 bg-purple-50 dark:bg-purple-900/20 border border-purple-200 dark:border-purple-700 rounded-lg space-y-1">
      <div className="flex items-center gap-2">
        <RefreshCw className="h-4 w-4 text-purple-600 dark:text-purple-400" />
        <span className="text-sm font-medium text-purple-800 dark:text-purple-300">
          {headline}
        </span>
      </div>
      <div className="text-xs text-purple-700 dark:text-purple-400 pl-6">
        {detail}
      </div>
      {txn.razorpay_refund_id && (
        <div className="text-[11px] text-purple-700/80 dark:text-purple-400/80 pl-6">
          Ref: {txn.razorpay_refund_id}
        </div>
      )}
    </div>
  );
}
