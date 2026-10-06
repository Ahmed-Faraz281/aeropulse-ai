export interface AutomationCycleSummary {
  cycle_id: string;
  started_at: string;
  completed_at?: string | null;
  duration_seconds: number;
  status: 'success' | 'partial_success' | 'error' | 'skipped' | 'backoff';
  stations_processed: number;
  stations_failed: number;
  observations_ingested: number;
  predictions_generated: number;
  models_retrained: boolean;
  errors: string[];
}

export interface AutomationStatusResponse {
  status: 'DISABLED' | 'STARTING' | 'RUNNING' | 'IDLE' | 'PAUSED' | 'BACKOFF' | 'ERROR';
  enabled: boolean;
  paused: boolean;
  last_run?: string | null;
  next_run?: string | null;
  last_run_duration_seconds?: number | null;
  observations_ingested: number;
  predictions_generated: number;
  models_retrained: boolean;
  stations_processed: number;
  stations_failed: number;
  active_stations_count: number;
  last_error?: string | null;
  backoff_until?: string | null;
  poll_interval_minutes: number;
  recent_cycles: AutomationCycleSummary[];
}

export interface AutomationTriggerResponse {
  status: string;
  message: string;
  started_at?: string | null;
}

export interface AutomationActionResponse {
  status: string;
  message: string;
  paused: boolean;
}
