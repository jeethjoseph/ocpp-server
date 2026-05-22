import { useEffect, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { publicQRActiveSessionService, QRActiveSessionListResponse } from "../api-services";

export const publicQRActiveSessionKeys = {
  all: ["public-qr-active-sessions"] as const,
  list: (vpa: string) => [...publicQRActiveSessionKeys.all, vpa] as const,
};

const POLL_ACTIVE_MS = 15_000;
const POLL_IDLE_MS = 60_000;

/**
 * Live-poll the customer's active QR sessions.
 *
 * Adaptive cadence:
 *   - 15s while at least one active session is in the response
 *   - 60s when the response is empty (lower-cost idle poll)
 * Pauses entirely when the tab is hidden (no MeterValues are pushed when the
 * customer isn't looking; we shouldn't burn requests either). Resumes
 * immediately on `visibilitychange`.
 *
 * See ADR 0006 for why this is read-only — no mutation hook ships alongside.
 */
export function usePublicQRActiveSessions(vpa: string) {
  const [visible, setVisible] = useState<boolean>(
    typeof document === "undefined" ? true : document.visibilityState === "visible",
  );

  useEffect(() => {
    if (typeof document === "undefined") return;
    const onVis = () => setVisible(document.visibilityState === "visible");
    document.addEventListener("visibilitychange", onVis);
    return () => document.removeEventListener("visibilitychange", onVis);
  }, []);

  const query = useQuery<QRActiveSessionListResponse, Error>({
    queryKey: publicQRActiveSessionKeys.list(vpa),
    queryFn: () => publicQRActiveSessionService.getByVpa(vpa),
    enabled: !!vpa,
    refetchInterval: (q) => {
      if (!visible) return false;
      const hasActive = (q.state.data?.total ?? 0) > 0;
      return hasActive ? POLL_ACTIVE_MS : POLL_IDLE_MS;
    },
    refetchIntervalInBackground: false,
    staleTime: 5_000,
  });

  return query;
}
