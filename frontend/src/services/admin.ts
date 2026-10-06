import { apiClient } from './api';
import type {
  AdminOverviewResponse,
  UserListResponse,
  AdminUserCreate,
  AdminUserUpdate,
  AuditLogListResponse,
  SystemSetting,
} from '../types/admin';
import type { User, UserRole } from '../types/auth';
import type { Location, DataSource, SourceType } from '../types/air_quality';

export interface AuditLogFilters {
  page?: number;
  page_size?: number;
  action?: string;
  resource_type?: string;
  user_id?: number;
  start_time?: string;
  end_time?: string;
  success?: boolean;
}

export interface UserFilters {
  page?: number;
  page_size?: number;
  role?: UserRole;
  is_active?: boolean;
  search?: string;
}

export interface DataSourceUpdatePayload {
  name?: string;
  provider?: string;
  description?: string;
  is_active?: boolean;
}

export interface DataSourceCreatePayload {
  name: string;
  source_type: SourceType;
  provider?: string;
  description?: string;
  is_active?: boolean;
}

export interface LocationCreatePayload {
  name: string;
  city: string;
  state: string;
  country?: string;
  latitude: number;
  longitude: number;
  description?: string;
  is_active?: boolean;
}

// Admin Overview
export const getAdminOverview = async (): Promise<AdminOverviewResponse> => {
  const response = await apiClient.get<AdminOverviewResponse>('/admin/overview');
  return response.data;
};

// User Administration
export const listUsers = async (filters: UserFilters = {}): Promise<UserListResponse> => {
  const response = await apiClient.get<UserListResponse>('/admin/users', { params: filters });
  return response.data;
};

export const createUserAdmin = async (payload: AdminUserCreate): Promise<User> => {
  const response = await apiClient.post<User>('/admin/users', payload);
  return response.data;
};

export const updateUserAdmin = async (userId: number, payload: AdminUserUpdate): Promise<User> => {
  const response = await apiClient.put<User>(`/admin/users/${userId}`, payload);
  return response.data;
};

// Audit Logs
export const listAuditLogs = async (filters: AuditLogFilters = {}): Promise<AuditLogListResponse> => {
  const response = await apiClient.get<AuditLogListResponse>('/admin/audit-logs', { params: filters });
  return response.data;
};

// System Settings
export const getSystemSettings = async (category?: string): Promise<SystemSetting[]> => {
  const params = category ? { category } : {};
  const response = await apiClient.get<SystemSetting[]>('/admin/settings', { params });
  return response.data;
};

export const updateSystemSetting = async (key: string, value: string): Promise<SystemSetting> => {
  const response = await apiClient.put<SystemSetting>(`/admin/settings/${key}`, { value });
  return response.data;
};

// Location Administration (authoritative domain endpoints with audit logging)
export const createLocation = async (payload: LocationCreatePayload): Promise<Location> => {
  const response = await apiClient.post<Location>('/locations', payload);
  return response.data;
};

export const updateLocation = async (locationId: number, payload: Partial<LocationCreatePayload>): Promise<Location> => {
  const response = await apiClient.put<Location>(`/locations/${locationId}`, payload);
  return response.data;
};

// Data Source Administration (authoritative domain endpoints with audit logging and locked provenance)
export const createDataSource = async (payload: DataSourceCreatePayload): Promise<DataSource> => {
  const response = await apiClient.post<DataSource>('/data-sources', payload);
  return response.data;
};

export const updateDataSource = async (sourceId: number, payload: DataSourceUpdatePayload): Promise<DataSource> => {
  const response = await apiClient.put<DataSource>(`/data-sources/${sourceId}`, payload);
  return response.data;
};
