export interface Station {
  id: number;
  name: string;
  latitude: number;
  longitude: number;
  address: string;
  franchisee_id?: number | null;
  state?: string | null;
  state_code?: string | null;
  pincode?: string | null;
  created_at: string;
  updated_at: string;
}

export interface StationCreate {
  name: string;
  latitude: number;
  longitude: number;
  address: string;
  franchisee_id?: number;
  state?: string;
  state_code?: string;
  pincode?: string;
}

export interface StationUpdate {
  name?: string;
  latitude?: number;
  longitude?: number;
  address?: string;
}

export interface StationListResponse {
  data: Station[];
  total: number;
  page: number;
  limit: number;
}

export interface Charger {
  id: number;
  charge_point_string_id: string;
  external_charger_id?: string;
  station_id: number;
  name: string;
  model?: string;
  vendor?: string;
  serial_number?: string;
  firmware_version?: string;
  latest_status: string;
  last_heart_beat_time?: string;
  connection_status: boolean;
  created_at: string;
  updated_at: string;
  tariff_per_kwh?: number;
  tariff_gst_percent?: number;
  latest_error?: LatestErrorInfo;
}

export interface ChargerCreate {
  station_id: number;
  name: string;
  model?: string;
  vendor?: string;
  serial_number?: string;
  external_charger_id?: string;
  connectors: ConnectorInput[];
  tariff_per_kwh?: number;
}

export interface ConnectorInput {
  connector_id: number;
  connector_type: string;
  max_power_kw?: number;
}

export interface ChargerUpdate {
  name?: string;
  model?: string;
  vendor?: string;
  latest_status?: string;
  external_charger_id?: string;
  tariff_per_kwh?: number;
}

export interface ChargerListResponse {
  data: Charger[];
  total: number;
  page: number;
  limit: number;
}

export interface Connector {
  id: number;
  connector_id: number;
  connector_type: string;
  max_power_kw?: number;
}

export interface ChargerDetail {
  charger: Charger & {
    station_name?: string;
  };
  station: {
    id: number;
    name: string;
    address: string;
  };
  connectors: Connector[];
  transactions?: Array<{
    id: number;
    status: string;
    id_tag: string;
    start_timestamp: string;
    meter_start?: number;
  }>;
  current_transaction?: {
    transaction_id: number;
  };
  recent_transaction?: {
    transaction_id: number;
  };
}

export interface MeterValue {
  id: number;
  created_at: string;
  updated_at: string;
  reading_kwh: number;
  current?: number;
  voltage?: number;
  power_kw?: number;
}

export interface Transaction {
  id: number;
  user_id: number;
  charger_id: number;
  start_meter_kwh?: number;
  end_meter_kwh?: number;
  energy_consumed_kwh?: number;
  start_time: string;
  end_time?: string;
  stop_reason?: string;
  transaction_status: string;
  created_at: string;
  updated_at: string;
}

export interface TransactionDetail {
  transaction: Transaction;
  user: {
    id: number;
    full_name?: string;
    email?: string;
    phone_number?: string;
  };
  charger: {
    id: number;
    name: string;
    charge_point_string_id: string;
  };
  meter_values: MeterValue[];
  wallet_transactions: Array<{
    id: number;
    amount: number;
    type: string;
    description?: string;
    created_at: string;
  }>;
}

export interface ApiResponse<T = any> {
  success?: boolean;
  message: string;
  data?: T;
}

// User Management Types
export interface UserListItem {
  id: number;
  email: string;
  full_name?: string;
  phone_number?: string;
  role: string;
  auth_provider: string;
  is_active: boolean;
  is_email_verified: boolean;
  rfid_card_id?: string;
  created_at: string;
  updated_at: string;
  last_login?: string;
  display_name: string;
  wallet_balance?: number;
  total_transactions: number;
  total_wallet_transactions: number;
}

export interface UserDetail extends UserListItem {
  clerk_user_id?: string;
  avatar_url?: string;
  terms_accepted_at?: string;
  preferred_language: string;
  notification_preferences: Record<string, any>;
}

export interface UserListResponse {
  data: UserListItem[];
  total: number;
  page: number;
  limit: number;
  total_pages: number;
}

export interface UserTransactionSummary {
  charging_transactions: number;
  wallet_transactions: number;
  total_energy_consumed: number;
  total_amount_spent: number;
  last_transaction_date?: string;
}

export interface UserChargingTransaction {
  id: number;
  charger_name: string;
  charger_id: string;
  energy_consumed_kwh?: number;
  start_time: string;
  end_time?: string;
  status: string;
  stop_reason?: string;
}

export interface UserWalletTransaction {
  id: number;
  amount: number;
  type: string;
  description?: string;
  payment_metadata?: Record<string, any>;
  created_at: string;
}

export interface UserTransactionsResponse {
  data: UserChargingTransaction[];
  total: number;
  page: number;
  limit: number;
  total_pages: number;
}

export interface UserWalletTransactionsResponse {
  data: UserWalletTransaction[];
  total: number;
  page: number;
  limit: number;
  total_pages: number;
}

// Wallet Payment Types
export interface CreateRechargeRequest {
  amount: number;
}

export interface CreateRechargeResponse {
  order_id: string;
  amount: number;
  currency: string;
  key_id: string;
  wallet_transaction_id: number;
}

export interface VerifyPaymentRequest {
  razorpay_order_id: string;
  razorpay_payment_id: string;
  razorpay_signature: string;
}

export interface VerifyPaymentResponse {
  success: boolean;
  message: string;
  wallet_balance: number;
  transaction_id: number;
}

export interface PaymentStatusResponse {
  transaction_id: number;
  amount: number;
  status: string;
  razorpay_order_id?: string;
  razorpay_payment_id?: string;
  created_at: string;
}

export interface RechargeHistoryResponse {
  data: Array<{
    id: number;
    amount: number;
    status: string;
    razorpay_order_id?: string;
    razorpay_payment_id?: string;
    description?: string;
    created_at: string;
  }>;
  total: number;
}

// Firmware Update Types
export interface FirmwareFile {
  id: number;
  version: string;
  filename: string;
  file_size: number;
  checksum: string;
  description?: string;
  uploaded_by_id: number;
  created_at: string;
  is_active: boolean;
}

export interface FirmwareFileListResponse {
  data: FirmwareFile[];
  total: number;
  page: number;
  limit: number;
}

export type FirmwareUpdateStatus =
  | 'PENDING'
  | 'DOWNLOADING'
  | 'DOWNLOADED'
  | 'INSTALLING'
  | 'INSTALLED'
  | 'DOWNLOAD_FAILED'
  | 'INSTALLATION_FAILED'
  | 'CANCELLED';

export interface FirmwareUpdate {
  id: number;
  charger_id: number;
  firmware_file_id: number;
  status: FirmwareUpdateStatus;
  download_url: string;
  initiated_at: string;
  started_at?: string;
  completed_at?: string;
  error_message?: string;
  retry_count?: number;
  firmware_version?: string;
}

export interface FirmwareHistoryResponse {
  data: FirmwareUpdate[];
  total: number;
  page: number;
  limit: number;
}

export interface FirmwareUpdateRequest {
  firmware_file_id: number;
}

export interface BulkFirmwareUpdateRequest {
  firmware_file_id: number;
  charger_ids: number[];
}

export interface BulkUpdateResult {
  success: Array<{
    charger_id: number;
    charger_name: string;
    update_id: number;
  }>;
  failed: Array<{
    charger_id: number;
    charger_name?: string;
    reason: string;
  }>;
}

export interface UpdateStatusSummary {
  pending: number;
  downloading: number;
  installing: number;
  completed_today: number;
  failed_today: number;
}

export interface UpdateStatusDashboard {
  in_progress: Array<{
    update_id: number;
    charger_id: number;
    charger_name: string;
    charge_point_id: string;
    firmware_version: string;
    status: FirmwareUpdateStatus;
    started_at?: string;
    initiated_at: string;
  }>;
  summary: UpdateStatusSummary;
}
// Signal Quality Types
export interface SignalQuality {
  id: number;
  charger_id: number;
  rssi: number;  // Received Signal Strength Indicator (0-31 for GSM, 99=unknown)
  ber: number;   // Bit Error Rate (0-7 for GSM, 99=unknown/not detectable)
  timestamp: string;
  created_at: string;
}

export interface SignalQualityListResponse {
  data: SignalQuality[];
  total: number;
  page: number;
  limit: number;
  charger_id: number;
  latest_rssi?: number;
  latest_ber?: number;
}

// Charger Error Types
export interface LatestErrorInfo {
  error_code: string;
  vendor_error_code?: string;
  info?: string;
  created_at: string;
}

export interface ChargerError {
  id: number;
  charger_id: number;
  connector_id: number;
  status: string;
  error_code: string;
  vendor_error_code?: string;
  vendor_id?: string;
  info?: string;
  error_timestamp?: string;
  is_resolved: boolean;
  resolved_at?: string;
  created_at: string;
}

export interface ChargerErrorListResponse {
  data: ChargerError[];
  total: number;
  page: number;
  limit: number;
  charger_id: number;
  unresolved_count: number;
}

// QR Code Types (Appless Charging)
export interface ChargerQRCode {
  id: number;
  charger_id: number;
  charger_name: string;
  charge_point_string_id: string;
  razorpay_qr_code_id: string;
  image_url: string;
  short_url?: string;
  is_active: boolean;
  payment_count?: number;
  total_revenue?: number;
  total_refunds?: number;
  created_at: string;
}

export interface ChargerQRCodeListResponse {
  data: ChargerQRCode[];
  total: number;
  page: number;
  limit: number;
}

export type QRPaymentStatus =
  | "PAID"
  | "CHARGING"
  | "COMPLETED"
  | "REFUNDED"
  | "REFUND_FAILED"
  | "EXPIRED"
  | "FAILED";

export interface QRPayment {
  id: number;
  razorpay_payment_id: string;
  amount_paid: string;
  customer_vpa?: string;
  customer_name?: string;
  customer_contact?: string;
  energy_cost?: string;
  gst_amount?: string;
  platform_fee?: string;
  razorpay_commission?: string;
  razorpay_gst?: string;
  fee_source?: string;
  refund_amount?: string;
  status: QRPaymentStatus;
  failure_reason?: string;
  transaction_id?: number;
  created_at: string;
}

export interface QRPaymentListResponse {
  data: QRPayment[];
  total: number;
  page: number;
  limit: number;
}

// ─── Franchisee Types ──────────────────────────────────────────────

export interface Franchisee {
  id: number;
  business_name: string;
  business_type?: string | null;
  contact_name: string;
  contact_email: string;
  contact_phone: string;
  address?: string | null;
  pan_number?: string | null;
  gstin?: string | null;
  state?: string | null;
  state_code?: string | null;
  commission_percent: number;
  tds_rate_percent: number;
  status: string;
  status_reason?: string | null;
  razorpay_account_id?: string | null;
  razorpay_account_status?: string | null;
  razorpay_onboarding_url?: string | null;
  station_count: number;
  activated_at?: string | null;
  created_at: string;
  updated_at: string;
  notes?: string | null;
}

export interface FranchiseeCreate {
  business_name: string;
  contact_name: string;
  contact_email: string;
  contact_phone: string;
  commission_percent?: number;
  tds_rate_percent?: number;
  notes?: string;
}

export interface FranchiseeUpdate {
  business_name?: string;
  contact_name?: string;
  contact_phone?: string;
  address?: string;
  business_type?: string;
  pan_number?: string;
  gstin?: string;
  tan_number?: string;
  state?: string;
  state_code?: string;
  notes?: string;
}

export interface FranchiseeListResponse {
  data: Franchisee[];
  total: number;
  page: number;
  limit: number;
}

export interface CommissionUpdate {
  new_percent: number;
  reason: string;
  effective_from: string;
  notes?: string;
}

export interface CommissionAuditEntry {
  id: number;
  previous_percent?: number | null;
  new_percent: number;
  reason: string;
  effective_from: string;
  notes?: string | null;
  changed_by_email?: string | null;
  created_at: string;
}

export interface FranchiseeStation {
  id: number;
  name: string;
  address?: string;
  latitude?: number;
  longitude?: number;
  state?: string;
  state_code?: string;
  pincode?: string;
  charger_count: number;
}
