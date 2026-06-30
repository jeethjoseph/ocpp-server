import { useQuery, type Query } from "@tanstack/react-query";
import { transactionService } from "@/lib/api-services";
import { isTerminalTransactionStatus } from "@/types/api";
import type { TransactionDetail, TransactionListResponse } from "@/types/api";
import { useAuth } from "@/contexts/AuthContext";

const DETAIL_POLL_MS = 1000 * 5;
const LIST_POLL_MS = 1000 * 10;

// Stop polling a settled session — its server-side state won't change again.
function detailRefetchInterval(
  query: Query<TransactionDetail, Error>
): number | false {
  const status = query.state.data?.transaction?.transaction_status;
  return isTerminalTransactionStatus(status) ? false : DETAIL_POLL_MS;
}

// Gate the list poll: once every loaded row is settled there are no live
// sessions to track, so stop refetching until a filter change re-runs the query.
function listRefetchInterval(
  query: Query<TransactionListResponse, Error>
): number | false {
  const rows = query.state.data?.data;
  if (!rows || rows.length === 0) return LIST_POLL_MS;
  const allTerminal = rows.every((r) =>
    isTerminalTransactionStatus(r.transaction_status)
  );
  return allTerminal ? false : LIST_POLL_MS;
}

// Query Keys
export const transactionKeys = {
  all: ["transactions"] as const,
  lists: () => [...transactionKeys.all, "list"] as const,
  list: (params: Record<string, unknown>) => [...transactionKeys.lists(), params] as const,
  details: () => [...transactionKeys.all, "detail"] as const,
  detail: (id: number) => [...transactionKeys.details(), id] as const,
  meterValues: (id: number) => [...transactionKeys.detail(id), "meter-values"] as const,
};

// Admin Transactions List Query Hook (Admin-only)
export interface AdminTransactionsParams {
  page?: number;
  limit?: number;
  status?: string;
  user_id?: number;
  charger_id?: number;
  start_date?: string;
  end_date?: string;
  sort?: string;
  funding_source?: string[];
  payment_status?: string;
}

export function useAdminTransactions(params: AdminTransactionsParams) {
  const { isAuthReady } = useAuth();

  return useQuery({
    queryKey: transactionKeys.list(params as Record<string, unknown>),
    queryFn: () => transactionService.getAll(params),
    enabled: isAuthReady,
    staleTime: 1000 * 5, // 5 seconds
    // Poll while any loaded session is live; stop once all rows are terminal.
    refetchInterval: listRefetchInterval,
  });
}

// Transaction Detail Query Hook (User-accessible)
export function useTransaction(transactionId: number) {
  const { isAuthReady } = useAuth();

  return useQuery({
    queryKey: transactionKeys.detail(transactionId),
    queryFn: () => transactionService.getUserTransaction(transactionId),
    enabled: isAuthReady && !!transactionId,
    staleTime: 1000 * 5, // 5 seconds
    // Stop polling once the session is settled (terminal status).
    refetchInterval: detailRefetchInterval,
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
    // Stop polling once the session is settled (terminal status).
    refetchInterval: detailRefetchInterval,
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