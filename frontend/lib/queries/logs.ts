import { useQuery } from "@tanstack/react-query";
import { logService } from "../api-services";
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