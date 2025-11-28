import { useQuery } from "@tanstack/react-query";
import { transactionService } from "@/lib/api-services";
import { useAuth } from "@/contexts/AuthContext";

// Query Keys
export const transactionKeys = {
  all: ["transactions"] as const,
  lists: () => [...transactionKeys.all, "list"] as const,
  list: (params: Record<string, unknown>) => [...transactionKeys.lists(), params] as const,
  details: () => [...transactionKeys.all, "detail"] as const,
  detail: (id: number) => [...transactionKeys.details(), id] as const,
  meterValues: (id: number) => [...transactionKeys.detail(id), "meter-values"] as const,
};

// Transaction Detail Query Hook (User-accessible)
export function useTransaction(transactionId: number) {
  const { isAuthReady } = useAuth();

  return useQuery({
    queryKey: transactionKeys.detail(transactionId),
    queryFn: () => transactionService.getUserTransaction(transactionId),
    enabled: isAuthReady && !!transactionId,
    staleTime: 1000 * 5, // 5 seconds
    refetchInterval: 1000 * 5, // Auto-refresh every 5 seconds for billing updates
  });
}

// Admin Transaction Detail Query Hook (Admin-only)
export function useAdminTransaction(transactionId: number) {
  const { isAuthReady } = useAuth();

  return useQuery({
    queryKey: [...transactionKeys.detail(transactionId), 'admin'],
    queryFn: () => transactionService.getById(transactionId),
    enabled: isAuthReady && !!transactionId,
    staleTime: 1000 * 5, // 5 seconds
    refetchInterval: 1000 * 5, // Auto-refresh every 5 seconds for billing updates
  });
}

// Transaction Meter Values Query Hook (User-accessible)
export function useTransactionMeterValues(transactionId: number) {
  const { isAuthReady } = useAuth();

  return useQuery({
    queryKey: transactionKeys.meterValues(transactionId),
    queryFn: () => transactionService.getUserTransactionMeterValues(transactionId),
    enabled: isAuthReady && !!transactionId,
    staleTime: 1000 * 5, // 5 seconds
    refetchInterval: 1000 * 10, // Auto-refresh every 10 seconds
  });
}

// Admin Transaction Meter Values Query Hook (Admin-only)
export function useAdminTransactionMeterValues(transactionId: number) {
  const { isAuthReady } = useAuth();

  return useQuery({
    queryKey: [...transactionKeys.meterValues(transactionId), 'admin'],
    queryFn: () => transactionService.getMeterValues(transactionId),
    enabled: isAuthReady && !!transactionId,
    staleTime: 1000 * 5, // 5 seconds
    refetchInterval: 1000 * 10, // Auto-refresh every 10 seconds
  });
}