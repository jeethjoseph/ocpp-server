import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { franchiseeService } from "@/lib/api-services";
import {
  FranchiseeCreate,
  FranchiseeUpdate,
  CommissionUpdate,
  StakeholderCreate,
  StakeholderUpdate,
} from "@/types/api";
import { toast } from "sonner";
import { useAuth } from "@/contexts/AuthContext";

export const franchiseeKeys = {
  all: ["franchisees"] as const,
  lists: () => [...franchiseeKeys.all, "list"] as const,
  list: (params: Record<string, unknown>) =>
    [...franchiseeKeys.lists(), params] as const,
  details: () => [...franchiseeKeys.all, "detail"] as const,
  detail: (id: number) => [...franchiseeKeys.details(), id] as const,
  stations: (id: number) =>
    [...franchiseeKeys.detail(id), "stations"] as const,
  commissionHistory: (id: number) =>
    [...franchiseeKeys.detail(id), "commission-history"] as const,
  stakeholders: (id: number) =>
    [...franchiseeKeys.detail(id), "stakeholders"] as const,
};

export function useFranchisees(
  params: {
    page?: number;
    limit?: number;
    status?: string;
    search?: string;
  } = {}
) {
  const { isAuthReady } = useAuth();

  return useQuery({
    queryKey: franchiseeKeys.list(params),
    queryFn: () => franchiseeService.getAll(params),
    staleTime: 1000 * 30,
    enabled: isAuthReady,
  });
}

export function useFranchisee(id: number) {
  const { isAuthReady } = useAuth();

  return useQuery({
    queryKey: franchiseeKeys.detail(id),
    queryFn: () => franchiseeService.getById(id),
    enabled: isAuthReady && !!id,
  });
}

export function useFranchiseeStations(id: number) {
  const { isAuthReady } = useAuth();

  return useQuery({
    queryKey: franchiseeKeys.stations(id),
    queryFn: () => franchiseeService.getStations(id),
    enabled: isAuthReady && !!id,
  });
}

export function useCommissionHistory(id: number) {
  const { isAuthReady } = useAuth();

  return useQuery({
    queryKey: franchiseeKeys.commissionHistory(id),
    queryFn: () => franchiseeService.getCommissionHistory(id),
    enabled: isAuthReady && !!id,
  });
}

export function useCreateFranchisee() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (data: FranchiseeCreate) => franchiseeService.create(data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: franchiseeKeys.lists() });
      toast.success("Franchisee created successfully");
    },
    onError: (err) => {
      const msg = err instanceof Error ? err.message : String(err);
      toast.error(`Failed to create franchisee: ${msg}`);
    },
  });
}

export function useUpdateFranchisee(id: number) {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (data: FranchiseeUpdate) => franchiseeService.update(id, data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: franchiseeKeys.detail(id) });
      queryClient.invalidateQueries({ queryKey: franchiseeKeys.lists() });
      toast.success("Franchisee updated");
    },
    onError: (err) => {
      const msg = err instanceof Error ? err.message : String(err);
      toast.error(`Update failed: ${msg}`);
    },
  });
}

export function useUpdateCommission(id: number) {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (data: CommissionUpdate) =>
      franchiseeService.updateCommission(id, data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: franchiseeKeys.detail(id) });
      queryClient.invalidateQueries({
        queryKey: franchiseeKeys.commissionHistory(id),
      });
      toast.success("Commission updated");
    },
    onError: (err) => {
      const msg = err instanceof Error ? err.message : String(err);
      toast.error(`Commission update failed: ${msg}`);
    },
  });
}

export function useAssignStations(id: number) {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (stationIds: number[]) =>
      franchiseeService.assignStations(id, stationIds),
    onSuccess: () => {
      queryClient.invalidateQueries({
        queryKey: franchiseeKeys.stations(id),
      });
      queryClient.invalidateQueries({ queryKey: franchiseeKeys.detail(id) });
      toast.success("Stations assigned");
    },
    onError: (err) => {
      const msg = err instanceof Error ? err.message : String(err);
      toast.error(`Assignment failed: ${msg}`);
    },
  });
}

export function useUnassignStation(franchiseeId: number) {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (stationId: number) =>
      franchiseeService.unassignStation(franchiseeId, stationId),
    onSuccess: () => {
      queryClient.invalidateQueries({
        queryKey: franchiseeKeys.stations(franchiseeId),
      });
      queryClient.invalidateQueries({
        queryKey: franchiseeKeys.detail(franchiseeId),
      });
      toast.success("Station unassigned");
    },
    onError: (err) => {
      const msg = err instanceof Error ? err.message : String(err);
      toast.error(`Unassign failed: ${msg}`);
    },
  });
}

export function useResendInvitation() {
  return useMutation({
    mutationFn: (id: number) => franchiseeService.resendInvitation(id),
    onSuccess: (data) => {
      toast.success(`Invitation sent to ${data.email}`);
    },
    onError: (err) => {
      const msg = err instanceof Error ? err.message : String(err);
      toast.error(`Could not resend invitation: ${msg}`);
    },
  });
}

export function useOnboardRazorpay() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (id: number) => franchiseeService.onboardRazorpay(id),
    onSuccess: (_, id) => {
      queryClient.invalidateQueries({ queryKey: franchiseeKeys.detail(id) });
      queryClient.invalidateQueries({ queryKey: franchiseeKeys.lists() });
      toast.success(
        "Razorpay onboarding started. The franchisee will receive an email to complete KYC."
      );
    },
    onError: (err) => {
      const msg = err instanceof Error ? err.message : String(err);
      toast.error(`Razorpay onboarding failed: ${msg}`);
    },
  });
}

export function useFranchiseeStakeholders(id: number) {
  const { isAuthReady } = useAuth();
  return useQuery({
    queryKey: franchiseeKeys.stakeholders(id),
    queryFn: () => franchiseeService.listStakeholders(id),
    enabled: isAuthReady && !!id,
  });
}

export function useCreateStakeholder(id: number) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (body: StakeholderCreate) =>
      franchiseeService.createStakeholder(id, body),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: franchiseeKeys.stakeholders(id) });
      toast.success("Stakeholder added.");
    },
    onError: (err) => {
      const msg = err instanceof Error ? err.message : String(err);
      toast.error(`Could not add stakeholder: ${msg}`);
    },
  });
}

export function useUpdateStakeholder(id: number) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({
      stakeholderId,
      body,
    }: {
      stakeholderId: number;
      body: StakeholderUpdate;
    }) => franchiseeService.updateStakeholder(id, stakeholderId, body),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: franchiseeKeys.stakeholders(id) });
      toast.success("Stakeholder updated.");
    },
    onError: (err) => {
      const msg = err instanceof Error ? err.message : String(err);
      toast.error(`Could not update stakeholder: ${msg}`);
    },
  });
}

export function useSubmitKYC() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (id: number) => franchiseeService.submitKYC(id),
    onSuccess: (res, id) => {
      queryClient.invalidateQueries({ queryKey: franchiseeKeys.detail(id) });
      const reqs = res.requirements?.length ?? 0;
      if (reqs === 0) {
        toast.success(
          `KYC submitted to Razorpay (status: ${res.activation_status}).`
        );
      } else {
        toast.warning(
          `KYC submitted. Razorpay still needs ${reqs} item(s): ${res.requirements
            .map((r) => r.field_reference)
            .join(", ")}`
        );
      }
    },
    onError: (err) => {
      const msg = err instanceof Error ? err.message : String(err);
      toast.error(`KYC submit failed: ${msg}`);
    },
  });
}
