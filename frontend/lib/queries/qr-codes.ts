import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { qrCodeService } from "@/lib/api-services";
import { toast } from "sonner";
import { useAuth } from "@/contexts/AuthContext";

// Query Keys
export const qrCodeKeys = {
  all: ["qr-codes"] as const,
  lists: () => [...qrCodeKeys.all, "list"] as const,
  list: (params: Record<string, unknown>) =>
    [...qrCodeKeys.lists(), params] as const,
  details: () => [...qrCodeKeys.all, "detail"] as const,
  detail: (id: number) => [...qrCodeKeys.details(), id] as const,
  byCharger: (chargerId: number) =>
    [...qrCodeKeys.all, "charger", chargerId] as const,
  payments: (qrId: number, params: Record<string, unknown>) =>
    [...qrCodeKeys.all, "payments", qrId, params] as const,
};

export function useQRCodes(params: {
  page?: number;
  limit?: number;
  status?: string;
  search?: string;
}) {
  const { isAuthReady } = useAuth();

  return useQuery({
    queryKey: qrCodeKeys.list(params),
    queryFn: () => qrCodeService.getAll(params),
    staleTime: 1000 * 30,
    enabled: isAuthReady,
  });
}

export function useQRCode(id: number) {
  const { isAuthReady } = useAuth();

  return useQuery({
    queryKey: qrCodeKeys.detail(id),
    queryFn: () => qrCodeService.getById(id),
    staleTime: 1000 * 10,
    enabled: isAuthReady && id > 0,
  });
}

export function useQRCodeByCharger(chargerId: number) {
  const { isAuthReady } = useAuth();

  return useQuery({
    queryKey: qrCodeKeys.byCharger(chargerId),
    queryFn: () => qrCodeService.getByChargerId(chargerId),
    staleTime: 1000 * 30,
    enabled: isAuthReady && chargerId > 0,
  });
}

export function useQRPayments(
  qrId: number,
  params: { page?: number; limit?: number; status?: string }
) {
  const { isAuthReady } = useAuth();

  return useQuery({
    queryKey: qrCodeKeys.payments(qrId, params),
    queryFn: () => qrCodeService.getPayments(qrId, params),
    staleTime: 1000 * 10,
    enabled: isAuthReady && qrId > 0,
  });
}

export function useCreateQRCode() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (chargerId: number) => qrCodeService.create(chargerId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: qrCodeKeys.all });
      toast.success("QR code created successfully");
    },
    onError: (error: Error) => {
      toast.error(`Failed to create QR code: ${error.message}`);
    },
  });
}

export function useCloseQRCode() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (id: number) => qrCodeService.close(id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: qrCodeKeys.all });
      toast.success("QR code closed successfully");
    },
    onError: (error: Error) => {
      toast.error(`Failed to close QR code: ${error.message}`);
    },
  });
}
