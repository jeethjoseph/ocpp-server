import { clsx, type ClassValue } from "clsx"
import { twMerge } from "tailwind-merge"

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs))
}

// Untethered connector types — the driver plugs in their own cable, so the
// charger idles in "Available" until authorised and CAN be remote-started from
// Available. Tethered/DC types (CCS, CHAdeMO, GB/T) transition to "Preparing"
// when a vehicle is plugged in and must be started from there. Anything we don't
// recognise defaults to tethered — we never auto-enable start-from-Available for
// an unknown type. See socket-charger-classification issue 01.
const SOCKET_CONNECTOR_TYPES = new Set(["socket", "type1", "type2", "domestic"]);

function normalizeConnectorType(raw: string): string {
  return raw.trim().toLowerCase().replace(/[\s_-]+/g, "");
}

export function isSocketCharger(
  connectors?: Array<{ connector_type: string }>
): boolean {
  return (
    connectors?.some((c) =>
      SOCKET_CONNECTOR_TYPES.has(normalizeConnectorType(c.connector_type))
    ) ?? false
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

/** Plain numeric formatter that returns `"—"` for null/invalid input.
 * Caller is responsible for prefixing `₹` or other symbols. Useful when the
 * call site already provides the currency symbol and just wants the digits. */
export function formatAmount(value: string | number | null | undefined): string {
  if (value === null || value === undefined || value === "") return "—";
  const n = typeof value === "number" ? value : Number(value);
  if (!Number.isFinite(n)) return "—";
  return n.toFixed(2);
}

export function formatTariffRangeAllIn(
  minAllIn: number | null | undefined,
  maxAllIn: number | null | undefined,
): string {
  if (minAllIn == null && maxAllIn == null) return "N/A";
  const lo = (minAllIn ?? maxAllIn) as number;
  const hi = (maxAllIn ?? minAllIn) as number;
  if (Math.abs(lo - hi) < 0.005) return `₹${lo.toFixed(2)}/kWh (incl. GST)`;
  return `₹${lo.toFixed(2)}–₹${hi.toFixed(2)}/kWh (incl. GST)`;
}

export function formatTariffBare(
  minAllIn: number | null | undefined,
  maxAllIn: number | null | undefined,
): string | null {
  if (minAllIn == null && maxAllIn == null) return null;
  const lo = (minAllIn ?? maxAllIn) as number;
  const hi = (maxAllIn ?? minAllIn) as number;
  if (Math.abs(lo - hi) < 0.005) return `₹${lo.toFixed(2)}/kWh`;
  return `₹${lo.toFixed(2)}–₹${hi.toFixed(2)}/kWh`;
}

/**
 * Back-derivation for the admin tariff-form live preview. Given a
 * GST-inclusive, gateway-EXCLUSIVE per-kWh rate, returns the two-line
 * breakdown the operator sees as they type. ADR 0026.
 *
 * Math: base rate is the GST-inclusive figure with GST backed out —
 * `ratePerKwh = rateGstIncluded / (1 + gst%/100)`. There is NO gateway
 * component in the tariff; the Razorpay gateway fee is a separate, variable
 * line billed on top and is not known at tariff-entry time. The two returned
 * components sum back to `rateGstIncluded` (within rounding).
 */
export function breakdownGstIncludedTariff(
  rateGstIncluded: number,
  gstPercent = 18,
): { ratePerKwh: number; gstPerKwh: number } | null {
  if (!Number.isFinite(rateGstIncluded) || rateGstIncluded <= 0) return null;
  const ratePerKwh = rateGstIncluded / (1 + gstPercent / 100);
  const gstPerKwh = rateGstIncluded - ratePerKwh;
  return { ratePerKwh, gstPerKwh };
}
