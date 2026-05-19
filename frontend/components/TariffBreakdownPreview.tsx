"use client";

import { breakdownAllInTariff } from "@/lib/utils";

export interface TariffBreakdownPreviewProps {
  value: string;
  /** Synthetic platform-fee rate in percent (mirrors backend ADR 0001). */
  feePercent: number;
  /** GST rate in percent applied to per-kWh energy charge. */
  gstPercent: number;
}

/**
 * Live preview of the back-derivation for the admin tariff form. Renders the
 * three components the operator should expect to see on a customer's invoice
 * (rate_per_kwh, gateway fee, GST) given an all-inclusive per-kWh input.
 *
 * Mirrors the backend's `back_derive_rate_per_kwh` formula. See ADR 0003.
 */
export function TariffBreakdownPreview({
  value,
  feePercent,
  gstPercent,
}: TariffBreakdownPreviewProps) {
  const parsed = parseFloat(value);
  const breakdown = breakdownAllInTariff(parsed, gstPercent, feePercent);
  if (!breakdown) return null;
  return (
    <div className="mt-2 rounded-md border border-border bg-muted/30 p-3 text-xs font-mono text-muted-foreground">
      <div className="flex justify-between">
        <span>→ Base rate (rate_per_kwh):</span>
        <span>₹{breakdown.ratePerKwh.toFixed(4)}/kWh</span>
      </div>
      <div className="flex justify-between">
        <span>→ Gateway fee ({feePercent}%):</span>
        <span>₹{breakdown.gatewayPerKwh.toFixed(4)}/kWh</span>
      </div>
      <div className="flex justify-between">
        <span>→ GST ({gstPercent}%):</span>
        <span>₹{breakdown.gstPerKwh.toFixed(4)}/kWh</span>
      </div>
    </div>
  );
}
