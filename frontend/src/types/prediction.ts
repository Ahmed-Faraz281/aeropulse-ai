export interface ModelMetrics {
  mae: number;
  rmse: number;
  r2: number;
}

export interface PredictionTrainRequest {
  location_id: number;
  horizon_hours: number;
  min_observations?: number;
}

export interface PredictionTrainResponse {
  status: 'SUCCESS' | 'INSUFFICIENT_DATA' | 'ERROR';
  message: string;
  location_id: number;
  horizon_hours: number;
  training_observations: number;
  training_start?: string;
  training_end?: string;
  metrics?: ModelMetrics;
  data_sources: string[];
  has_simulated_data: boolean;
  provenance_notice: string;
}

export interface PredictionRequest {
  location_id: number;
  horizon_hours: number;
}

export interface PredictionResponse {
  id?: number;
  location_id: number;
  location_name?: string;
  base_timestamp: string;
  target_timestamp: string;
  horizon_hours: number;
  predicted_aqi: number;
  predicted_category: string;
  model_name: string;
  training_observations: number;
  mae?: number;
  rmse?: number;
  r2?: number;
  data_sources: string[];
  has_simulated_data: boolean;
  provenance_notice: string;
  created_at: string;
}
