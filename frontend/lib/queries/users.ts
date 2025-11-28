"use client";

import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/api-client";
import {
  UserListResponse,
  UserDetail,
  UserTransactionSummary,
  UserTransactionsResponse,
  UserWalletTransactionsResponse
} from "@/types/api";
import { useAuth } from "@/contexts/AuthContext";

// Query Keys
const userKeys = {
  all: ["users"] as const,
  lists: () => [...userKeys.all, "list"] as const,
  list: (filters: Record<string, unknown>) => [...userKeys.lists(), { filters }] as const,
  details: () => [...userKeys.all, "detail"] as const,
  detail: (id: number) => [...userKeys.details(), id] as const,
  transactions: (id: number) => [...userKeys.all, "transactions", id] as const,
  walletTransactions: (id: number) => [...userKeys.all, "wallet-transactions", id] as const,
  summary: (id: number) => [...userKeys.all, "summary", id] as const,
};

// List Users Query
export function useUsers({
  page = 1,
  limit = 20,
  is_active,
  search,
}: {
  page?: number;
  limit?: number;
  is_active?: boolean;
  search?: string;
} = {}) {
  const { isAuthReady } = useAuth();
  const params = new URLSearchParams();
  params.append("page", page.toString());
  params.append("limit", limit.toString());
  if (is_active !== undefined) params.append("is_active", is_active.toString());
  if (search) params.append("search", search);

  return useQuery({
    queryKey: userKeys.list({ page, limit, is_active, search }),
    queryFn: () => api.get<UserListResponse>(`/api/users?${params.toString()}`),
    staleTime: 30000, // 30 seconds
    enabled: isAuthReady,
  });
}

// Get User Detail Query
export function useUser(userId: number, enabled = true) {
  const { isAuthReady } = useAuth();

  return useQuery({
    queryKey: userKeys.detail(userId),
    queryFn: () => api.get<UserDetail>(`/api/users/${userId}`),
    enabled: enabled && isAuthReady && !!userId,
    staleTime: 60000, // 1 minute
  });
}

// User Transaction Summary Query
export function useUserTransactionSummary(userId: number, enabled = true) {
  const { isAuthReady } = useAuth();

  return useQuery({
    queryKey: userKeys.summary(userId),
    queryFn: () => api.get<UserTransactionSummary>(`/api/users/${userId}/transactions-summary`),
    enabled: enabled && isAuthReady && !!userId,
    staleTime: 60000, // 1 minute
  });
}

// User Charging Transactions Query
export function useUserTransactions({
  userId,
  page = 1,
  limit = 20,
  enabled = true
}: {
  userId: number;
  page?: number;
  limit?: number;
  enabled?: boolean;
}) {
  const { isAuthReady } = useAuth();
  const params = new URLSearchParams();
  params.append("page", page.toString());
  params.append("limit", limit.toString());

  return useQuery({
    queryKey: [...userKeys.transactions(userId), { page, limit }],
    queryFn: () => api.get<UserTransactionsResponse>(`/api/users/${userId}/transactions?${params.toString()}`),
    enabled: enabled && isAuthReady && !!userId,
    staleTime: 60000, // 1 minute
  });
}

// User Wallet Transactions Query
export function useUserWalletTransactions({
  userId,
  page = 1,
  limit = 20,
  enabled = true
}: {
  userId: number;
  page?: number;
  limit?: number;
  enabled?: boolean;
}) {
  const { isAuthReady } = useAuth();
  const params = new URLSearchParams();
  params.append("page", page.toString());
  params.append("limit", limit.toString());

  return useQuery({
    queryKey: [...userKeys.walletTransactions(userId), { page, limit }],
    queryFn: () => api.get<UserWalletTransactionsResponse>(`/api/users/${userId}/wallet-transactions?${params.toString()}`),
    enabled: enabled && isAuthReady && !!userId,
    staleTime: 60000, // 1 minute
  });
}

// Soft Delete User Mutation
export function useDeactivateUser() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (userId: number) => api.put(`/api/users/${userId}/deactivate`),
    onSuccess: () => {
      // Invalidate and refetch users list
      queryClient.invalidateQueries({ queryKey: userKeys.lists() });
      queryClient.invalidateQueries({ queryKey: userKeys.details() });
    },
  });
}

// Reactivate User Mutation
export function useReactivateUser() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (userId: number) => api.put(`/api/users/${userId}/reactivate`),
    onSuccess: () => {
      // Invalidate and refetch users list
      queryClient.invalidateQueries({ queryKey: userKeys.lists() });
      queryClient.invalidateQueries({ queryKey: userKeys.details() });
    },
  });
}