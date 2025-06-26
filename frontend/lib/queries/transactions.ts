import { useQuery } from "@tanstack/react-query";
import { transactionService } from "@/lib/api-services";

// Query Keys
export const transactionKeys = {
  all: ["transactions"] as const,
  lists: () => [...transactionKeys.all, "list"] as const,
  list: (params: Record<string, unknown>) => [...transactionKeys.lists(), params] as const,
  details: () => [...transactionKeys.all, "detail"] as const,
  detail: (id: number) => [...transactionKeys.details(), id] as const,
  meterValues: (id: number) => [...transactionKeys.detail(id), "meter-values"] as const,
};

// Transaction Detail Query Hook
export function useTransaction(transactionId: number) {
  return useQuery({
    queryKey: transactionKeys.detail(transactionId),
    queryFn: () => transactionService.getById(transactionId),
    enabled: !!transactionId,
    staleTime: 1000 * 5, // 5 seconds
  });
}

// Transaction Meter Values Query Hook
export function useTransactionMeterValues(transactionId: number) {
  return useQuery({
    queryKey: transactionKeys.meterValues(transactionId),
    queryFn: () => transactionService.getMeterValues(transactionId),
    enabled: !!transactionId,
    staleTime: 1000 * 5, // 5 seconds
    refetchInterval: 1000 * 10, // Auto-refresh every 10 seconds
  });
}