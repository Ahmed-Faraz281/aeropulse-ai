import { apiClient } from './api';
import type {
  AutomationActionResponse,
  AutomationStatusResponse,
  AutomationTriggerResponse,
} from '../types/automation';

export async function getAutomationStatus(): Promise<AutomationStatusResponse> {
  const response = await apiClient.get<AutomationStatusResponse>('/automation/status');
  return response.data;
}

export async function triggerAutomationCycle(): Promise<AutomationTriggerResponse> {
  const response = await apiClient.post<AutomationTriggerResponse>('/automation/trigger');
  return response.data;
}

export async function pauseAutomationScheduler(): Promise<AutomationActionResponse> {
  const response = await apiClient.post<AutomationActionResponse>('/automation/pause');
  return response.data;
}

export async function resumeAutomationScheduler(): Promise<AutomationActionResponse> {
  const response = await apiClient.post<AutomationActionResponse>('/automation/resume');
  return response.data;
}
