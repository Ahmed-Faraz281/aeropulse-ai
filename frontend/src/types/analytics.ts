export interface MetricStatistics {
  count: number;
  mean: number | null;
  minimum: number | null;
  maximum: number | null;
  median: number | null;
  stddev: number | null;
}

export type TrendDirection =
  | 'INCREASING'
  | 'DECREASING'
  | 'STABLE'
  | 'INSUFFICIENT_DATA';

export interface LocationAnalyticsSummary {
  location_id: number;
  location_name: string;
  city: string;
  start_time?: string | null;
  end_time?: string | null;
  aqi_statistics: MetricStatistics;
  pollutant_statistics: Record<string, MetricStatistics>;
  trend_direction: TrendDirection | string;
}

export interface TimeAggregatedPoint {
  timestamp: string;
  average: number;
  maximum: number;
  count: number;
}

export interface AnomalyItem {
  timestamp: string;
  location_id?: number | null;
  metric: string;
  observed_value: number;
  expected_value: number;
  score: number;
  severity: 'LOW' | 'MEDIUM' | 'HIGH' | string;
  reason: string;
}

export interface PollutionEventItem {
  location_id?: number | null;
  start_time: string;
  end_time: string;
  duration_hours: number;
  max_aqi: number;
  dominant_pollutant?: string | null;
  increase_percentage: number;
  detection_reason: string;
}

export interface LocationComparisonItem {
  location_id: number;
  location_name: string;
  city: string;
  average_aqi: number | null;
  max_aqi: number | null;
  observation_count: number;
  dominant_pollutant?: string | null;
}

export interface HotspotIndicatorItem {
  location_id: number;
  location_name: string;
  city: string;
  mean_aqi: number | null;
  max_aqi: number | null;
  observation_count: number;
  high_pollution_hours: number;
  event_count: number;
}

export interface AnalyticsSummaryParams {
  location_id: number;
  start_time?: string;
  end_time?: string;
}

export interface TrendParams {
  location_id: number;
  aggregation?: 'hourly' | 'daily' | 'weekly' | 'monthly';
  start_time?: string;
  end_time?: string;
  limit?: number;
}

export interface AnomalyParams {
  location_id: number;
  metric?: string;
  method?: 'zscore' | 'iqr';
  threshold?: number;
  start_time?: string;
  end_time?: string;
}

export interface EventParams {
  location_id: number;
  aqi_threshold?: number;
  min_duration_hours?: number;
  start_time?: string;
  end_time?: string;
}

export interface ComparisonParams {
  start_time?: string;
  end_time?: string;
}
