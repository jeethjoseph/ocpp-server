"use client";

import { useState } from "react";
import { CheckCircle2, MinusCircle } from "lucide-react";

import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import {
  useMarkSettlementBelowThreshold,
  useMarkSettlementSettled,
} from "@/lib/queries/admin-settlements";
import { cn } from "@/lib/utils";
import { formatINR } from "@/lib/utils";

// Mirror of MINIMUM_TRANSFER_AMOUNT env on the backend. Razorpay Route
// won't accept transfers below ₹1.00, so this is also the eligibility
// threshold for marking BELOW_THRESHOLD. Server is the source of truth —
// this constant only gates which button shows in the UI.
const MIN_TRANSFER_AMOUNT_INR = 1.0;

const BELOW_THRESHOLD_SOURCES = new Set(["PENDING", "FAILED", "ON_HOLD"]);
const MANUAL_SETTLE_SOURCES = new Set([
  "PENDING",
  "TRANSFER_INITIATED",
  "TRANSFER_PROCESSED",
  "FAILED",
  "ON_HOLD",
]);

export interface SettlementTerminalActionsEntry {
  id: number;
  franchisee_id: number;
  settlement_status: string;
  franchisee_payout: string | number;
}

interface Props {
  entry: SettlementTerminalActionsEntry;
  className?: string;
}

type PendingAction =
  | { kind: "below_threshold" }
  | { kind: "settled"; note: string };

export function SettlementTerminalActions({ entry, className }: Props) {
  const [pending, setPending] = useState<PendingAction | null>(null);
  const markBelowThreshold = useMarkSettlementBelowThreshold();
  const markSettled = useMarkSettlementSettled();

  const payout =
    typeof entry.franchisee_payout === "string"
      ? parseFloat(entry.franchisee_payout)
      : entry.franchisee_payout;

  const canMarkBelowThreshold =
    BELOW_THRESHOLD_SOURCES.has(entry.settlement_status) &&
    payout < MIN_TRANSFER_AMOUNT_INR;
  const canMarkSettled = MANUAL_SETTLE_SOURCES.has(entry.settlement_status);

  if (!canMarkBelowThreshold && !canMarkSettled) return null;

  const noteTooShort =
    pending?.kind === "settled" && pending.note.trim().length < 3;
  const submitting = markBelowThreshold.isPending || markSettled.isPending;

  function confirm() {
    if (!pending) return;
    if (pending.kind === "below_threshold") {
      markBelowThreshold.mutate(
        { entryId: entry.id, franchiseeId: entry.franchisee_id },
        { onSuccess: () => setPending(null) },
      );
    } else {
      if (pending.note.trim().length < 3) return;
      markSettled.mutate(
        {
          entryId: entry.id,
          franchiseeId: entry.franchisee_id,
          note: pending.note.trim(),
        },
        { onSuccess: () => setPending(null) },
      );
    }
  }

  return (
    <div className={cn("flex gap-1", className)}>
      {canMarkBelowThreshold && (
        <Button
          size="sm"
          variant="ghost"
          onClick={() => setPending({ kind: "below_threshold" })}
          title="Mark BELOW_THRESHOLD (sub-floor payout)"
        >
          <MinusCircle className="w-3 h-3" />
        </Button>
      )}
      {canMarkSettled && (
        <Button
          size="sm"
          variant="ghost"
          onClick={() => setPending({ kind: "settled", note: "" })}
          title="Mark SETTLED (resolved out-of-band)"
        >
          <CheckCircle2 className="w-3 h-3" />
        </Button>
      )}

      <Dialog
        open={pending !== null}
        onOpenChange={(open) => {
          if (!open && !submitting) setPending(null);
        }}
      >
        <DialogContent className="max-w-md">
          <DialogHeader>
            <DialogTitle>
              {pending?.kind === "below_threshold"
                ? "Mark BELOW_THRESHOLD?"
                : "Mark SETTLED (manual)?"}
            </DialogTitle>
            <DialogDescription>
              Entry #{entry.id} · payout{" "}
              <span className="font-semibold">{formatINR(payout)}</span> ·
              currently {entry.settlement_status.replace(/_/g, " ")}
            </DialogDescription>
          </DialogHeader>

          {pending?.kind === "below_threshold" && (
            <p className="text-sm text-muted-foreground">
              Razorpay Route refuses transfers below ₹{MIN_TRANSFER_AMOUNT_INR.toFixed(2)}.
              This marks the entry terminal as <strong>BELOW_THRESHOLD</strong> so the
              retry sweep stops picking it up. Irreversible from the UI.
            </p>
          )}

          {pending?.kind === "settled" && (
            <div className="space-y-2">
              <p className="text-sm text-muted-foreground">
                For entries resolved out-of-band (e.g. paid by direct bank
                transfer). Sets the row terminal as <strong>SETTLED</strong> with{" "}
                <code>settled_at = now()</code>. Razorpay IDs untouched. Irreversible
                from the UI.
              </p>
              <label className="text-xs font-medium" htmlFor="manual-settle-note">
                Resolution note (required, min 3 chars)
              </label>
              <textarea
                id="manual-settle-note"
                value={pending.note}
                onChange={(e) =>
                  setPending({ kind: "settled", note: e.target.value })
                }
                placeholder="e.g. Paid via bank transfer UTR ABC123 on 2026-05-26"
                className="w-full min-h-[80px] rounded-md border bg-transparent px-3 py-2 text-sm shadow-xs outline-none focus-visible:ring-ring/50 focus-visible:ring-[3px] focus-visible:border-ring"
              />
            </div>
          )}

          <DialogFooter>
            <Button
              type="button"
              variant="outline"
              onClick={() => setPending(null)}
              disabled={submitting}
            >
              Cancel
            </Button>
            <Button
              type="button"
              onClick={confirm}
              disabled={submitting || noteTooShort}
            >
              {submitting ? "Working…" : "Confirm"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
