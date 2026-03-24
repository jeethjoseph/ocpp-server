import { useQuery } from "@tanstack/react-query";
import { publicQRTransactionService, QRTransactionListResponse } from "../api-services";

export const publicQRTransactionKeys = {
  all: ["public-qr-transactions"] as const,
  list: (params: Record<string, unknown>) =>
    [...publicQRTransactionKeys.all, "list", params] as const,
};

export function usePublicQRTransactions(params: {
  token: string;
  page?: number;
  limit?: number;
  status?: string;
}) {
  return useQuery<QRTransactionListResponse, Error>({
    queryKey: publicQRTransactionKeys.list(params),
    queryFn: () => publicQRTransactionService.getByToken(params),
    enabled: !!params.token,
    staleTime: 30000,
  });
}
