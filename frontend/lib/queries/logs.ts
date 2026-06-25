import { useQuery } from "@tanstack/react-query";
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