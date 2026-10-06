import type { User, UserRole } from './auth';

export interface UserListResponse {
  items: User[];
  total: number;
  page: number;
  page_size: number;
  total_pages: number;
}

export interface AdminUserCreate {
  username: string;
  email: string;
  password: string;
  role: UserRole;
  is_active?: boolean;
}

export interface AdminUserUpdate {
  email?: string;
  role?: UserRole;
  is_active?: boolean;
}

export interface AuditLog {
  id: number;
  timestamp: string;
  user_id?: number | null;
  username_snapshot: string;
  action: string;
  resource_type: string;
  resource_id?: string | null;
  description: string;
  old_value?: Record<string, any> | null;
  new_value?: Record<string, any> | null;
  ip_address?: string | null;
  user_agent?: string | null;
  success: boolean;
  metadata_json?: Record<string, any> | null;
}

export interface AuditLogListResponse {
  items: AuditLog[];
  total: number;
  page: number;
  page_size: number;
  total_pages: number;
}

export type SettingCategory = 'GENERAL' | 'AQI_STANDARDS' | 'ANALYTICS' | 'PREDICTION' | 'REPORTING';

export interface SystemSetting {
  id: number;
  key: string;
  value: string;
  value_type: 'STRING' | 'INT' | 'FLOAT' | 'BOOLEAN' | 'JSON';
  description?: string | null;
  category: SettingCategory;
  is_sensitive: boolean;
  updated_by?: string | null;
  updated_at: string;
}

export interface UserStats {
  total: number;
  active: number;
  inactive: number;
  by_role: Record<string, number>;
}

export interface LocationStats {
  total: number;
  active: number;
  inactive: number;
}

export interface DataSourceStats {
  total: number;
  active: number;
  by_type: Record<string, number>;
}

export interface AlertRuleStats {
  total: number;
  enabled: number;
  disabled: number;
}

export interface SystemStatusInfo {
  app_name: string;
  version: string;
  environment: string;
  database_connected: boolean;
  database_dialect: string;
}

export interface AdminOverviewResponse {
  users: UserStats;
  locations: LocationStats;
  data_sources: DataSourceStats;
  alert_rules: AlertRuleStats;
  system_status: SystemStatusInfo;
  recent_audit_logs: AuditLog[];
}
