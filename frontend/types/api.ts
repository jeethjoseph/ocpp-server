export interface Station {
  id: number;
  name: string;
  latitude: number;
  longitude: number;
  address: string;
  created_at: string;
  updated_at: string;
}

export interface StationCreate {
  name: string;
  latitude: number;
  longitude: number;
  address: string;
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
  station_id: number;
  name: string;
  model?: string;
  vendor?: string;
  serial_number?: string;
  latest_status: string;
  last_heart_beat_time?: string;
  connection_status: boolean;
  created_at: string;
  updated_at: string;
}

export interface ChargerCreate {
  station_id: number;
  name: string;
  model?: string;
  vendor?: string;
  serial_number?: string;
  connectors: ConnectorInput[];
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