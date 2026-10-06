export type AQICategory =
  | 'Good'
  | 'Satisfactory'
  | 'Moderate'
  | 'Poor'
  | 'Very Poor'
  | 'Severe';

export type AQIStatus =
  | 'CALCULATED'
  | 'INSUFFICIENT_DATA'
  | 'INVALID_DATA'
  | 'UNSUPPORTED';

export interface AQIResponse {
  id: number;
  location_id: number;
  reading_id: number;
  timestamp: string;
  aqi: number | null;
  category: AQICategory | string | null;
  dominant_pollutant: string | null;
  calculation_method: string;
  status: AQIStatus;
  pollutant_subindices?: Record<string, number | null>;
  warnings?: string[];
  message?: string | null;
  created_at: string;
  updated_at: string;
}

export interface AQIHistoryParams {
  start_time?: string;
  end_time?: string;
  limit?: number;
}
