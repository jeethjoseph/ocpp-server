import { apiClient } from "./api";
import {
  Station,
  StationCreate,
  StationUpdate,
  StationListResponse,
  Charger,
  ChargerCreate,
  ChargerUpdate,
  ChargerListResponse,
  ChargerDetail,
  ApiResponse,
} from "@/types/api";

export const stationService = {
  getAll: (params?: {
    page?: number;
    limit?: number;
    search?: string;
    sort?: string;
  }) => {
    const searchParams = new URLSearchParams();
    if (params?.page) searchParams.set("page", params.page.toString());
    if (params?.limit) searchParams.set("limit", params.limit.toString());
    if (params?.search) searchParams.set("search", params.search);
    if (params?.sort) searchParams.set("sort", params.sort);
    
    const query = searchParams.toString();
    return apiClient.get<StationListResponse>(
      `/api/admin/stations${query ? `?${query}` : ""}`
    );
  },

  getById: (id: number) =>
    apiClient.get<{
      station: Station;
      chargers: Array<{
        id: number;
        charge_point_string_id: string;
        name: string;
        latest_status: string;
      }>;
    }>(`/api/admin/stations/${id}`),

  create: (data: StationCreate) =>
    apiClient.post<ApiResponse<{ station: Station }>>("/api/admin/stations", data),

  update: (id: number, data: StationUpdate) =>
    apiClient.put<ApiResponse<{ station: Station }>>(`/api/admin/stations/${id}`, data),

  delete: (id: number) =>
    apiClient.delete<ApiResponse>(`/api/admin/stations/${id}`),
};

export const chargerService = {
  getAll: (params?: {
    page?: number;
    limit?: number;
    status?: string;
    station_id?: number;
    search?: string;
    sort?: string;
  }) => {
    const searchParams = new URLSearchParams();
    if (params?.page) searchParams.set("page", params.page.toString());
    if (params?.limit) searchParams.set("limit", params.limit.toString());
    if (params?.status) searchParams.set("status", params.status);
    if (params?.station_id) searchParams.set("station_id", params.station_id.toString());
    if (params?.search) searchParams.set("search", params.search);
    if (params?.sort) searchParams.set("sort", params.sort);
    
    const query = searchParams.toString();
    return apiClient.get<ChargerListResponse>(
      `/api/admin/chargers${query ? `?${query}` : ""}`
    );
  },

  getById: (id: number) =>
    apiClient.get<ChargerDetail>(`/api/admin/chargers/${id}`),

  create: (data: ChargerCreate) =>
    apiClient.post<ApiResponse<{ charger: Charger; ocpp_url: string }>>(
      "/api/admin/chargers",
      data
    ),

  update: (id: number, data: ChargerUpdate) =>
    apiClient.put<ApiResponse<{ charger: Charger }>>(`/api/admin/chargers/${id}`, data),

  delete: (id: number) =>
    apiClient.delete<ApiResponse>(`/api/admin/chargers/${id}`),

  changeAvailability: (
    id: number,
    type: "Inoperative" | "Operative",
    connectorId: number
  ) =>
    apiClient.post<ApiResponse>(
      `/api/admin/chargers/${id}/change-availability?type=${type}&connector_id=${connectorId}`
    ),

  remoteStop: (id: number, reason?: string) =>
    apiClient.post<ApiResponse>(
      `/api/admin/chargers/${id}/remote-stop`,
      reason ? { reason } : undefined
    ),
};