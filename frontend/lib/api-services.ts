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
  SignalQuality,
  SignalQualityListResponse,
  ChargerError,
  ChargerErrorListResponse,
  Franchisee,
  FranchiseeCreate,
  FranchiseeUpdate,
  FranchiseeListResponse,
  FranchiseeStakeholder,
  StakeholderCreate,
  StakeholderUpdate,
  RazorpayApiLog,
  SubmitKYCResponse,
  CommissionUpdate,
  CommissionAuditEntry,
  FranchiseeStation,
  AdminSettlementEntry,
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

  // User-facing endpoint that accepts string IDs (charge_point_string_id)
  getByStringId: (chargePointId: string) =>
    api.get<ChargerDetail>(`/api/users/charger/${chargePointId}`),

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

  // User-facing remote stop that accepts string IDs
  remoteStopByStringId: (chargePointId: string, reason?: string) =>
    api.post<ApiResponse>(
      `/api/users/charger/${chargePointId}/remote-stop`,
      reason ? { reason } : undefined
    ),

  remoteStart: (id: number, connectorId: number = 1, idTag: string = "admin") =>
    api.post<ApiResponse>(`/api/admin/chargers/${id}/remote-start`, {
      connector_id: connectorId,
      id_tag: idTag,
    }),

  // User-facing remote start that accepts string IDs
  remoteStartByStringId: (chargePointId: string, connectorId: number = 1) =>
    api.post<ApiResponse>(`/api/users/charger/${chargePointId}/remote-start`, {
      connector_id: connectorId,
    }),

  reset: (chargerId: number, type: 'Hard' | 'Soft' = 'Hard') =>
    api.post<{ success: boolean; message: string; reset_type: string; charger_id: number }>(
      `/api/admin/chargers/${chargerId}/reset?type=${type}`
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
export interface PublicStationChargerInfo {
  charge_point_string_id: string;
  name: string;
  latest_status: string;
  connectors: Array<{
    connector_type: string;
    max_power_kw: number | null;
  }>;
  tariff_per_kwh: number | null;
  tariff_per_kwh_incl_tax: number | null;
  tariff_gst_percent: number | null;
}

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
  chargers?: PublicStationChargerInfo[];
  price_per_kwh: number | null;
  min_price_per_kwh_incl_tax: number | null;
  max_price_per_kwh_incl_tax: number | null;
  franchisee_name: string | null;
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

// Public station map service (no auth required)
export const publicStationMapService = {
  getAll: () =>
    api.get<PublicStationsListResponse>(`/api/public/stations/map`),
};

// Public QR Transaction History (no auth required)
export interface QRTransactionItem {
  id: number;
  created_at: string;
  amount_paid: string;
  status: string;
  energy_consumed_kwh: number | null;
  energy_cost: string | null;
  gst_amount: string | null;
  platform_fee: string | null;
  razorpay_commission: string | null;
  razorpay_gst: string | null;
  fee_source: string | null;
  refund_amount: string | null;
  charger_name: string | null;
  station_name: string | null;
  franchisee_name: string | null;
  duration_minutes: number | null;
  start_time: string | null;
  end_time: string | null;
  failure_reason: string | null;
}

export interface QRTransactionListResponse {
  data: QRTransactionItem[];
  total: number;
  page: number;
  limit: number;
}

export const publicQRTransactionService = {
  getByVpa: (params: { vpa: string; page?: number; limit?: number; status?: string }) => {
    const searchParams = new URLSearchParams();
    searchParams.set("vpa", params.vpa);
    if (params.page) searchParams.set("page", params.page.toString());
    if (params.limit) searchParams.set("limit", params.limit.toString());
    if (params.status) searchParams.set("status", params.status);
    const query = searchParams.toString();
    return api.get<QRTransactionListResponse>(`/api/public/qr-transactions?${query}`);
  },
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

// Audit Log Service
export interface AuditLogEntry {
  id: number;
  created_at: string;
  actor_type: string;
  actor_id: number | null;
  actor_email: string | null;
  action: string;
  entity_type: string;
  entity_id: string;
  changes: Record<string, unknown> | null;
}

export interface AuditLogListResponse {
  data: AuditLogEntry[];
  total: number;
  page: number;
  limit: number;
}

export const auditLogService = {
  getAuditLogs: (params?: {
    page?: number;
    limit?: number;
    entity_type?: string;
    entity_id?: string;
    action?: string;
    actor_type?: string;
    start_date?: string;
    end_date?: string;
  }) => {
    const searchParams = new URLSearchParams();
    if (params?.page) searchParams.set("page", params.page.toString());
    if (params?.limit) searchParams.set("limit", params.limit.toString());
    if (params?.entity_type) searchParams.set("entity_type", params.entity_type);
    if (params?.entity_id) searchParams.set("entity_id", params.entity_id);
    if (params?.action) searchParams.set("action", params.action);
    if (params?.actor_type) searchParams.set("actor_type", params.actor_type);
    if (params?.start_date) searchParams.set("start_date", params.start_date);
    if (params?.end_date) searchParams.set("end_date", params.end_date);

    const query = searchParams.toString();
    return api.get<AuditLogListResponse>(
      `/api/admin/logs/audit${query ? `?${query}` : ""}`
    );
  },

  getChargerTimeline: (chargePointId: string, params?: {
    page?: number;
    limit?: number;
    action?: string;
    actor_type?: string;
    start_date?: string;
    end_date?: string;
  }) => {
    const searchParams = new URLSearchParams();
    if (params?.page) searchParams.set("page", params.page.toString());
    if (params?.limit) searchParams.set("limit", params.limit.toString());
    if (params?.action) searchParams.set("action", params.action);
    if (params?.actor_type) searchParams.set("actor_type", params.actor_type);
    if (params?.start_date) searchParams.set("start_date", params.start_date);
    if (params?.end_date) searchParams.set("end_date", params.end_date);

    const query = searchParams.toString();
    return api.get<AuditLogListResponse>(
      `/api/admin/logs/audit/charger-timeline/${encodeURIComponent(chargePointId)}${query ? `?${query}` : ""}`
    );
  },
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
      credentials: 'include',
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

  /**
   * Cancel a pending firmware update (only PENDING with no attempts)
   */
  cancelUpdate: (updateId: number) =>
    api.post(`/api/admin/firmware/updates/${updateId}/cancel`, {}),

  /**
   * Admin: manually close an update as INSTALLED (polling chargers / out-of-band installs)
   */
  markInstalled: (updateId: number) =>
    api.post<import("@/types/api").FirmwareUpdate>(
      `/api/admin/firmware/updates/${updateId}/mark-installed`,
      {}
    ),

  /**
   * Admin: manually close a stuck update as FAILED
   */
  markFailed: (updateId: number) =>
    api.post<import("@/types/api").FirmwareUpdate>(
      `/api/admin/firmware/updates/${updateId}/mark-failed`,
      {}
    ),
};

/**
 * Signal Quality Service
 * Handles charger cellular signal quality data (RSSI, BER)
 */
export const signalQualityService = {
  /**
   * Get signal quality history for a charger
   * @param chargerId - The charger ID
   * @param params - Query parameters (page, limit, hours)
   */
  getSignalQuality: (
    chargerId: number,
    params?: { page?: number; limit?: number; hours?: number }
  ) => {
    const searchParams = new URLSearchParams();
    if (params?.page) searchParams.set("page", params.page.toString());
    if (params?.limit) searchParams.set("limit", params.limit.toString());
    if (params?.hours) searchParams.set("hours", params.hours.toString());

    const query = searchParams.toString();
    return api.get<SignalQualityListResponse>(
      `/api/admin/chargers/${chargerId}/signal-quality${query ? `?${query}` : ""}`
    );
  },

  /**
   * Get the most recent signal quality reading for a charger
   * @param chargerId - The charger ID
   */
  getLatestSignalQuality: (chargerId: number) =>
    api.get<SignalQuality | null>(
      `/api/admin/chargers/${chargerId}/signal-quality/latest`
    ),
};

/**
 * Charger Error Service
 * Handles charger error history and diagnostics
 */
export const chargerErrorService = {
  /**
   * Get error history for a charger
   * @param chargerId - The charger ID
   * @param params - Query parameters (page, limit, hours, include_resolved)
   */
  getErrors: (
    chargerId: number,
    params?: { page?: number; limit?: number; hours?: number; include_resolved?: boolean }
  ) => {
    const searchParams = new URLSearchParams();
    if (params?.page) searchParams.set("page", params.page.toString());
    if (params?.limit) searchParams.set("limit", params.limit.toString());
    if (params?.hours) searchParams.set("hours", params.hours.toString());
    if (params?.include_resolved !== undefined)
      searchParams.set("include_resolved", params.include_resolved.toString());

    const query = searchParams.toString();
    return api.get<ChargerErrorListResponse>(
      `/api/admin/chargers/${chargerId}/errors${query ? `?${query}` : ""}`
    );
  },

  /**
   * Get the most recent unresolved error for a charger
   * @param chargerId - The charger ID
   */
  getLatestError: (chargerId: number) =>
    api.get<ChargerError | null>(
      `/api/admin/chargers/${chargerId}/errors/latest`
    ),
};

/**
 * QR Code Service
 * Handles Razorpay QR codes for appless EV charging
 */
export const qrCodeService = {
  create: (chargerId: number) =>
    api.post<import("@/types/api").ChargerQRCode>("/api/admin/qr-codes", {
      charger_id: chargerId,
    }),

  getAll: (params?: {
    page?: number;
    limit?: number;
    status?: string;
    search?: string;
  }) => {
    const searchParams = new URLSearchParams();
    if (params?.page) searchParams.set("page", params.page.toString());
    if (params?.limit) searchParams.set("limit", params.limit.toString());
    if (params?.status) searchParams.set("status", params.status);
    if (params?.search) searchParams.set("search", params.search);

    const query = searchParams.toString();
    return api.get<import("@/types/api").ChargerQRCodeListResponse>(
      `/api/admin/qr-codes${query ? `?${query}` : ""}`
    );
  },

  getById: (id: number) =>
    api.get<import("@/types/api").ChargerQRCode>(`/api/admin/qr-codes/${id}`),

  getByChargerId: (chargerId: number) =>
    api.get<import("@/types/api").ChargerQRCode | null>(
      `/api/admin/qr-codes/charger/${chargerId}`
    ),

  close: (id: number) =>
    api.post<{ message: string }>(`/api/admin/qr-codes/${id}/close`, {}),

  getPayments: (
    id: number,
    params?: { page?: number; limit?: number; status?: string }
  ) => {
    const searchParams = new URLSearchParams();
    if (params?.page) searchParams.set("page", params.page.toString());
    if (params?.limit) searchParams.set("limit", params.limit.toString());
    if (params?.status) searchParams.set("status", params.status);

    const query = searchParams.toString();
    return api.get<import("@/types/api").QRPaymentListResponse>(
      `/api/admin/qr-codes/${id}/payments${query ? `?${query}` : ""}`
    );
  },
};

// ─── Franchisee Service ────────────────────────────────────────────

export const franchiseeService = {
  getAll: (params?: {
    page?: number;
    limit?: number;
    status?: string;
    search?: string;
  }) => {
    const searchParams = new URLSearchParams();
    if (params?.page) searchParams.set("page", params.page.toString());
    if (params?.limit) searchParams.set("limit", params.limit.toString());
    if (params?.status) searchParams.set("status", params.status);
    if (params?.search) searchParams.set("search", params.search);

    const query = searchParams.toString();
    return api.get<FranchiseeListResponse>(
      `/api/admin/franchisees${query ? `?${query}` : ""}`
    );
  },

  getById: (id: number) => api.get<Franchisee>(`/api/admin/franchisees/${id}`),

  create: (data: FranchiseeCreate) =>
    api.post<Franchisee>("/api/admin/franchisees", data),

  update: (id: number, data: FranchiseeUpdate) =>
    api.put<Franchisee>(`/api/admin/franchisees/${id}`, data),

  updateCommission: (id: number, data: CommissionUpdate) =>
    api.put<{ message: string }>(`/api/admin/franchisees/${id}/commission`, data),

  updateTDS: (id: number, data: { tds_rate_percent: number; notes?: string }) =>
    api.put<{ message: string }>(`/api/admin/franchisees/${id}/tds`, data),

  getCommissionHistory: (id: number) =>
    api.get<CommissionAuditEntry[]>(
      `/api/admin/franchisees/${id}/commission-history`
    ),

  getStations: (id: number) =>
    api.get<FranchiseeStation[]>(`/api/admin/franchisees/${id}/stations`),

  assignStations: (id: number, stationIds: number[]) =>
    api.post<{ message: string }>(`/api/admin/franchisees/${id}/stations`, {
      station_ids: stationIds,
    }),

  unassignStation: (franchiseeId: number, stationId: number) =>
    api.delete<{ message: string }>(
      `/api/admin/franchisees/${franchiseeId}/stations/${stationId}`
    ),

  updateStatus: (id: number, status: string, reason?: string) => {
    const searchParams = new URLSearchParams({ status });
    if (reason) searchParams.set("reason", reason);
    return api.put<{ message: string }>(
      `/api/admin/franchisees/${id}/status?${searchParams.toString()}`
    );
  },

  resendInvitation: (id: number) =>
    api.post<{ message: string; email: string }>(
      `/api/admin/franchisees/${id}/resend-invitation`,
      {}
    ),

  onboardRazorpay: (id: number) =>
    api.post<{
      message?: string;
      account_id?: string;
      status?: string;
      razorpay_onboarding_url?: string | null;
    }>(`/api/admin/franchisees/${id}/onboard-razorpay`, {}),

  listStakeholders: (id: number) =>
    api.get<FranchiseeStakeholder[]>(
      `/api/admin/franchisees/${id}/stakeholders`
    ),

  createStakeholder: (id: number, body: StakeholderCreate) =>
    api.post<FranchiseeStakeholder>(
      `/api/admin/franchisees/${id}/stakeholders`,
      body
    ),

  updateStakeholder: (
    id: number,
    stakeholderId: number,
    body: StakeholderUpdate
  ) =>
    api.put<FranchiseeStakeholder>(
      `/api/admin/franchisees/${id}/stakeholders/${stakeholderId}`,
      body
    ),

  submitKYC: (id: number) =>
    api.post<SubmitKYCResponse>(
      `/api/admin/franchisees/${id}/submit-kyc`,
      {}
    ),

  deleteRazorpayAccount: (id: number) =>
    api.delete<{
      status: string;
      franchisee_id: number;
      razorpay_account_id?: string;
      stakeholders_removed?: number;
    }>(`/api/admin/franchisees/${id}/razorpay-account`),

  listRazorpayApiLogs: (id: number, limit = 50) =>
    api.get<RazorpayApiLog[]>(
      `/api/admin/franchisees/${id}/razorpay-api-logs?limit=${limit}`
    ),

  // ─── Settlement ledger (admin) ────────────────────────────────
  listSettlements: (
    id: number,
    params: { page?: number; limit?: number; status?: string } = {}
  ) => {
    const searchParams = new URLSearchParams();
    if (params.page) searchParams.set("page", params.page.toString());
    if (params.limit) searchParams.set("limit", params.limit.toString());
    if (params.status) searchParams.set("status", params.status);
    const query = searchParams.toString();
    return api.get<{
      data: AdminSettlementEntry[];
      total: number;
      page: number;
      limit: number;
    }>(
      `/api/admin/franchisees/${id}/settlements${query ? `?${query}` : ""}`
    );
  },

  retryFailedSettlements: (id: number) =>
    api.post<{ message: string }>(
      `/api/admin/franchisees/${id}/settlements/retry-failed`,
      {}
    ),

  holdSettlement: (id: number, entryId: number) =>
    api.post<{ message: string }>(
      `/api/admin/franchisees/${id}/settlements/${entryId}/hold`,
      {}
    ),

  releaseSettlement: (id: number, entryId: number) =>
    api.post<{ message: string }>(
      `/api/admin/franchisees/${id}/settlements/${entryId}/release`,
      {}
    ),
};

// ─── Franchisee Portal Service ─────────────────────────────────────

// Franchisee portal endpoints return loosely-typed payloads that flow
// straight into admin-style UIs reading ad-hoc fields. Defining strict
// response schemas for all of these is a follow-up; for now, allow
// `any` in this section only.
/* eslint-disable @typescript-eslint/no-explicit-any */
export const franchiseePortalService = {
  getDashboard: () => api.get<any>("/api/franchisee/dashboard"),

  getStations: () => api.get<any[]>("/api/franchisee/stations"),

  getStation: (id: number) => api.get<any>(`/api/franchisee/stations/${id}`),

  getCharger: (id: number) => api.get<any>(`/api/franchisee/chargers/${id}`),

  remoteStop: (chargerId: number) =>
    api.post<any>(`/api/franchisee/chargers/${chargerId}/remote-stop`),

  resetCharger: (chargerId: number) =>
    api.post<any>(`/api/franchisee/chargers/${chargerId}/reset`),

  changeAvailability: (chargerId: number, available: boolean) =>
    api.post<any>(
      `/api/franchisee/chargers/${chargerId}/change-availability?available=${available}`
    ),

  getTransactions: (params?: { page?: number; limit?: number; status?: string }) => {
    const searchParams = new URLSearchParams();
    if (params?.page) searchParams.set("page", params.page.toString());
    if (params?.limit) searchParams.set("limit", params.limit.toString());
    if (params?.status) searchParams.set("status", params.status);
    const query = searchParams.toString();
    return api.get<any>(`/api/franchisee/transactions${query ? `?${query}` : ""}`);
  },

  getTransaction: (id: number) =>
    api.get<any>(`/api/franchisee/transactions/${id}`),

  getSettlements: (params?: { page?: number; limit?: number }) => {
    const searchParams = new URLSearchParams();
    if (params?.page) searchParams.set("page", params.page.toString());
    if (params?.limit) searchParams.set("limit", params.limit.toString());
    const query = searchParams.toString();
    return api.get<any>(`/api/franchisee/settlements${query ? `?${query}` : ""}`);
  },

  getProfile: () => api.get<any>("/api/franchisee/profile"),

  getQRCodes: () =>
    api.get<{
      data: PortalQRCode[];
      can_create_direct: boolean;
      razorpay_account_status: string | null;
      franchisee_status: string;
    }>("/api/franchisee/qr-codes"),

  createQRCode: (charger_id: number) =>
    api.post<PortalQRCode>("/api/franchisee/qr-codes", { charger_id }),

  regenerateQRCode: (qr_id: number) =>
    api.post<PortalQRCode>(
      `/api/franchisee/qr-codes/${qr_id}/regenerate`,
      {}
    ),

  closeQRCode: (qr_id: number) =>
    api.post<{ message: string; id: number }>(
      `/api/franchisee/qr-codes/${qr_id}/close`,
      {}
    ),
};
/* eslint-enable @typescript-eslint/no-explicit-any */

export interface PortalQRCode {
  id: number;
  charger_id: number;
  charger_name: string | null;
  razorpay_qr_code_id: string;
  image_url: string;
  short_url: string | null;
  is_active: boolean;
  owner: "franchisee" | "platform";
  payee_display_name: string;
  created_at: string;
}
