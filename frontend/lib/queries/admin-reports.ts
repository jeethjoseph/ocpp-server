import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api-client";
import { useAuth } from "@/contexts/AuthContext";

export type Grain = "week" | "month";

export interface CohortCell {
  offset: number;
  active: number;
}

export interface Cohort {
  cohort: string; // YYYY-MM-DD, period start
  size: number;
  cells: CohortCell[];
}

export interface ChurnSummary {
  customers: number;
  one_time: number;
  repeat: number;
  avg_sessions: string | null;
  avg_ltv: string | null;
  median_ltv: string | null;
  successful_sessions: number;
  net_revenue: string | null;
  latest_period: string | null;
}

export interface QRChurnReport {
  grain: Grain;
  generated_at: string; // server compute time (UTC ISO); informational only
  latest_period: string | null;
  max_offset: number;
  summary: ChurnSummary;
  cohorts: Cohort[];
}

export const adminReportsKeys = {
  all: ["admin-reports"] as const,
  qrChurn: (grain: Grain) =>
    [...adminReportsKeys.all, "qr-churn", grain] as const,
};

/**
 * QR churn cohort report. Computed live on the server (ADR 0025) — there is no
 * cache. `staleTime: Infinity` + the disabled auto-refetches mean this only
 * hits the network on first load and on an explicit `refetch()`; the page's
 * "last refreshed" label reads the query's `dataUpdatedAt`.
 */
export function useQRChurnReport(grain: Grain) {
  const { isAuthReady } = useAuth();
  return useQuery({
    queryKey: adminReportsKeys.qrChurn(grain),
    queryFn: () =>
      api.get<QRChurnReport>(`/api/admin/reports/qr-churn?grain=${grain}`),
    staleTime: Infinity,
    gcTime: Infinity,
    refetchOnMount: false,
    refetchOnWindowFocus: false,
    refetchOnReconnect: false,
    enabled: isAuthReady,
  });
}
