import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { stationService } from "@/lib/api-services";
import { StationListResponse, StationCreate, StationUpdate } from "@/types/api";
import { toast } from "sonner";
import { useAuth } from "@/contexts/AuthContext";

// Query Keys
export const stationKeys = {
  all: ["stations"] as const,
  lists: () => [...stationKeys.all, "list"] as const,
  list: (params: Record<string, unknown>) => [...stationKeys.lists(), params] as const,
  details: () => [...stationKeys.all, "detail"] as const,
  detail: (id: number) => [...stationKeys.details(), id] as const,
};

// Stations Query Hook
export function useStations(params: {
  page?: number;
  limit?: number;
  search?: string;
  sort?: string;
} = {}) {
  const { isAuthReady } = useAuth();

  return useQuery({
    queryKey: stationKeys.list(params),
    queryFn: () => stationService.getAll(params),
    staleTime: 1000 * 60 * 2, // 2 minutes - stations don't change often
    refetchOnWindowFocus: true, // Refresh when user returns to the page
    enabled: isAuthReady,
  });
}

// Individual Station Query Hook
export function useStation(id: number) {
  const { isAuthReady } = useAuth();

  return useQuery({
    queryKey: stationKeys.detail(id),
    queryFn: () => stationService.getById(id),
    enabled: isAuthReady && !!id,
  });
}

// Create Station Mutation Hook
export function useCreateStation() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (data: StationCreate) => stationService.create(data),
    onSuccess: () => {
      // Invalidate and refetch stations list
      queryClient.invalidateQueries({ queryKey: stationKeys.lists() });
      toast.success("Station created successfully");
    },
    onError: (err) => {
      const errorMessage = err instanceof Error ? err.message : String(err);
      console.error("Create station error:", errorMessage);
      toast.error("Failed to create station");
    },
  });
}

// Update Station Mutation Hook
export function useUpdateStation() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: ({ id, data }: { id: number; data: StationUpdate }) =>
      stationService.update(id, data),
    onSuccess: (_, { id }) => {
      // Invalidate both the specific station and the lists
      queryClient.invalidateQueries({ queryKey: stationKeys.detail(id) });
      queryClient.invalidateQueries({ queryKey: stationKeys.lists() });
      toast.success("Station updated successfully");
    },
    onError: (err) => {
      const errorMessage = err instanceof Error ? err.message : String(err);
      console.error("Update station error:", errorMessage);
      toast.error("Failed to update station");
    },
  });
}

// Delete Station Mutation Hook
export function useDeleteStation() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (id: number) => stationService.delete(id),
    onMutate: async (id) => {
      // Cancel outgoing refetches
      await queryClient.cancelQueries({ queryKey: stationKeys.all });

      // Snapshot previous value for rollback
      const previousStations = queryClient.getQueriesData({
        queryKey: stationKeys.lists(),
      });

      // Optimistically remove station from all lists
      queryClient.setQueriesData<StationListResponse>(
        { queryKey: stationKeys.lists() },
        (old) => {
          if (!old) return old;
          return {
            ...old,
            data: old.data.filter((station) => station.id !== id),
            total: old.total - 1,
          };
        }
      );

      return { previousStations };
    },
    onSuccess: () => {
      toast.success("Station deleted successfully");
    },
    onError: (err, variables, context) => {
      // Rollback optimistic update on error
      if (context?.previousStations) {
        context.previousStations.forEach(([queryKey, data]) => {
          queryClient.setQueryData(queryKey, data);
        });
      }
      const errorMessage = err instanceof Error ? err.message : String(err);
      console.error("Delete station error:", errorMessage);
      toast.error("Failed to delete station");
    },
    onSettled: () => {
      // Refetch to get actual server state
      queryClient.invalidateQueries({ queryKey: stationKeys.all });
    },
  });
}