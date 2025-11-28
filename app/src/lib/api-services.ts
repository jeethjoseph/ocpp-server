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
 * Charger service - User actions
 * Used for controlling chargers and viewing status
 */
export const chargerService = (api: ApiClient) => ({
  /**
   * Get charger details including current transaction
   */
  getById: (id: number) =>
    api.get<ChargerDetail>(`/api/admin/chargers/${id}`),

  /**
   * Start a charging session (Remote Start)
   * @param id - Charger ID
   * @param connectorId - Connector ID (default: 1)
   * @param idTag - User ID tag (default: user's email or ID)
   */
  remoteStart: (id: number, connectorId: number = 1, idTag: string = "user") =>
    api.post<ApiResponse>(`/api/admin/chargers/${id}/remote-start`, {
      connector_id: connectorId,
      id_tag: idTag,
    }),

  /**
   * Stop a charging session (Remote Stop)
   * @param id - Charger ID
   * @param reason - Optional stop reason
   */
  remoteStop: (id: number, reason?: string) =>
    api.post<ApiResponse>(
      `/api/admin/chargers/${id}/remote-stop`,
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
   */
  getMySessions: () =>
    api.get<{
      charging_sessions: Array<{
        transaction_id: number;
        charger_name: string;
        station_name: string;
        energy_kwh: number;
        cost: number;
        start_time: string;
        end_time?: string;
        status: string;
      }>;
      wallet_transactions: Array<{
        id: number;
        amount: number;
        type: string;
        description: string;
        created_at: string;
      }>;
      wallet_balance: number;
    }>(`/api/users/my-sessions`),

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
