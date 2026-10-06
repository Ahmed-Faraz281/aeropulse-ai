import { apiClient } from './api';
import type {
  AnalyticsSummaryParams,
  AnomalyItem,
  AnomalyParams,
  ComparisonParams,
  EventParams,
  HotspotIndicatorItem,
  LocationAnalyticsSummary,
  LocationComparisonItem,
  PollutionEventItem,
  TimeAggregatedPoint,
  TrendParams,
} from '../types/analytics';

export const getLocationSummary = async (
  params: AnalyticsSummaryParams
): Promise<LocationAnalyticsSummary> => {
  const response = await apiClient.get<LocationAnalyticsSummary>('/analytics/summary', {
    params,
  });
  return response.data;
};

export const getAQITrend = async (params: TrendParams): Promise<TimeAggregatedPoint[]> => {
  const response = await apiClient.get<TimeAggregatedPoint[]>('/analytics/aqi-trend', {
    params,
  });
  return response.data;
};

export const getPollutantTrend = async (
  pollutant: string,
  params: TrendParams
): Promise<TimeAggregatedPoint[]> => {
  const response = await apiClient.get<TimeAggregatedPoint[]>(
    `/analytics/pollutants/${pollutant}`,
    { params }
  );
  return response.data;
};

export const getLocationComparison = async (
  params?: ComparisonParams
): Promise<LocationComparisonItem[]> => {
  const response = await apiClient.get<LocationComparisonItem[]>(
    '/analytics/location-comparison',
    { params }
  );
  return response.data;
};

export const getAnomalies = async (params: AnomalyParams): Promise<AnomalyItem[]> => {
  const response = await apiClient.get<AnomalyItem[]>('/analytics/anomalies', {
    params,
  });
  return response.data;
};

export const getPollutionEvents = async (
  params: EventParams
): Promise<PollutionEventItem[]> => {
  const response = await apiClient.get<PollutionEventItem[]>('/analytics/events', {
    params,
  });
  return response.data;
};

export const getHotspotIndicators = async (
  params?: ComparisonParams
): Promise<HotspotIndicatorItem[]> => {
  const response = await apiClient.get<HotspotIndicatorItem[]>('/analytics/hotspots', {
    params,
  });
  return response.data;
};
