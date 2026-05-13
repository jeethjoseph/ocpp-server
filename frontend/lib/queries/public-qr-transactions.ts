import { useQuery } from "@tanstack/react-query";
import { publicQRTransactionService, QRTransactionListResponse } from "../api-services";

export const publicQRTransactionKeys = {
  all: ["public-qr-transactions"] as const,
  list: (params: Record<string, unknown>) =>
    [...publicQRTransactionKeys.all, "list", params] as const,
};

export function usePublicQRTransactions(params: {
  vpa: string;
  page?: number;
  limit?: number;
  status?: string;
}) {
  return useQuery<QRTransactionListResponse, Error>({
    queryKey: publicQRTransactionKeys.list(params),
    queryFn: () => publicQRTransactionService.getByVpa(params),
    enabled: !!params.vpa,
    staleTime: 30000,
  });
}

/** Open the invoice PDF for a QR session in a new tab.
 *
 * Public endpoint — no auth required; the customer's own VPA is the implicit
 * credential. Backend verifies the VPA matches qr_payment.customer_vpa and
 * returns 404 otherwise. Hits the same lazy-S3 + inline-fallback path as
 * authenticated downloads. */
export async function viewPublicInvoicePDF(
  qrPaymentId: number,
  vpa: string,
): Promise<void> {
  const baseUrl = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";
  const url =
    `${baseUrl}/api/public/qr-transactions/${qrPaymentId}/invoice/pdf` +
    `?vpa=${encodeURIComponent(vpa)}`;

  const res = await fetch(url, { method: "GET", redirect: "follow" });
  if (!res.ok) {
    if (res.status === 404) {
      throw new Error("Invoice not found for this VPA");
    }
    if (res.status === 429) {
      throw new Error("Too many requests — please wait a minute and try again");
    }
    throw new Error(`PDF fetch failed: ${res.status} ${res.statusText}`);
  }

  const blob = await res.blob();
  const objectUrl = URL.createObjectURL(blob);
  const newTab = window.open(objectUrl, "_blank");
  if (!newTab) {
    // Popup blocked — force a download instead
    const link = document.createElement("a");
    link.href = objectUrl;
    link.download = `invoice_${qrPaymentId}.pdf`;
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
  }
  setTimeout(() => URL.revokeObjectURL(objectUrl), 60_000);
}
