import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api-client";
import { useAuth } from "@/contexts/AuthContext";

export interface StuckSettlementEntry {
  id: number;
  franchisee_id: number;
  franchisee_business_name: string;
  transaction_id: number | null;
  settlement_status: string;
  franchisee_payout: string;
  gross_amount: string;
  retry_count: number;
  failure_reason: string | null;
  razorpay_payment_id: string | null;
  razorpay_transfer_id: string | null;
  created_at: string;
  transfer_initiated_at: string | null;
}

export interface StuckSettlementsResponse {
  data: StuckSettlementEntry[];
  total: number;
  page: number;
  limit: number;
  older_than_hours: number;
}

export interface UseStuckSettlementsParams {
  page?: number;
  limit?: number;
  older_than_hours?: number;
  status?: string;
}

export const adminSettlementsKeys = {
  all: ["admin-settlements"] as const,
  stuck: (params: UseStuckSettlementsParams) =>
    [...adminSettlementsKeys.all, "stuck", params] as const,
};

export function useAdminStuckSettlements(params: UseStuckSettlementsParams = {}) {
  const { isAuthReady } = useAuth();
  const search = new URLSearchParams();
  if (params.page) search.set("page", String(params.page));
  if (params.limit) search.set("limit", String(params.limit));
  if (params.older_than_hours)
    search.set("older_than_hours", String(params.older_than_hours));
  if (params.status) search.set("status", params.status);
  const query = search.toString();

  return useQuery({
    queryKey: adminSettlementsKeys.stuck(params),
    queryFn: () =>
      api.get<StuckSettlementsResponse>(
        `/api/admin/settlements/stuck${query ? `?${query}` : ""}`
      ),
    staleTime: 1000 * 30,
    enabled: isAuthReady,
  });
}
