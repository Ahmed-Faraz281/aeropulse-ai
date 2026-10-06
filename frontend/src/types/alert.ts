export type AlertSeverity = 'INFO' | 'WARNING' | 'HIGH' | 'CRITICAL';
export type AlertStatus = 'ACTIVE' | 'ACKNOWLEDGED' | 'RESOLVED' | 'DISMISSED';
export type AlertType =
  | 'AQI_THRESHOLD'
  | 'SUSTAINED_HIGH_AQI'
  | 'RAPID_INCREASE'
  | 'PREDICTED_THRESHOLD'
  | 'CATEGORY_CHANGE';

export interface AlertRule {
  id: number;
  name: string;
  alert_type: AlertType;
  threshold: number;
  duration_hours?: number;
  window_hours?: number;
  severity: AlertSeverity;
  enabled: boolean;
  applies_to_prediction: boolean;
  prediction_horizon_hours?: number;
  created_at: string;
  updated_at: string;
}

export interface AlertRuleCreate {
  name: string;
  alert_type: AlertType;
  threshold: number;
  duration_hours?: number;
  window_hours?: number;
  severity?: AlertSeverity;
  enabled?: boolean;
  applies_to_prediction?: boolean;
  prediction_horizon_hours?: number;
}

export interface Alert {
  id: number;
  location_id: number;
  location_name?: string;
  rule_id?: number;
  alert_type: AlertType;
  severity: AlertSeverity;
  status: AlertStatus;
  title: string;
  message: string;
  observed_value?: number;
  threshold_value: number;
  detected_at: string;
  resolved_at?: string;
  source_type: string;
  is_prediction: boolean;
  prediction_id?: number;
  metadata_json?: Record<string, any>;
  created_at: string;
  updated_at: string;
}

export interface AlertEvaluationResponse {
  location_id: number;
  location_name?: string;
  evaluated_at: string;
  alerts_created: number;
  alerts_active: number;
  alerts: Alert[];
}
