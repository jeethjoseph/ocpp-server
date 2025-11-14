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
    api.put<ApiResponse<{ station: Station }>>(
      `/api/admin/stations/${id}`,
      data
    ),

  delete: (id: number) => api.delete<ApiResponse>(`/api/admin/stations/${id}`),
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
    if (params?.station_id)
      searchParams.set("station_id", params.station_id.toString());
    if (params?.search) searchParams.set("search", params.search);
    if (params?.sort) searchParams.set("sort", params.sort);

    const query = searchParams.toString();
    return api.get<ChargerListResponse>(
      `/api/admin/chargers${query ? `?${query}` : ""}`
    );
  },

  getById: (id: number) => api.get<ChargerDetail>(`/api/admin/chargers/${id}`),

  create: (data: ChargerCreate) =>
    api.post<ApiResponse<{ charger: Charger; ocpp_url: string }>>(
      "/api/admin/chargers",
      data
    ),

  update: (id: number, data: ChargerUpdate) =>
    api.put<ApiResponse<{ charger: Charger }>>(
      `/api/admin/chargers/${id}`,
      data
    ),

  delete: (id: number) => api.delete<ApiResponse>(`/api/admin/chargers/${id}`),

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
    api.post<ApiResponse>(`/api/admin/chargers/${id}/remote-start`, {
      connector_id: connectorId,
      id_tag: idTag,
    }),
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
    if (params?.charger_id)
      searchParams.set("charger_id", params.charger_id.toString());
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
    }>(`/api/admin/transactions${query ? `?${query}` : ""}`);
  },

  getById: (id: number) =>
    api.get<TransactionDetail>(`/api/admin/transactions/${id}`),

  // User-accessible endpoints (works for both users and admins)
  getUserTransaction: (id: number) =>
    api.get<TransactionDetail>(`/api/users/transaction/${id}`),

  getUserTransactionMeterValues: (id: number) =>
    api.get<{
      meter_values: MeterValue[];
      energy_chart_data: Record<string, unknown>;
    }>(`/api/users/transaction/${id}/meter-values`),

  getMeterValues: (id: number) =>
    api.get<{
      meter_values: MeterValue[];
      energy_chart_data: Record<string, unknown>;
    }>(`/api/admin/transactions/${id}/meter-values`),

  forceStop: (id: number, reason: string) =>
    api.post<ApiResponse>(`/api/admin/transactions/${id}/stop`, { reason }),
};

// Public stations service for user-facing pages
export interface PublicStationResponse {
  id: number;
  name: string;
  latitude: number;
  longitude: number;
  address: string;
  available_chargers: number;
  total_chargers: number;
  connector_types: string[];
  connector_details: Array<{
    connector_type: string;
    max_power_kw: number | null;
    available_count: number;
    total_count: number;
  }>;
  price_per_kwh: number | null;
}

export interface PublicStationsListResponse {
  data: PublicStationResponse[];
  total: number;
}

export const publicStationService = {
  getAll: () => 
    api.get<PublicStationsListResponse>(`/api/public/stations`),
  
  getById: (id: number) => 
    api.get<PublicStationResponse>(`/api/public/stations/${id}`)
};

// Log service
export interface LogEntry {
  id: number;
  created_at: string;
  charge_point_id: string | null;
  message_type: string | null;
  direction: "IN" | "OUT";
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  payload: Record<string, any> | any[] | null;  // Allow both dict and array
  status: string | null;
  correlation_id: string | null;
  timestamp: string;
}

export interface LogsResponse {
  data: LogEntry[];
  total: number;
  limit: number;
  has_more: boolean;
  message?: string;
}

export interface LogSummary {
  charge_point_id: string;
  total_logs: number;
  inbound_logs: number;
  outbound_logs: number;
  oldest_log_date: string | null;
  newest_log_date: string | null;
}

export const logService = {
  getChargerLogs: (
    chargePointId: string,
    params?: {
      start_date?: string;
      end_date?: string;
      limit?: number;
    }
  ) => {
    const searchParams = new URLSearchParams();
    if (params?.start_date) searchParams.set("start_date", params.start_date);
    if (params?.end_date) searchParams.set("end_date", params.end_date);
    if (params?.limit) searchParams.set("limit", params.limit.toString());

    const query = searchParams.toString();
    return api.get<LogsResponse>(
      `/api/admin/logs/charger/${chargePointId}${query ? `?${query}` : ""}`
    );
  },

  getChargerLogSummary: (chargePointId: string) =>
    api.get<LogSummary>(`/api/admin/logs/charger/${chargePointId}/summary`),
};

// Wallet Payment Service
export const walletPaymentService = {
  /**
   * Create a Razorpay order for wallet recharge
   */
  createRechargeOrder: (amount: number) =>
    api.post<import("@/types/api").CreateRechargeResponse>(
      "/api/wallet/create-recharge",
      { amount }
    ),

  /**
   * Verify payment after Razorpay checkout completion
   */
  verifyPayment: (paymentDetails: import("@/types/api").VerifyPaymentRequest) =>
    api.post<import("@/types/api").VerifyPaymentResponse>(
      "/api/wallet/verify-payment",
      paymentDetails
    ),

  /**
   * Get payment status by transaction ID
   */
  getPaymentStatus: (transactionId: number) =>
    api.get<import("@/types/api").PaymentStatusResponse>(
      `/api/wallet/payment-status/${transactionId}`
    ),

  /**
   * Get user's recharge history
   */
  getRechargeHistory: () =>
    api.get<import("@/types/api").RechargeHistoryResponse>(
      "/api/wallet/recharge-history"
    ),
};

/**
 * Firmware Update Service
 * Handles OTA firmware updates for chargers
 */
export const firmwareService = {
  /**
   * Upload a new firmware file
   * Note: Uses custom fetch to handle FormData with auth token
   */
  uploadFirmware: async (file: File, version: string, getToken: () => Promise<string | null>, description?: string) => {
    const formData = new FormData();
    formData.append('file', file);
    formData.append('version', version);
    if (description) {
      formData.append('description', description);
    }

    const token = await getToken();
    if (!token) {
      throw new Error('Authentication token not available');
    }

    const response = await fetch(`${process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000'}/api/admin/firmware/upload`, {
      method: 'POST',
      headers: {
        'Authorization': `Bearer ${token}`,
      },
      body: formData,
    });

    if (!response.ok) {
      const error = await response.json();
      throw new Error(error.detail || 'Failed to upload firmware');
    }

    return response.json();
  },

  /**
   * Get list of all firmware files
   */
  getFirmwareFiles: (params?: { page?: number; limit?: number; is_active?: boolean }) => {
    const searchParams = new URLSearchParams();
    if (params?.page) searchParams.set("page", params.page.toString());
    if (params?.limit) searchParams.set("limit", params.limit.toString());
    if (params?.is_active !== undefined) searchParams.set("is_active", params.is_active.toString());

    const query = searchParams.toString();
    return api.get<import("@/types/api").FirmwareFileListResponse>(
      `/api/admin/firmware${query ? `?${query}` : ""}`
    );
  },

  /**
   * Delete (soft delete) a firmware file
   */
  deleteFirmwareFile: (firmwareId: number) =>
    api.delete(`/api/admin/firmware/${firmwareId}`),

  /**
   * Trigger firmware update for a single charger
   */
  triggerUpdate: (chargerId: number, firmwareFileId: number) =>
    api.post<import("@/types/api").FirmwareUpdate>(
      `/api/admin/firmware/chargers/${chargerId}/update`,
      { firmware_file_id: firmwareFileId }
    ),

  /**
   * Trigger bulk firmware update for multiple chargers
   */
  bulkUpdate: (request: import("@/types/api").BulkFirmwareUpdateRequest) =>
    api.post<import("@/types/api").BulkUpdateResult>(
      "/api/admin/firmware/bulk-update",
      request
    ),

  /**
   * Get firmware update history for a charger
   */
  getFirmwareHistory: (chargerId: number, params?: { page?: number; limit?: number }) => {
    const searchParams = new URLSearchParams();
    if (params?.page) searchParams.set("page", params.page.toString());
    if (params?.limit) searchParams.set("limit", params.limit.toString());

    const query = searchParams.toString();
    return api.get<import("@/types/api").FirmwareHistoryResponse>(
      `/api/admin/firmware/chargers/${chargerId}/history${query ? `?${query}` : ""}`
    );
  },

  /**
   * Get dashboard status of all firmware updates
   */
  getUpdateStatus: () =>
    api.get<import("@/types/api").UpdateStatusDashboard>(
      "/api/admin/firmware/updates/status"
    ),
};
