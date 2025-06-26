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
  charger: Charger;
  station: {
    id: number;
    name: string;
    address: string;
  };
  connectors: Connector[];
  current_transaction?: {
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