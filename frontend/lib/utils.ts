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
