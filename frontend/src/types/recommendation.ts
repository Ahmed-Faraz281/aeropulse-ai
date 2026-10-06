export type RecommendationType =
  | 'OUTDOOR_ACTIVITY'
  | 'VENTILATION'
  | 'INDOOR_AIR'
  | 'EXPOSURE_REDUCTION'
  | 'MASK_GUIDANCE'
  | 'TRAVEL_TIMING'
  | 'HIGH_RISK_GROUP_CAUTION'
  | 'POLLUTANT_SPECIFIC'
  | 'FORECAST_PREVENTION'
  | 'ALERT_RESPONSE';

export type RecommendationPriority = 'CRITICAL' | 'HIGH' | 'MEDIUM' | 'LOW' | 'INFO';

export interface RecommendationItem {
  id: string;
  type: RecommendationType;
  title: string;
  message: string;
  action: string;
  severity: string;
  priority: RecommendationPriority;
  reason: string;
  triggered_by: string;
  supporting_data: Record<string, unknown>;
  source_type: string;
  generated_at: string;
  location_id: number;
  category?: string | null;
  dominant_pollutant?: string | null;
  forecast_based: boolean;
  active: boolean;
}

export interface ForecastContext {
  horizon_hours: number;
  predicted_aqi: number;
  predicted_category: string;
  target_timestamp: string;
  model_name: string;
}

export interface LocationRecommendationsResponse {
  location_id: number;
  location_name: string;
  city: string;
  assessment_timestamp: string;
  current_aqi?: number | null;
  current_category?: string | null;
  dominant_pollutant?: string | null;
  trend?: string | null;
  source_type: string;
  has_simulated_data: boolean;
  disclaimer: string;
  forecast_summary?: ForecastContext | null;
  active_alerts_count: number;
  recommendations: RecommendationItem[];
}
