import { clsx, type ClassValue } from "clsx"
import { twMerge } from "tailwind-merge"

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs))
}

export function isSocketCharger(
  connectors?: Array<{ connector_type: string }>
): boolean {
  return (
    connectors?.some((c) => c.connector_type.toLowerCase() === "socket") ??
    false
  );
}

const INR_FORMATTER = new Intl.NumberFormat("en-IN", {
  style: "currency",
  currency: "INR",
  maximumFractionDigits: 2,
  minimumFractionDigits: 2,
});

export function formatINR(value: string | number | null | undefined): string {
  if (value === null || value === undefined || value === "") return "₹—";
  const n = typeof value === "number" ? value : Number(value);
  if (!Number.isFinite(n)) return "₹—";
  return INR_FORMATTER.format(n);
}

export function formatTariffRangeAllIn(
  minAllIn: number | null | undefined,
  maxAllIn: number | null | undefined,
): string {
  if (minAllIn == null && maxAllIn == null) return "N/A";
  const lo = (minAllIn ?? maxAllIn) as number;
  const hi = (maxAllIn ?? minAllIn) as number;
  if (Math.abs(lo - hi) < 0.005) return `₹${lo.toFixed(2)}/kWh (all-inclusive)`;
  return `₹${lo.toFixed(2)}–₹${hi.toFixed(2)}/kWh (all-inclusive)`;
}

/**
 * Mirror of `services/tariff_utils.back_derive_rate_per_kwh` for the admin
 * tariff-form live preview. Given an all-in per-kWh rate, returns the
 * three-line breakdown the operator sees as they type. ADR 0003.
 *
 * Math: gateway fee deducted first (2% of all-in), then GST backed out
 * of the remainder. Result components sum back to `allIn` (within rounding).
 */
export function breakdownAllInTariff(
  allIn: number,
  gstPercent = 18,
  feePercent = 2,
): { ratePerKwh: number; gatewayPerKwh: number; gstPerKwh: number } | null {
  if (!Number.isFinite(allIn) || allIn <= 0) return null;
  const gatewayPerKwh = allIn * (feePercent / 100);
  const postGateway = allIn - gatewayPerKwh; // still includes GST
  const ratePerKwh = postGateway / (1 + gstPercent / 100);
  const gstPerKwh = postGateway - ratePerKwh;
  return { ratePerKwh, gatewayPerKwh, gstPerKwh };
}
