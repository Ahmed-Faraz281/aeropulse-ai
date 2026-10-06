import { apiClient } from './api';
import type {
  PredictionRequest,
  PredictionResponse,
  PredictionTrainRequest,
  PredictionTrainResponse,
} from '../types/prediction';

export const trainPredictionModel = async (
  payload: PredictionTrainRequest
): Promise<PredictionTrainResponse> => {
  const response = await apiClient.post<PredictionTrainResponse>('/prediction/train', payload);
  return response.data;
};

export const runPrediction = async (
  payload: PredictionRequest
): Promise<PredictionResponse> => {
  const response = await apiClient.post<PredictionResponse>('/prediction/predict', payload);
  return response.data;
};

export const getLatestPredictions = async (
  locationId: number
): Promise<PredictionResponse[]> => {
  const response = await apiClient.get<PredictionResponse[]>(`/prediction/${locationId}/latest`);
  return response.data;
};

export const getPredictionHistory = async (
  locationId: number,
  limit: number = 20
): Promise<PredictionResponse[]> => {
  const response = await apiClient.get<PredictionResponse[]>(
    `/prediction/${locationId}/history?limit=${limit}`
  );
  return response.data;
};
