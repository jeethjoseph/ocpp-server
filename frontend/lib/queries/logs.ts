import { useQuery } from "@tanstack/react-query";
import { logService, auditLogService } from "../api-services";
import { useAuth } from "@/contexts/AuthContext";

export const useChargerLogs = (
  chargePointId: string,
  params?: {
    start_date?: string;
    end_date?: string;
    limit?: number;
  }
) => {
  const { isAuthReady } = useAuth();

  return useQuery({
    queryKey: ["chargerLogs", chargePointId, params],
    queryFn: () => logService.getChargerLogs(chargePointId, params),
    enabled: isAuthReady && !!chargePointId,
    staleTime: Infinity, // Historical data never changes
    gcTime: 10 * 60 * 1000, // Keep in cache for 10 minutes
    refetchOnWindowFocus: false, // No need to refetch historical data
    refetchOnMount: false, // No need to refetch if we have data
  });
};

export const useChargerLogSummary = (chargePointId: string) => {
  const { isAuthReady } = useAuth();

  return useQuery({
    queryKey: ["chargerLogSummary", chargePointId],
    queryFn: () => logService.getChargerLogSummary(chargePointId),
    enabled: isAuthReady && !!chargePointId,
    staleTime: Infinity, // Summary of historical data doesn't change
    gcTime: 30 * 60 * 1000, // Keep in cache for 30 minutes
    refetchOnWindowFocus: false,
    refetchOnMount: false,
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