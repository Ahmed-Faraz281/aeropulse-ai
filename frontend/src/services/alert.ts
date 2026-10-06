import { apiClient } from './api';
import type {
  Alert,
  AlertEvaluationResponse,
  AlertRule,
  AlertRuleCreate,
} from '../types/alert';

export const getAlertRules = async (): Promise<AlertRule[]> => {
  const response = await apiClient.get<AlertRule[]>('/alerts/rules');
  return response.data;
};

export const createAlertRule = async (payload: AlertRuleCreate): Promise<AlertRule> => {
  const response = await apiClient.post<AlertRule>('/alerts/rules', payload);
  return response.data;
};

export const updateAlertRule = async (
  ruleId: number,
  payload: Partial<AlertRuleCreate>
): Promise<AlertRule> => {
  const response = await apiClient.put<AlertRule>(`/alerts/rules/${ruleId}`, payload);
  return response.data;
};

export const deleteAlertRule = async (ruleId: number): Promise<void> => {
  await apiClient.delete(`/alerts/rules/${ruleId}`);
};

export const getAlerts = async (params?: {
  location_id?: number;
  severity?: string;
  alert_type?: string;
  status?: string;
  source_type?: string;
  limit?: number;
}): Promise<Alert[]> => {
  const response = await apiClient.get<Alert[]>('/alerts', { params });
  return response.data;
};

export const getActiveAlerts = async (locationId?: number): Promise<Alert[]> => {
  const params = locationId ? { location_id: locationId } : undefined;
  const response = await apiClient.get<Alert[]>('/alerts/active', { params });
  return response.data;
};

export const evaluateLocationAlerts = async (
  locationId: number
): Promise<AlertEvaluationResponse> => {
  const response = await apiClient.post<AlertEvaluationResponse>(
    `/alerts/evaluate/${locationId}`
  );
  return response.data;
};

export const acknowledgeAlert = async (alertId: number): Promise<Alert> => {
  const response = await apiClient.post<Alert>(`/alerts/${alertId}/acknowledge`);
  return response.data;
};

export const resolveAlert = async (alertId: number): Promise<Alert> => {
  const response = await apiClient.post<Alert>(`/alerts/${alertId}/resolve`);
  return response.data;
};
