import { useQuery, useQueryClient } from "@tanstack/react-query";
import { stationService, chargerService } from "@/lib/api-services";

// Query Keys
export const dashboardKeys = {
  all: ["dashboard"] as const,
  stats: () => [...dashboardKeys.all, "stats"] as const,
};

// Dashboard Stats Query Hook
export function useDashboardStats() {
  return useQuery({
    queryKey: dashboardKeys.stats(),
    queryFn: async () => {
      const [stationsResponse, chargersResponse] = await Promise.all([
        stationService.getAll({ limit: 1 }), // Just need total count
        chargerService.getAll({ limit: 100 }), // Get all chargers for status analysis
      ]);

      const chargers = chargersResponse.data;
      
      return {
        totalStations: stationsResponse.total,
        totalChargers: chargers.length,
        availableChargers: chargers.filter(c => c.latest_status === 'Available').length,
        chargingChargers: chargers.filter(c => c.latest_status === 'Charging').length,
        unavailableChargers: chargers.filter(c => c.latest_status === 'Unavailable').length,
        faultedChargers: chargers.filter(c => c.latest_status === 'Faulted').length,
        connectedChargers: chargers.filter(c => c.connection_status).length,
        disconnectedChargers: chargers.filter(c => !c.connection_status).length,
      };
    },
    staleTime: 1000 * 10, // 10 seconds - dashboard should be very fresh
    refetchInterval: 1000 * 10, // Auto-refresh every 10 seconds
  });
}

// Dashboard refresh helper hook
export function useDashboardRefresh() {
  const queryClient = useQueryClient();
  
  return () => {
    queryClient.invalidateQueries({ queryKey: dashboardKeys.all });
  };
}