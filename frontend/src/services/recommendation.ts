import { apiClient } from './api';
import type { LocationRecommendationsResponse } from '../types/recommendation';

export const getRecommendationsForLocation = async (
  locationId: number,
  options?: {
    include_forecast?: boolean;
    include_alerts?: boolean;
    horizon_hours?: number;
  }
): Promise<LocationRecommendationsResponse> => {
  const response = await apiClient.get<LocationRecommendationsResponse>(
    `/recommendations/${locationId}`,
    { params: options }
  );
  return response.data;
};
