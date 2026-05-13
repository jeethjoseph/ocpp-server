import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api-client";
import { useAuth, getGlobalGetToken } from "@/contexts/AuthContext";

export interface GSTInvoice {
  id: number;
  invoice_number: string;
  series: string;
  financial_year: string;
  invoice_date: string | null;
  supplier_name: string;
  supplier_gstin: string | null;
  supplier_state_code: string | null;
  // Substore (Razorpay disclosure) — null for VoltLync-owned stations
  franchisee_business_name: string | null;
  franchisee_gstin: string | null;
  franchisee_address: string | null;
  franchisee_state: string | null;
  franchisee_state_code: string | null;
  customer_name: string | null;
  customer_identifier: string | null;
  place_of_supply_state_code: string | null;
  is_inter_state: boolean;
  station_name: string | null;
  charger_id_str: string | null;
  energy_consumed_kwh: number;
  hsn_sac_code: string;
  gst_rate_percent: string | null;
  energy_taxable_value: string | null;
  gateway_charges: string | null;
  total_taxable_value: string | null;
  cgst_rate: string | null;
  cgst_amount: string | null;
  sgst_rate: string | null;
  sgst_amount: string | null;
  igst_rate: string | null;
  igst_amount: string | null;
  total_tax: string | null;
  total_amount: string | null;
  payment_method: string | null;
  transaction_amount: string | null;
  refund_amount: string | null;
  transaction_id: number;
  franchisee_id: number | null;
  created_at: string;
}

export interface GSTInvoicesResponse {
  data: GSTInvoice[];
  total: number;
  page: number;
  limit: number;
}

export interface GSTInvoicesSummary {
  count: number;
  total_taxable_value: string;
  total_cgst: string;
  total_sgst: string;
  total_igst: string;
  total_tax: string;
  total_amount: string;
  by_series: Record<string, number>;
}

export interface GSTInvoiceFilters {
  page?: number;
  limit?: number;
  financial_year?: string;
  series?: "WAL" | "QR";
  franchisee_id?: number;
  start_date?: string;
  end_date?: string;
  place_of_supply_state_code?: string;
  is_inter_state?: boolean;
  q?: string;
}

export const adminGSTInvoicesKeys = {
  all: ["admin-gst-invoices"] as const,
  list: (params: GSTInvoiceFilters) =>
    [...adminGSTInvoicesKeys.all, "list", params] as const,
  summary: (params: Omit<GSTInvoiceFilters, "page" | "limit">) =>
    [...adminGSTInvoicesKeys.all, "summary", params] as const,
};

function buildSearch(params: GSTInvoiceFilters): string {
  const s = new URLSearchParams();
  if (params.page) s.set("page", String(params.page));
  if (params.limit) s.set("limit", String(params.limit));
  if (params.financial_year) s.set("financial_year", params.financial_year);
  if (params.series) s.set("series", params.series);
  if (params.franchisee_id !== undefined)
    s.set("franchisee_id", String(params.franchisee_id));
  if (params.start_date) s.set("start_date", params.start_date);
  if (params.end_date) s.set("end_date", params.end_date);
  if (params.place_of_supply_state_code)
    s.set("place_of_supply_state_code", params.place_of_supply_state_code);
  if (params.is_inter_state !== undefined)
    s.set("is_inter_state", String(params.is_inter_state));
  if (params.q) s.set("q", params.q);
  return s.toString();
}

export function useAdminGSTInvoices(params: GSTInvoiceFilters = {}) {
  const { isAuthReady } = useAuth();
  const query = buildSearch(params);
  return useQuery({
    queryKey: adminGSTInvoicesKeys.list(params),
    queryFn: () =>
      api.get<GSTInvoicesResponse>(
        `/api/admin/invoices${query ? `?${query}` : ""}`
      ),
    staleTime: 1000 * 30,
    enabled: isAuthReady,
  });
}

export function useAdminGSTInvoicesSummary(
  params: Omit<GSTInvoiceFilters, "page" | "limit"> = {}
) {
  const { isAuthReady } = useAuth();
  const query = buildSearch(params);
  return useQuery({
    queryKey: adminGSTInvoicesKeys.summary(params),
    queryFn: () =>
      api.get<GSTInvoicesSummary>(
        `/api/admin/invoices/summary${query ? `?${query}` : ""}`
      ),
    staleTime: 1000 * 30,
    enabled: isAuthReady,
  });
}

/** Open an invoice PDF in a new tab. The backend endpoint requires Bearer
 * auth, so we can't just point a plain `<a href>` at it — we have to fetch
 * with the auth header, follow the 302 to S3 (or the inline-streamed PDF
 * fallback), and open the result as a blob URL. */
export async function viewInvoicePDF(transactionId: number): Promise<void> {
  const baseUrl = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";
  const url = `${baseUrl}/api/transactions/${transactionId}/invoice/pdf`;

  const getToken = getGlobalGetToken();
  const token = getToken ? await getToken() : null;

  const res = await fetch(url, {
    method: "GET",
    headers: token ? { Authorization: `Bearer ${token}` } : undefined,
    redirect: "follow", // backend may 302 to a presigned S3 URL
  });
  if (!res.ok) {
    throw new Error(`PDF fetch failed: ${res.status} ${res.statusText}`);
  }

  const blob = await res.blob();
  const objectUrl = URL.createObjectURL(blob);
  const newTab = window.open(objectUrl, "_blank");
  if (!newTab) {
    // Popup blocked — fall back to forcing a download via anchor click
    const link = document.createElement("a");
    link.href = objectUrl;
    link.download = `invoice_${transactionId}.pdf`;
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
  }
  // Revoke after a minute so memory frees but the open tab stays usable.
  setTimeout(() => URL.revokeObjectURL(objectUrl), 60_000);
}

/** Fetches the filtered CSV from the backend with the current auth token and
 * triggers a browser download. The endpoint requires admin Bearer auth, so we
 * can't just point `window.location` at it — we have to fetch + blob. */
export async function downloadGSTInvoicesCSV(
  params: Omit<GSTInvoiceFilters, "page" | "limit"> = {}
): Promise<void> {
  const baseUrl = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";
  const query = buildSearch(params);
  const url = `${baseUrl}/api/admin/invoices/export.csv${query ? `?${query}` : ""}`;

  const getToken = getGlobalGetToken();
  const token = getToken ? await getToken() : null;

  const res = await fetch(url, {
    method: "GET",
    headers: token ? { Authorization: `Bearer ${token}` } : undefined,
  });
  if (!res.ok) {
    throw new Error(`CSV export failed: ${res.status} ${res.statusText}`);
  }

  const disposition = res.headers.get("Content-Disposition") || "";
  const match = disposition.match(/filename="?([^";]+)"?/i);
  const filename = match ? match[1] : `gst_invoices_${new Date().toISOString().slice(0, 10)}.csv`;

  const blob = await res.blob();
  const objectUrl = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = objectUrl;
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  document.body.removeChild(link);
  URL.revokeObjectURL(objectUrl);
}
