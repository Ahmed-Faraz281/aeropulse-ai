import type { WhatIfSimulationRequest } from './whatIf';

export type ReportType =
  | 'LOCATION_SUMMARY'
  | 'PERIOD_REPORT'
  | 'COMPARISON_REPORT'
  | 'WHAT_IF_REPORT';

export interface ReportGenerateRequest {
  report_type: ReportType;
  location_id: number;
  start_time?: string | null;
  end_time?: string | null;
  period_preset?: string | null;
  comparison_location_ids?: number[] | null;
  what_if_request?: WhatIfSimulationRequest | null;
}

export interface ReportPreviewResponse {
  report_title: string;
  report_type: ReportType;
  location_name: string;
  city: string;
  state: string;
  country: string;
  reporting_period: string;
  generated_at: string;
  provenance_summary: {
    observed_provenance: string;
    forecast_provenance: string;
    scenario_provenance: string;
  };

  latest_aqi?: number | null;
  latest_category?: string | null;
  dominant_pollutant?: string | null;
  aqi_statistics: {
    count: number;
    mean?: number | null;
    minimum?: number | null;
    maximum?: number | null;
    median?: number | null;
    stddev?: number | null;
  };
  category_distribution: Record<string, number>;
  pollutant_summary: Record<
    string,
    {
      available: boolean;
      label: string;
      unit: string;
      message?: string | null;
      statistics: {
        count: number;
        mean?: number | null;
        minimum?: number | null;
        maximum?: number | null;
      };
      latest?: number | null;
      trend?: string | null;
    }
  >;
  trend_direction: string;

  anomalies_count: number;
  events_count: number;
  alerts_count: number;

  forecast_available: boolean;
  forecast_summary?: {
    horizon_hours: number;
    predicted_aqi: number;
    predicted_category: string;
    model_name: string;
    target_timestamp?: string | null;
    mae?: number | null;
    rmse?: number | null;
    r2?: number | null;
    has_simulated_data: boolean;
    label: string;
  } | null;

  top_recommendations: Array<{
    id: string;
    type: string;
    priority: string;
    action: string;
    reason: string;
    triggered_by: string;
    supporting_data?: Record<string, any>;
    source_type?: string;
  }>;

  comparison_data?: Array<{
    location_id: number;
    location_name: string;
    city: string;
    state: string;
    reading_count: number;
    latest_aqi?: number | null;
    latest_category?: string | null;
    mean_aqi?: number | null;
    min_aqi?: number | null;
    max_aqi?: number | null;
  }> | null;

  what_if_summary?: Record<string, any> | null;
  executive_summary: string;
  disclaimer: string;
}
