export type SourceType = 'API' | 'UPLOADED' | 'SIMULATED' | 'DEMO';
export type QualityStatus = 'VALID' | 'WARNING' | 'INVALID';

export interface Location {
  id: number;
  name: string;
  city: string;
  state: string;
  country: string;
  latitude: number;
  longitude: number;
  description?: string;
  is_active: boolean;
  created_at: string;
  updated_at: string;
}

export interface DataSource {
  id: number;
  name: string;
  source_type: SourceType;
  provider?: string;
  description?: string;
  is_active: boolean;
  created_at: string;
  updated_at: string;
}

export interface AirQualityReading {
  id: number;
  location_id: number;
  timestamp: string;
  pm25: number | null;
  pm10: number | null;
  co: number | null;
  no2: number | null;
  so2: number | null;
  o3: number | null;
  nh3?: number | null;
  pb?: number | null;
  temperature: number | null;
  humidity: number | null;
  wind_speed?: number | null;
  wind_direction?: number | null;
  pressure?: number | null;
  source_id: number;
  source_type: SourceType;
  quality_status: QualityStatus;
  validation_notes?: string | null;
  created_at: string;
  updated_at: string;
}

export interface CurrentReadingResponse {
  location_id: number;
  location_name: string;
  city: string;
  reading: AirQualityReading | null;
  message?: string;
}
