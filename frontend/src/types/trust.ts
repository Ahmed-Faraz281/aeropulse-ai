export type DataFreshnessStatus = 'FRESH' | 'STALE' | 'UNAVAILABLE';

export type PredictionReadiness = 'READY' | 'INSUFFICIENT_HISTORY' | 'MODEL_UNAVAILABLE' | 'STALE_INPUT';

export interface StationDataFreshness {
  status: DataFreshnessStatus;
  observation_timestamp?: string | null;
  age_hours?: number | null;
  age_minutes?: number | null;
  message: string;
}

export interface StationDataQuality {
  aqi_valid: boolean;
  aqi_status: string;
  pollutants_available: string[];
  pollutants_missing: string[];
  pollutants_used_for_aqi: string[];
  dominant_pollutant?: string | null;
  total_pollutants_monitored: number;
  available_count: number;
  completeness_pct: number;
  quality_status: string;
  validation_notes?: string | null;
}

export interface StationProvenanceTrust {
  source_type: string;
  source_name: string;
  provider?: string | null;
  notice: string;
}

export interface StationPredictionTrust {
  readiness: PredictionReadiness;
  sufficient_history: boolean;
  continuous_hourly_count: number;
  model_available: boolean;
  active_horizons: number[];
  input_freshness: DataFreshnessStatus;
  confidence_level: string;
  explanation: string;
}

export interface StationDegradedState {
  is_degraded: boolean;
  openaq_accessible: boolean;
  ml_ready: boolean;
  alerts_operational: boolean;
  recommendations_operational: boolean;
  notes: string[];
}

export interface StationTrustResponse {
  location_id: number;
  location_name: string;
  city: string;
  state?: string | null;
  country: string;
  external_provider?: string | null;
  external_id?: string | null;
  is_active: boolean;
  current_aqi?: number | null;
  aqi_category?: string | null;
  freshness: StationDataFreshness;
  quality: StationDataQuality;
  provenance: StationProvenanceTrust;
  prediction: StationPredictionTrust;
  automation: Record<string, unknown>;
  degraded_state: StationDegradedState;
  evaluated_at: string;
}

export interface SystemTrustOverview {
  total_locations: number;
  active_locations: number;
  fresh_stations_count: number;
  stale_stations_count: number;
  unavailable_stations_count: number;
  active_model_horizons: number[];
  available_models_count: number;
  automation_status: string;
  automation_running: boolean;
  automation_paused: boolean;
  last_sync?: string | null;
  next_sync?: string | null;
  data_sources_summary: Record<string, number>;
  evaluated_at: string;
}
