import { apiClient } from './api';
import type { AQIResponse } from '../types/aqi';
import type { Alert } from '../types/alert';
import type { RecommendationItem } from '../types/recommendation';

export interface UserLocationEcho {
  latitude: number;
  longitude: number;
  accuracy_meters?: number | null;
}

export interface ResolvedStationInfo {
  location_id: number;
  id?: number;
  external_id: number;
  external_provider?: string;
  name: string;
  city: string;
  state?: string;
  country?: string;
  latitude: number;
  longitude: number;
  distance_km: number;
  is_monitor?: boolean;
  data_freshness: 'FRESH' | 'STALE' | 'UNAVAILABLE';
  last_observation_time?: string | null;
  pollutants_monitored?: string[];
}

export interface DistantStationInfo {
  external_id: number;
  name: string;
  city: string;
  latitude: number;
  longitude: number;
  distance_km: number;
  notice: string;
}

export interface PredictionSummaryItem {
  horizon_hours: number;
  predicted_aqi: number | null;
  category: string | null;
  status: string;
  target_timestamp?: string | null;
  model_name?: string | null;
  message?: string | null;
}

export interface WorkflowExecutionMetadata {
  duration_seconds: number;
  cache_hit: boolean;
  new_station_discovered: boolean;
  observations_ingested: number;
  predictions_generated: number;
  warnings: string[];
}

export interface LocationWorkflowResponse {
  status: 'SUCCESS' | 'PARTIAL_SUCCESS' | 'NO_STATIONS_FOUND' | 'DATA_UNAVAILABLE' | 'ERROR';
  message: string;
  user_location: UserLocationEcho;
  resolved_station: ResolvedStationInfo | null;
  nearest_distant_station: DistantStationInfo | null;
  current_aqi: AQIResponse | null;
  predictions: PredictionSummaryItem[];
  active_alerts: Alert[];
  recommendations: RecommendationItem[];
  alternative_stations: ResolvedStationInfo[];
  metadata: WorkflowExecutionMetadata;
}

export interface LocationWorkflowRequest {
  latitude: number;
  longitude: number;
  accuracy_meters?: number | null;
  radius_meters?: number;
  force_refresh?: boolean;
}

/**
 * Resolves nearest monitoring station, current AQI, ML predictions, alerts, and recommendations
 * based on user coordinates.
 * Configured with a 15-second timeout for upstream resilience.
 */
export const resolveLocationWorkflow = async (
  request: LocationWorkflowRequest
): Promise<LocationWorkflowResponse> => {
  const response = await apiClient.post<LocationWorkflowResponse>(
    '/location-workflow/resolve',
    request,
    { timeout: 15000 }
  );
  return response.data;
};
