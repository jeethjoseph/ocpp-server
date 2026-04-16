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
