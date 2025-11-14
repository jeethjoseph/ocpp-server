/**
 * TanStack Query hooks for Firmware Update operations
 */

import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { firmwareService } from "@/lib/api-services";
import { toast } from "sonner";

// Query keys for cache management
export const firmwareKeys = {
  all: ["firmware"] as const,
  lists: () => [...firmwareKeys.all, "list"] as const,
  list: (params: Record<string, unknown>) => [...firmwareKeys.lists(), params] as const,
  details: () => [...firmwareKeys.all, "detail"] as const,
  detail: (id: number) => [...firmwareKeys.details(), id] as const,
  history: (chargerId: number, params?: Record<string, unknown>) =>
    [...firmwareKeys.all, "history", chargerId, params] as const,
  status: () => [...firmwareKeys.all, "status"] as const,
};

/**
 * Get list of firmware files
 */
export function useFirmwareFiles(params?: { page?: number; limit?: number; is_active?: boolean }) {
  return useQuery({
    queryKey: firmwareKeys.list(params || {}),
    queryFn: () => firmwareService.getFirmwareFiles(params),
    staleTime: 1000 * 30, // 30 seconds
  });
}

/**
 * Upload firmware file mutation
 */
export function useUploadFirmware() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: ({ file, version, getToken, description }: {
      file: File;
      version: string;
      getToken: () => Promise<string | null>;
      description?: string;
    }) => firmwareService.uploadFirmware(file, version, getToken, description),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: firmwareKeys.lists() });
      toast.success("Firmware uploaded successfully");
    },
    onError: (err) => {
      const errorMessage = err instanceof Error ? err.message : String(err);
      console.error("Upload firmware error:", errorMessage);
      toast.error(`Failed to upload firmware: ${errorMessage}`);
    },
  });
}

/**
 * Delete firmware file mutation
 */
export function useDeleteFirmware() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (firmwareId: number) => firmwareService.deleteFirmwareFile(firmwareId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: firmwareKeys.lists() });
      toast.success("Firmware deleted successfully");
    },
    onError: (err) => {
      const errorMessage = err instanceof Error ? err.message : String(err);
      console.error("Delete firmware error:", errorMessage);
      toast.error(`Failed to delete firmware: ${errorMessage}`);
    },
  });
}

/**
 * Trigger firmware update for a single charger
 */
export function useTriggerUpdate() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: ({ chargerId, firmwareFileId }: { chargerId: number; firmwareFileId: number }) =>
      firmwareService.triggerUpdate(chargerId, firmwareFileId),
    onSuccess: (_, variables) => {
      queryClient.invalidateQueries({ queryKey: firmwareKeys.status() });
      queryClient.invalidateQueries({ queryKey: firmwareKeys.history(variables.chargerId) });
      toast.success("Firmware update initiated successfully");
    },
    onError: (err) => {
      const errorMessage = err instanceof Error ? err.message : String(err);
      console.error("Trigger update error:", errorMessage);
      toast.error(`Failed to trigger update: ${errorMessage}`);
    },
  });
}

/**
 * Trigger bulk firmware update
 */
export function useBulkUpdate() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (request: import("@/types/api").BulkFirmwareUpdateRequest) =>
      firmwareService.bulkUpdate(request),
    onSuccess: (result) => {
      queryClient.invalidateQueries({ queryKey: firmwareKeys.status() });
      const successCount = result.success.length;
      const failedCount = result.failed.length;

      if (failedCount === 0) {
        toast.success(`Bulk update initiated for ${successCount} charger(s)`);
      } else {
        toast.warning(`Updated ${successCount} charger(s), ${failedCount} failed`);
      }
    },
    onError: (err) => {
      const errorMessage = err instanceof Error ? err.message : String(err);
      console.error("Bulk update error:", errorMessage);
      toast.error(`Failed to trigger bulk update: ${errorMessage}`);
    },
  });
}

/**
 * Get firmware update history for a charger
 */
export function useFirmwareHistory(chargerId: number, params?: { page?: number; limit?: number }) {
  return useQuery({
    queryKey: firmwareKeys.history(chargerId, params),
    queryFn: () => firmwareService.getFirmwareHistory(chargerId, params),
    staleTime: 1000 * 10, // 10 seconds
    enabled: !!chargerId,
  });
}

/**
 * Get dashboard status of all firmware updates
 * Auto-refreshes every 10 seconds
 */
export function useUpdateStatus() {
  return useQuery({
    queryKey: firmwareKeys.status(),
    queryFn: () => firmwareService.getUpdateStatus(),
    staleTime: 1000 * 5,  // 5 seconds
    refetchInterval: 1000 * 10,  // Refresh every 10 seconds for real-time monitoring
  });
}
