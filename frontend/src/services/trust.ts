import { apiClient } from './api';
import type { StationTrustResponse, SystemTrustOverview } from '../types/trust';

export async function getStationTrust(locationId: number): Promise<StationTrustResponse> {
  const response = await apiClient.get<StationTrustResponse>(`/trust/station/${locationId}`);
  return response.data;
}

export async function getSystemTrustOverview(): Promise<SystemTrustOverview> {
  const response = await apiClient.get<SystemTrustOverview>('/trust/overview');
  return response.data;
}
