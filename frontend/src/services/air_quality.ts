import { apiClient } from './api';
import type {
  Location,
  DataSource,
  AirQualityReading,
  CurrentReadingResponse,
  SourceType,
  QualityStatus,
} from '../types/air_quality';

export const getLocations = async (city?: string): Promise<Location[]> => {
  const params = city ? { city } : {};
  const response = await apiClient.get<Location[]>('/locations', { params });
  return response.data;
};

export const getDataSources = async (source_type?: SourceType): Promise<DataSource[]> => {
  const params = source_type ? { source_type } : {};
  const response = await apiClient.get<DataSource[]>('/data-sources', { params });
  return response.data;
};

export const getCurrentReading = async (locationId: number): Promise<CurrentReadingResponse> => {
  const response = await apiClient.get<CurrentReadingResponse>('/air-quality/current', {
    params: { location_id: locationId },
  });
  return response.data;
};

export interface HistoryQueryFilters {
  location_id?: number;
  start_time?: string;
  end_time?: string;
  source_type?: SourceType;
  quality_status?: QualityStatus;
  limit?: number;
}

export const getHistoricalReadings = async (
  filters: HistoryQueryFilters = {}
): Promise<AirQualityReading[]> => {
  const response = await apiClient.get<AirQualityReading[]>('/air-quality/history', {
    params: filters,
  });
  return response.data;
};
