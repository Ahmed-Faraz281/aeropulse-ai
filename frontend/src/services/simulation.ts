import { apiClient } from './api';
import type {
  SimulationRequest,
  SimulationResponse,
  SimulationRunMetadata,
} from '../types/simulation';

export const runSimulation = async (
  payload: SimulationRequest
): Promise<SimulationResponse> => {
  const response = await apiClient.post<SimulationResponse>('/simulation/run', payload);
  return response.data;
};

export const getLatestSimulation = async (): Promise<SimulationRunMetadata | null> => {
  const response = await apiClient.get<SimulationRunMetadata | null>('/simulation/latest');
  return response.data;
};
