import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import {
  chargerService,
  stationService,
  signalQualityService,
  chargerErrorService,
  type ChangeAvailabilityResponse,
} from "@/lib/api-services";
import { ChargerListResponse } from "@/types/api";
import { toast } from "sonner";
import { transactionKeys } from "./transactions";
import { useAuth } from "@/contexts/AuthContext";

// Query Keys
export const chargerKeys = {
  all: ["chargers"] as const,
  lists: () => [...chargerKeys.all, "list"] as const,
  list: (params: Record<string, unknown>) => [...chargerKeys.lists(), params] as const,
  details: () => [...chargerKeys.all, "detail"] as const,
  detail: (id: number) => [...chargerKeys.details(), id] as const,
  signalQuality: (chargerId: number, hours: number) => [...chargerKeys.all, "signal-quality", chargerId, hours] as const,
  signalQualityLatest: (chargerId: number) => [...chargerKeys.all, "signal-quality-latest", chargerId] as const,
  errors: (chargerId: number, params: Record<string, unknown>) => [...chargerKeys.all, "errors", chargerId, params] as const,
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
  const { isAuthReady } = useAuth();

  return useQuery({
    queryKey: chargerKeys.list(params),
    queryFn: () => chargerService.getAll(params),
    staleTime: 1000 * 3, // 3 seconds - frequent updates for OCPP status
    refetchInterval: 1000 * 3, // Auto-refresh every 3 seconds for real-time status
    enabled: isAuthReady, // Wait for auth to be ready
  });
}

// Stations Query Hook (for dropdown/filters)
export function useStations(params: { limit?: number } = {}) {
  const { isAuthReady } = useAuth();

  return useQuery({
    queryKey: stationKeys.list(params),
    queryFn: () => stationService.getAll(params),
    staleTime: 1000 * 60 * 5, // 5 minutes - stations don't change often
    enabled: isAuthReady, // Wait for auth to be ready
  });
}

// Individual Charger Query Hook (by numeric ID)
export function useCharger(id: number, hasActiveTransaction?: boolean) {
  const { isAuthReady } = useAuth();

  return useQuery({
    queryKey: chargerKeys.detail(id),
    queryFn: () => chargerService.getById(id),
    enabled: isAuthReady && !!id, // Wait for auth and valid id
    staleTime: hasActiveTransaction ? 1000 * 2 : 1000 * 3, // 2s during active session, 3s otherwise
    refetchInterval: hasActiveTransaction ? 1000 * 2 : 1000 * 3, // More frequent polling during active sessions
  });
}

// Individual Charger Query Hook (by string ID - for user-facing pages)
export function useChargerByStringId(chargePointId: string, hasActiveTransaction?: boolean) {
  const { isAuthReady } = useAuth();

  return useQuery({
    queryKey: [...chargerKeys.all, "detail-string", chargePointId] as const,
    queryFn: () => chargerService.getByStringId(chargePointId),
    enabled: isAuthReady && !!chargePointId, // Wait for auth and valid id
    staleTime: hasActiveTransaction ? 1000 * 2 : 1000 * 3, // 2s during active session, 3s otherwise
    refetchInterval: hasActiveTransaction ? 1000 * 2 : 1000 * 3, // More frequent polling during active sessions
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

// Remote Start Mutation Hook (by string ID - for user-facing pages)
export function useRemoteStartByStringId() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: async ({
      chargePointId,
      connectorId = 1,
    }: {
      chargePointId: string;
      connectorId?: number;
    }) => {

      try {
        const result = await chargerService.remoteStartByStringId(chargePointId, connectorId);
        return result;
      } catch (error) {
        throw error;
      }
    },
    onSuccess: () => {
      // Invalidate all charger queries to refetch latest status
      queryClient.invalidateQueries({ queryKey: chargerKeys.all });
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
//
// Honours all three OCPP 1.6 response states. Per issue 01 (availability-toggle
// review fixes):
//   - Accepted  → toast success, keep optimistic update
//   - Scheduled → toast info ("will apply when current session ends"), revert
//                 the optimistic update (the StatusNotification fired when the
//                 transaction ends will reconcile the real state).
//   - Rejected  → toast error, revert.
//   - other     → defensive neutral toast, revert.

type ChangeAvailabilityVariables = {
  id: number;
  type: "Inoperative" | "Operative";
  connectorId?: number;
};

type ChangeAvailabilityContext = {
  previousChargers: Array<[readonly unknown[], unknown]>;
};

export function useChangeAvailability() {
  const queryClient = useQueryClient();

  // Single rollback helper so both onError and the non-Accepted onSuccess
  // branches can revert the optimistic update without duplicating the loop.
  const rollback = (context: ChangeAvailabilityContext | undefined) => {
    if (!context?.previousChargers) return;
    context.previousChargers.forEach(([queryKey, data]) => {
      queryClient.setQueryData(queryKey, data);
    });
  };

  return useMutation<
    ChangeAvailabilityResponse,
    Error,
    ChangeAvailabilityVariables,
    ChangeAvailabilityContext
  >({
    mutationFn: async ({ id, type, connectorId = 0 }) => {
      // chargerService.changeAvailability is typed Promise<ChangeAvailabilityResponse>
      // — no cast needed.
      return chargerService.changeAvailability(id, type, connectorId);
    },
    onMutate: async ({ id, type }) => {
      // Cancel outgoing refetches so they don't overwrite optimistic update
      await queryClient.cancelQueries({ queryKey: chargerKeys.all });

      // Snapshot previous value for rollback
      const previousChargers = queryClient.getQueriesData({
        queryKey: chargerKeys.lists(),
      });

      // Optimistically update charger status. Reverted below for any non-Accepted
      // OCPP response so the UI never lies about a Scheduled or Rejected outcome.
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
    onSuccess: (data, variables, context) => {
      // Defensive: a future contract change where the backend returns
      // success=false with a 200 must not silently process as Accepted.
      if (!data?.success) {
        rollback(context);
        toast.error("Charger refused the change");
        return;
      }

      const displayStatus = variables.type === "Inoperative" ? "unavailable" : "available";
      const ocppResponse = data.ocpp_response;

      switch (ocppResponse) {
        case "Accepted":
          // Optimistic update is correct; just notify.
          toast.success(`Charger marked as ${displayStatus}`);
          break;
        case "Scheduled":
          // Change deferred until the current session ends. Revert the
          // optimistic flip so the table reflects the real (still-current)
          // state; the StatusNotification on session-end will refresh it.
          rollback(context);
          toast.info(
            `Change scheduled — will apply when the current session ends`
          );
          break;
        case "Rejected":
          rollback(context);
          toast.error("Charger refused the change");
          break;
        default:
          // Defensive: unknown OCPP status. Revert so the UI doesn't fib.
          rollback(context);
          toast(
            `Unexpected charger response${ocppResponse ? `: ${ocppResponse}` : ""}`,
          );
      }
    },
    onError: (err, _variables, context) => {
      rollback(context);

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
      // Immediate invalidation
      queryClient.invalidateQueries({ queryKey: chargerKeys.all });
      queryClient.invalidateQueries({ queryKey: transactionKeys.all });

      // More aggressive refetching for better UX
      const refetchDelays = [1000, 2000, 4000, 8000]; // 1s, 2s, 4s, 8s - faster initial checks
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

// Remote Stop Mutation Hook (by string ID - for user-facing pages)
export function useRemoteStopByStringId() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: async ({
      chargePointId,
      reason,
    }: {
      chargePointId: string;
      reason?: string;
    }) => {
      return chargerService.remoteStopByStringId(chargePointId, reason);
    },
    onSuccess: () => {
      // Immediate invalidation
      queryClient.invalidateQueries({ queryKey: chargerKeys.all });
      queryClient.invalidateQueries({ queryKey: transactionKeys.all });

      // More aggressive refetching for better UX
      const refetchDelays = [1000, 2000, 4000, 8000]; // 1s, 2s, 4s, 8s - faster initial checks
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

// Reset Charger Mutation Hook
export function useResetCharger() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: ({ chargerId, type }: { chargerId: number; type: 'Hard' | 'Soft' }) =>
      chargerService.reset(chargerId, type),
    onSuccess: (_, variables) => {
      queryClient.invalidateQueries({ queryKey: chargerKeys.detail(variables.chargerId) });
      queryClient.invalidateQueries({ queryKey: chargerKeys.all });
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

// Create Charger Mutation Hook
export function useCreateCharger() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (data: Parameters<typeof chargerService.create>[0]) =>
      chargerService.create(data),
    onSuccess: () => {
      // Invalidate chargers list to refetch
      queryClient.invalidateQueries({ queryKey: chargerKeys.lists() });
      toast.success("Charger created successfully");
    },
    onError: (err) => {
      const errorMessage = err instanceof Error ? err.message : String(err);
      console.error("Create charger error:", errorMessage);
      toast.error("Failed to create charger");
    },
  });
}

// Update Charger Mutation Hook
export function useUpdateCharger() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: ({ id, data }: { id: number; data: Parameters<typeof chargerService.update>[1] }) =>
      chargerService.update(id, data),
    onSuccess: (_, variables) => {
      // Invalidate chargers list and detail to refetch
      queryClient.invalidateQueries({ queryKey: chargerKeys.lists() });
      queryClient.invalidateQueries({ queryKey: chargerKeys.detail(variables.id) });
      toast.success("Charger updated successfully");
    },
    onError: (err) => {
      const errorMessage = err instanceof Error ? err.message : String(err);
      console.error("Update charger error:", errorMessage);
      if (errorMessage.includes("External charger ID already exists")) {
        toast.error("External charger ID already exists");
      } else {
        toast.error("Failed to update charger");
      }
    },
  });
}

// Signal Quality Query Hooks

/**
 * Hook to fetch signal quality history for a charger
 * @param chargerId - The charger ID
 * @param hours - Number of hours of history to fetch (default: 24)
 */
export function useSignalQuality(chargerId: number, hours: number = 24) {
  const { isAuthReady } = useAuth();

  return useQuery({
    queryKey: chargerKeys.signalQuality(chargerId, hours),
    queryFn: () => signalQualityService.getSignalQuality(chargerId, { hours, limit: 100 }),
    enabled: isAuthReady && !!chargerId, // Wait for auth and valid id
    staleTime: 1000 * 10, // 10 seconds
    refetchInterval: 1000 * 10, // Auto-refresh every 10 seconds
  });
}

/**
 * Hook to fetch the latest signal quality reading for a charger
 * @param chargerId - The charger ID
 */
export function useLatestSignalQuality(chargerId: number) {
  const { isAuthReady } = useAuth();

  return useQuery({
    queryKey: chargerKeys.signalQualityLatest(chargerId),
    queryFn: () => signalQualityService.getLatestSignalQuality(chargerId),
    enabled: isAuthReady && !!chargerId, // Wait for auth and valid id
    staleTime: 1000 * 5, // 5 seconds
    refetchInterval: 1000 * 5, // Auto-refresh every 5 seconds for real-time monitoring
  });
}

// Charger Error Query Hooks

/**
 * Hook to fetch error history for a charger
 * @param chargerId - The charger ID
 * @param params - Query parameters (hours, include_resolved, limit)
 */
export function useChargerErrors(
  chargerId: number,
  params: { hours?: number; include_resolved?: boolean; limit?: number } = {}
) {
  const { isAuthReady } = useAuth();
  const queryParams = { hours: 168, include_resolved: true, limit: 20, ...params };

  return useQuery({
    queryKey: chargerKeys.errors(chargerId, queryParams),
    queryFn: () => chargerErrorService.getErrors(chargerId, queryParams),
    enabled: isAuthReady && !!chargerId,
    staleTime: 1000 * 30, // 30 seconds - errors don't change as frequently
    refetchInterval: 1000 * 30, // Auto-refresh every 30 seconds
  });
}