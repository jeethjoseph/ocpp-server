import { api } from "./api-client";
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
  MeterValue,
  Transaction,
  TransactionDetail,
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
    return api.get<StationListResponse>(
      `/api/admin/stations${query ? `?${query}` : ""}`
    );
  },

  getById: (id: number) =>
    api.get<{
      station: Station;
      chargers: Array<{
        id: number;
        charge_point_string_id: string;
        name: string;
        latest_status: string;
      }>;
    }>(`/api/admin/stations/${id}`),

  create: (data: StationCreate) =>
    api.post<ApiResponse<{ station: Station }>>("/api/admin/stations", data),

  update: (id: number, data: StationUpdate) =>
    api.put<ApiResponse<{ station: Station }>>(`/api/admin/stations/${id}`, data),

  delete: (id: number) =>
    api.delete<ApiResponse>(`/api/admin/stations/${id}`),
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
    return api.get<ChargerListResponse>(
      `/api/admin/chargers${query ? `?${query}` : ""}`
    );
  },

  getById: (id: number) =>
    api.get<ChargerDetail>(`/api/admin/chargers/${id}`),

  create: (data: ChargerCreate) =>
    api.post<ApiResponse<{ charger: Charger; ocpp_url: string }>>(
      "/api/admin/chargers",
      data
    ),

  update: (id: number, data: ChargerUpdate) =>
    api.put<ApiResponse<{ charger: Charger }>>(`/api/admin/chargers/${id}`, data),

  delete: (id: number) =>
    api.delete<ApiResponse>(`/api/admin/chargers/${id}`),

  changeAvailability: (
    id: number,
    type: "Inoperative" | "Operative",
    connectorId: number
  ) =>
    api.post<ApiResponse>(
      `/api/admin/chargers/${id}/change-availability?type=${type}&connector_id=${connectorId}`
    ),

  remoteStop: (id: number, reason?: string) =>
    api.post<ApiResponse>(
      `/api/admin/chargers/${id}/remote-stop`,
      reason ? { reason } : undefined
    ),

  remoteStart: (id: number, connectorId: number = 1, idTag: string = "admin") =>
    api.post<ApiResponse>(
      `/api/admin/chargers/${id}/remote-start`,
      { connector_id: connectorId, id_tag: idTag }
    ),
};

export const transactionService = {
  getAll: (params?: {
    page?: number;
    limit?: number;
    status?: string;
    user_id?: number;
    charger_id?: number;
    start_date?: string;
    end_date?: string;
    sort?: string;
  }) => {
    const searchParams = new URLSearchParams();
    if (params?.page) searchParams.set("page", params.page.toString());
    if (params?.limit) searchParams.set("limit", params.limit.toString());
    if (params?.status) searchParams.set("status", params.status);
    if (params?.user_id) searchParams.set("user_id", params.user_id.toString());
    if (params?.charger_id) searchParams.set("charger_id", params.charger_id.toString());
    if (params?.start_date) searchParams.set("start_date", params.start_date);
    if (params?.end_date) searchParams.set("end_date", params.end_date);
    if (params?.sort) searchParams.set("sort", params.sort);
    
    const query = searchParams.toString();
    return api.get<{
      data: unknown[];
      total: number;
      page: number;
      limit: number;
      summary: Record<string, unknown>;
    }>(
      `/api/admin/transactions${query ? `?${query}` : ""}`
    );
  },

  getById: (id: number) =>
    api.get<TransactionDetail>(`/api/admin/transactions/${id}`),

  getMeterValues: (id: number) =>
    api.get<{
      meter_values: MeterValue[];
      energy_chart_data: Record<string, unknown>;
    }>(`/api/admin/transactions/${id}/meter-values`),

  forceStop: (id: number, reason: string) =>
    api.post<ApiResponse>(
      `/api/admin/transactions/${id}/stop`,
      { reason }
    ),
};