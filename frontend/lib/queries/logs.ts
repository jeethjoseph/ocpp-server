import { useQuery, keepPreviousData } from "@tanstack/react-query";
import { logService, auditLogService } from "../api-services";
import { useAuth } from "@/contexts/AuthContext";

export const useLogs = (params: {
  charge_point_id?: string;
  message_type?: string[];
  start_date?: string;
  end_date?: string;
  direction?: string;
  errors_only?: boolean;
  offset?: number;
  limit?: number;
}) => {
  const { isAuthReady } = useAuth();

  return useQuery({
    queryKey: ["logs", params],
    queryFn: () => logService.getLogs(params),
    enabled: isAuthReady,
    staleTime: 30 * 1000,
    gcTime: 5 * 60 * 1000,
    refetchOnWindowFocus: false,
    // Keep the previous page visible while the next loads (offset pagination)
    // so stepping Prev/Next doesn't unmount the list and flash the loading state.
    placeholderData: keepPreviousData,
  });
};

// Fetch the correlated reply (CallResult/CallError) for a single OCPP request.
// Scoped by correlation_id + charge_point_id + a tight window around the request
// timestamp: the window (a) beats the endpoint's default 24h bound for historical
// rows and (b) disambiguates charger-reused messageIds across reboots (a boot_*
// id is not globally unique). Lazy — only runs once the row is expanded.
export const useLogReply = (params: {
  correlationId: string | null;
  chargePointId: string | null;
  aroundIso: string;
  enabled: boolean;
}) => {
  const { isAuthReady } = useAuth();
  const { correlationId, chargePointId, aroundIso } = params;
  const around = new Date(aroundIso).getTime();
  const start_date = new Date(around - 5_000).toISOString();
  const end_date = new Date(around + 120_000).toISOString();

  return useQuery({
    queryKey: ["logReply", correlationId, chargePointId, aroundIso],
    queryFn: () =>
      logService.getLogs({
        correlation_id: correlationId ?? undefined,
        charge_point_id: chargePointId ?? undefined,
        start_date,
        end_date,
        limit: 20,
      }),
    enabled: isAuthReady && params.enabled && !!correlationId,
    staleTime: 5 * 60 * 1000,
    gcTime: 5 * 60 * 1000,
    refetchOnWindowFocus: false,
  });
};

export const useChargerTimeline = (
  chargePointId: string,
  params?: {
    page?: number;
    limit?: number;
    action?: string;
    actor_type?: string;
    start_date?: string;
    end_date?: string;
  }
) => {
  const { isAuthReady } = useAuth();

  return useQuery({
    queryKey: ["chargerTimeline", chargePointId, params],
    queryFn: () => auditLogService.getChargerTimeline(chargePointId, params),
    enabled: isAuthReady && !!chargePointId,
    staleTime: 30 * 1000,
    gcTime: 5 * 60 * 1000,
  });
};

export const useEntityAuditLogs = (
  entityType: string,
  entityId: string,
  params?: {
    page?: number;
    limit?: number;
    action?: string;
    actor_type?: string;
    start_date?: string;
    end_date?: string;
  }
) => {
  const { isAuthReady } = useAuth();

  return useQuery({
    queryKey: ["auditLogs", entityType, entityId, params],
    queryFn: () =>
      auditLogService.getAuditLogs({
        entity_type: entityType,
        entity_id: entityId,
        ...params,
      }),
    enabled: isAuthReady && !!entityId,
    staleTime: 30 * 1000,
    gcTime: 5 * 60 * 1000,
  });
};