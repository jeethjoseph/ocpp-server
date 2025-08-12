import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { chargerService, stationService } from "@/lib/api-services";
import { ChargerListResponse } from "@/types/api";
import { toast } from "sonner";
import { transactionKeys } from "./transactions";

// Query Keys
export const chargerKeys = {
  all: ["chargers"] as const,
  lists: () => [...chargerKeys.all, "list"] as const,
  list: (params: Record<string, unknown>) => [...chargerKeys.lists(), params] as const,
  details: () => [...chargerKeys.all, "detail"] as const,
  detail: (id: number) => [...chargerKeys.details(), id] as const,
};

export const stationKeys = {
  all: ["stations"] as const,
  lists: () => [...stationKeys.all, "list"] as const,
  list: (params: Record<string, unknown>) => [...stationKeys.lists(), params] as const,
};

// Chargers Query Hook
export function useChargers(params: {
  page?: number;
  limit?: number;
  status?: string;
  station_id?: number;
  search?: string;
  sort?: string;
}) {
  return useQuery({
    queryKey: chargerKeys.list(params),
    queryFn: () => chargerService.getAll(params),
    staleTime: 1000 * 10, // 10 seconds - frequent updates for OCPP status
    refetchInterval: 1000 * 10, // Auto-refresh every 10 seconds for real-time status
  });
}

// Stations Query Hook (for dropdown/filters)
export function useStations(params: { limit?: number } = {}) {
  return useQuery({
    queryKey: stationKeys.list(params),
    queryFn: () => stationService.getAll(params),
    staleTime: 1000 * 60 * 5, // 5 minutes - stations don't change often
  });
}

// Individual Charger Query Hook
export function useCharger(id: number) {
  return useQuery({
    queryKey: chargerKeys.detail(id),
    queryFn: () => chargerService.getById(id),
    enabled: !!id,
    staleTime: 1000 * 10, // 10 seconds
    refetchInterval: 1000 * 10, // Auto-refresh every 10 seconds
  });
}

// Remote Start Mutation Hook
export function useRemoteStart() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: async ({
      id,
      connectorId = 1,
      idTag = "admin",
    }: {
      id: number;
      connectorId?: number;
      idTag?: string;
    }) => {
      
      try {
        const result = await chargerService.remoteStart(id, connectorId, idTag);
        return result;
      } catch (error) {
        throw error;
      }
    },
    onSuccess: (_, variables) => {
      // Invalidate charger details to refetch latest status
      queryClient.invalidateQueries({ queryKey: chargerKeys.detail(variables.id) });
      toast.success("Remote start command sent successfully. Waiting for charger to start charging...");
    },
    onError: (err) => {
      const errorMessage = err instanceof Error ? err.message : String(err);
      console.error("Remote start error:", errorMessage);
      if (errorMessage.includes("409") || errorMessage.includes("not connected")) {
        toast.error("Charger not connected or not in correct state");
      } else {
        toast.error("Failed to start charging");
      }
    },
  });
}

// Change Availability Mutation Hook
export function useChangeAvailability() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: async ({
      id,
      type,
      connectorId = 0,
    }: {
      id: number;
      type: "Inoperative" | "Operative";
      connectorId?: number;
    }) => {
      return chargerService.changeAvailability(id, type, connectorId);
    },
    onMutate: async ({ id, type }) => {
      // Cancel outgoing refetches so they don't overwrite optimistic update
      await queryClient.cancelQueries({ queryKey: chargerKeys.all });

      // Snapshot previous value for rollback
      const previousChargers = queryClient.getQueriesData({
        queryKey: chargerKeys.lists(),
      });

      // Optimistically update charger status
      queryClient.setQueriesData<ChargerListResponse>(
        { queryKey: chargerKeys.lists() },
        (old) => {
          if (!old) return old;

          const optimisticStatus = type === "Inoperative" ? "Unavailable" : "Available";
          
          return {
            ...old,
            data: old.data.map((charger) =>
              charger.id === id
                ? { ...charger, latest_status: optimisticStatus }
                : charger
            ),
          };
        }
      );

      return { previousChargers };
    },
    onSuccess: (data, variables) => {
      const status = variables.type === "Inoperative" ? "unavailable" : "available";
      toast.success(`Charger marked as ${status}`);
    },
    onError: (err, variables, context) => {
      // Rollback optimistic update on error
      if (context?.previousChargers) {
        context.previousChargers.forEach(([queryKey, data]) => {
          queryClient.setQueryData(queryKey, data);
        });
      }
      
      const errorMessage = err instanceof Error ? err.message : String(err);
      if (errorMessage.includes("409") || errorMessage.includes("not connected")) {
        toast.error("Charger not connected");
      } else {
        toast.error("Failed to change availability");
      }
    },
  });
}

// Remote Stop Mutation Hook
export function useRemoteStop() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: async ({
      id,
      reason,
    }: {
      id: number;
      reason?: string;
    }) => {
      return chargerService.remoteStop(id, reason);
    },
    onSuccess: () => {
      // Invalidate chargers to refetch latest status
      queryClient.invalidateQueries({ queryKey: chargerKeys.all });
      // Invalidate transactions to refetch final transaction status and energy consumed
      queryClient.invalidateQueries({ queryKey: transactionKeys.all });
      
      // Delayed refetches to handle OCPP backend processing delays
      const refetchDelays = [3000, 6000]; // 3s, 6s - optimized based on testing
      refetchDelays.forEach((delay) => {
        setTimeout(() => {
          queryClient.invalidateQueries({ queryKey: chargerKeys.all });
          queryClient.invalidateQueries({ queryKey: transactionKeys.all });
        }, delay);
      });
      
      toast.success("Remote stop initiated");
    },
    onError: (err) => {
      const errorMessage = err instanceof Error ? err.message : String(err);
      console.error("Remote stop error:", errorMessage);
      if (errorMessage.includes("409") || errorMessage.includes("not connected")) {
        toast.error("Charger not connected or no active session");
      } else {
        toast.error("Failed to initiate remote stop");
      }
    },
  });
}

// Delete Charger Mutation Hook
export function useDeleteCharger() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (id: number) => chargerService.delete(id),
    onSuccess: () => {
      // Invalidate chargers list to refetch
      queryClient.invalidateQueries({ queryKey: chargerKeys.lists() });
      toast.success("Charger deleted successfully");
    },
    onError: (err) => {
      const errorMessage = err instanceof Error ? err.message : String(err);
      console.error("Delete charger error:", errorMessage);
      toast.error("Failed to delete charger");
    },
  });
}