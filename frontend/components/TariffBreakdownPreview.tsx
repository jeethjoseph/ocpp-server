"use client";

import { breakdownGstIncludedTariff } from "@/lib/utils";

export interface TariffBreakdownPreviewProps {
  value: string;
  /** GST rate in percent applied to per-kWh energy charge. */
  gstPercent: number;
}

/**
 * Live preview of the back-derivation for the admin tariff form. The operator
 * types a GST-inclusive, gateway-EXCLUSIVE per-kWh rate; this renders the two
 * components that make it up (base rate_per_kwh + GST). The Razorpay gateway
 * fee is NOT part of the tariff — it's a separate, variable line billed on top
 * and unknown at tariff-entry time. See ADR 0026.
 */
export function TariffBreakdownPreview({
  value,
  gstPercent,
}: TariffBreakdownPreviewProps) {
  const parsed = parseFloat(value);
  const breakdown = breakdownGstIncludedTariff(parsed, gstPercent);
  if (!breakdown) return null;
  return (
    <div className="mt-2 rounded-md border border-border bg-muted/30 p-3 text-xs font-mono text-muted-foreground">
      <div className="flex justify-between">
        <span>→ Base rate (rate_per_kwh):</span>
        <span>₹{breakdown.ratePerKwh.toFixed(4)}/kWh</span>
      </div>
      <div className="flex justify-between">
        <span>→ GST ({gstPercent}%):</span>
        <span>₹{breakdown.gstPerKwh.toFixed(4)}/kWh</span>
      </div>
      <div className="mt-2 border-t border-border pt-2 text-[11px] not-italic">
        Gateway fee (Razorpay actual) billed separately.
      </div>
    </div>
  );
}
