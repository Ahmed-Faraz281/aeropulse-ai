import { apiClient } from './api';
import type { AQIResponse, AQIHistoryParams } from '../types/aqi';

export const getLatestAQI = async (locationId: number): Promise<AQIResponse> => {
  const response = await apiClient.get<AQIResponse>(`/aqi/${locationId}`);
  return response.data;
};

export const getAQIHistory = async (
  locationId: number,
  params?: AQIHistoryParams
): Promise<AQIResponse[]> => {
  const response = await apiClient.get<AQIResponse[]>(`/aqi/${locationId}/history`, {
    params,
  });
  return response.data;
};
