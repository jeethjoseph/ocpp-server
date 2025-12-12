// API Services for Capacitor Mobile App (User-facing endpoints only)
import type {
  PublicStationsListResponse,
  PublicStationResponse,
  ChargerDetail,
  TransactionDetail,
  MeterValue,
  ApiResponse,
  CreateRechargeResponse,
  VerifyPaymentRequest,
  VerifyPaymentResponse,
  PaymentStatusResponse,
  RechargeHistoryResponse,
  UserWallet,
} from '../types/api';

// Type for the API client
export type ApiClient = {
  get: <T>(endpoint: string) => Promise<T>;
  post: <T>(endpoint: string, data?: unknown) => Promise<T>;
  put: <T>(endpoint: string, data?: unknown) => Promise<T>;
  delete: <T>(endpoint: string) => Promise<T>;
};

/**
 * Public stations service - No auth required
 * Used for finding charging stations
 */
export const publicStationService = (api: ApiClient) => ({
  /**
   * Get all public stations
   */
  getAll: () =>
    api.get<PublicStationsListResponse>(`/api/public/stations`),

  /**
   * Get a specific station by ID
   */
  getById: (id: number) =>
    api.get<PublicStationResponse>(`/api/public/stations/${id}`)
});

/**
 * Charger service - User actions (String ID support for customer-facing apps)
 * Used for controlling chargers and viewing status using alphanumeric charge_point_string_id
 */
export const chargerService = (api: ApiClient) => ({
  /**
   * Get charger details including current transaction
   * @param id - Charger charge_point_string_id (alphanumeric, e.g., 'AIRPORT_EXPRESS_CHARGING_01')
   */
  getById: (id: string) =>
    api.get<ChargerDetail>(`/api/users/charger/${id}`),

  /**
   * Start a charging session (Remote Start)
   * @param id - Charger charge_point_string_id (alphanumeric)
   * @param connectorId - Connector ID (default: 1)
   * @param idTag - User ID tag (default: user's email or ID)
   */
  remoteStart: (id: string, connectorId: number = 1, idTag: string = "user") =>
    api.post<ApiResponse>(`/api/users/charger/${id}/remote-start`, {
      connector_id: connectorId,
      id_tag: idTag,
    }),

  /**
   * Stop a charging session (Remote Stop)
   * @param id - Charger charge_point_string_id (alphanumeric)
   * @param reason - Optional stop reason
   */
  remoteStop: (id: string, reason?: string) =>
    api.post<ApiResponse>(
      `/api/users/charger/${id}/remote-stop`,
      reason ? { reason } : undefined
    ),
});

/**
 * Transaction service - User's charging sessions
 */
export const transactionService = (api: ApiClient) => ({
  /**
   * Get user's transaction details
   * @param id - Transaction ID
   */
  getUserTransaction: (id: number) =>
    api.get<TransactionDetail>(`/api/users/transaction/${id}`),

  /**
   * Get meter values for a transaction (live energy readings)
   * @param id - Transaction ID
   */
  getUserTransactionMeterValues: (id: number) =>
    api.get<{
      meter_values: MeterValue[];
      energy_chart_data: Record<string, unknown>;
    }>(`/api/users/transaction/${id}/meter-values`),
});

/**
 * User session service
 * Used for viewing user's charging and wallet history
 */
export const userSessionService = (api: ApiClient) => ({
  /**
   * Get user's sessions (charging + wallet transactions)
   * Returns paginated transactions of both types
   */
  getMySessions: (page: number = 1, limit: number = 20) =>
    api.get<{
      data: Array<{
        id: number;
        type: "charging" | "wallet";
        created_at: string;
        // Charging transaction fields
        station_name?: string;
        charger_name?: string;
        energy_consumed_kwh?: number;
        start_time?: string;
        end_time?: string;
        status?: string;
        amount?: number;
        wallet_transactions?: Array<{
          id: number;
          amount: number;
          type: string;
          description: string;
          created_at: string;
        }>;
        // Wallet transaction fields
        transaction_type?: string;
        description?: string;
        payment_metadata?: any;
      }>;
      total: number;
      page: number;
      limit: number;
      total_pages: number;
    }>(`/api/users/my-sessions?page=${page}&limit=${limit}`),

  /**
   * Get user's wallet balance
   */
  getMyWallet: () =>
    api.get<UserWallet>(`/api/users/my-wallet`),
});

/**
 * Wallet payment service
 * Handles wallet recharge via Razorpay
 */
export const walletPaymentService = (api: ApiClient) => ({
  /**
   * Create a Razorpay order for wallet recharge
   * @param amount - Recharge amount in INR
   */
  createRechargeOrder: (amount: number) =>
    api.post<CreateRechargeResponse>(
      "/api/wallet/create-recharge",
      { amount }
    ),

  /**
   * Verify payment after Razorpay checkout completion
   * @param paymentDetails - Razorpay payment details
   */
  verifyPayment: (paymentDetails: VerifyPaymentRequest) =>
    api.post<VerifyPaymentResponse>(
      "/api/wallet/verify-payment",
      paymentDetails
    ),

  /**
   * Get payment status by transaction ID
   * @param transactionId - Wallet transaction ID
   */
  getPaymentStatus: (transactionId: number) =>
    api.get<PaymentStatusResponse>(
      `/api/wallet/payment-status/${transactionId}`
    ),

  /**
   * Get user's recharge history
   */
  getRechargeHistory: () =>
    api.get<RechargeHistoryResponse>(
      "/api/wallet/recharge-history"
    ),
});
