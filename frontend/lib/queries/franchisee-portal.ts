import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { franchiseePortalService } from "@/lib/api-services";
import { toast } from "sonner";
import { useAuth } from "@/contexts/AuthContext";

export const portalKeys = {
  all: ["franchisee-portal"] as const,
  dashboard: () => [...portalKeys.all, "dashboard"] as const,
  stations: () => [...portalKeys.all, "stations"] as const,
  station: (id: number) => [...portalKeys.all, "station", id] as const,
  charger: (id: number) => [...portalKeys.all, "charger", id] as const,
  transactions: (params: Record<string, unknown>) =>
    [...portalKeys.all, "transactions", params] as const,
  transaction: (id: number) => [...portalKeys.all, "transaction", id] as const,
  settlements: (params: Record<string, unknown>) =>
    [...portalKeys.all, "settlements", params] as const,
  profile: () => [...portalKeys.all, "profile"] as const,
  qrCodes: () => [...portalKeys.all, "qr-codes"] as const,
};

export function usePortalDashboard() {
  const { isAuthReady } = useAuth();
  return useQuery({
    queryKey: portalKeys.dashboard(),
    queryFn: () => franchiseePortalService.getDashboard(),
    staleTime: 1000 * 15,
    enabled: isAuthReady,
  });
}

export function usePortalStations() {
  const { isAuthReady } = useAuth();
  return useQuery({
    queryKey: portalKeys.stations(),
    queryFn: () => franchiseePortalService.getStations(),
    staleTime: 1000 * 60,
    enabled: isAuthReady,
  });
}

export function usePortalStation(id: number) {
  const { isAuthReady } = useAuth();
  return useQuery({
    queryKey: portalKeys.station(id),
    queryFn: () => franchiseePortalService.getStation(id),
    enabled: isAuthReady && !!id,
  });
}

export function usePortalCharger(id: number) {
  const { isAuthReady } = useAuth();
  return useQuery({
    queryKey: portalKeys.charger(id),
    queryFn: () => franchiseePortalService.getCharger(id),
    enabled: isAuthReady && !!id,
  });
}

export function usePortalTransactions(
  params: { page?: number; limit?: number; status?: string } = {}
) {
  const { isAuthReady } = useAuth();
  return useQuery({
    queryKey: portalKeys.transactions(params),
    queryFn: () => franchiseePortalService.getTransactions(params),
    staleTime: 1000 * 15,
    enabled: isAuthReady,
  });
}

export function usePortalTransaction(id: number) {
  const { isAuthReady } = useAuth();
  return useQuery({
    queryKey: portalKeys.transaction(id),
    queryFn: () => franchiseePortalService.getTransaction(id),
    enabled: isAuthReady && !!id,
  });
}

export function usePortalSettlements(
  params: { page?: number; limit?: number; from_date?: string; to_date?: string } = {}
) {
  const { isAuthReady } = useAuth();
  return useQuery({
    queryKey: portalKeys.settlements(params),
    queryFn: () => franchiseePortalService.getSettlements(params),
    staleTime: 1000 * 30,
    enabled: isAuthReady,
  });
}

export function usePortalProfile() {
  const { isAuthReady } = useAuth();
  return useQuery({
    queryKey: portalKeys.profile(),
    queryFn: () => franchiseePortalService.getProfile(),
    staleTime: 1000 * 60 * 5,
    enabled: isAuthReady,
  });
}

export function usePortalQRCodes() {
  const { isAuthReady } = useAuth();
  return useQuery({
    queryKey: portalKeys.qrCodes(),
    queryFn: () => franchiseePortalService.getQRCodes(),
    staleTime: 1000 * 60,
    enabled: isAuthReady,
  });
}

export function useRemoteStop() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (chargerId: number) =>
      franchiseePortalService.remoteStop(chargerId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: portalKeys.all });
      toast.success("Stop command sent");
    },
    onError: (err) => {
      toast.error(err instanceof Error ? err.message : "Stop failed");
    },
  });
}

export function useResetCharger() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (chargerId: number) =>
      franchiseePortalService.resetCharger(chargerId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: portalKeys.all });
      toast.success("Reset command sent");
    },
    onError: (err) => {
      toast.error(err instanceof Error ? err.message : "Reset failed");
    },
  });
}

export function useCreatePortalQRCode() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (chargerId: number) =>
      franchiseePortalService.createQRCode(chargerId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: portalKeys.qrCodes() });
      toast.success("QR code created");
    },
    onError: (err) => {
      toast.error(err instanceof Error ? err.message : "Create failed");
    },
  });
}

export function useRegeneratePortalQRCode() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (qrId: number) =>
      franchiseePortalService.regenerateQRCode(qrId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: portalKeys.qrCodes() });
      toast.success("QR code regenerated — print the new image for the charger");
    },
    onError: (err) => {
      toast.error(err instanceof Error ? err.message : "Regenerate failed");
    },
  });
}

export function useClosePortalQRCode() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (qrId: number) =>
      franchiseePortalService.closeQRCode(qrId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: portalKeys.qrCodes() });
      toast.success("QR code closed");
    },
    onError: (err) => {
      toast.error(err instanceof Error ? err.message : "Close failed");
    },
  });
}
