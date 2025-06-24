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
    id: number;
    user_id: number;
    start_time: string;
    status: string;
  };
}

export interface ApiResponse<T = any> {
  success?: boolean;
  message: string;
  data?: T;
}