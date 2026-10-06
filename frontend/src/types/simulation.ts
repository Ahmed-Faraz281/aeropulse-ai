export type SimulationScenario =
  | 'NORMAL'
  | 'RISING_POLLUTION'
  | 'POLLUTION_SPIKE'
  | 'PERSISTENT_ELEVATED'
  | 'RECOVERY';

export interface SimulationRequest {
  location_ids: number[];
  duration_hours: number;
  interval_minutes: number;
  scenario: SimulationScenario;
  intensity: number;
  seed?: number | null;
}

export interface SimulationResponse {
  status: string;
  source_type: string;
  locations: number;
  readings_generated: number;
  readings_inserted: number;
  readings_skipped: number;
  scenario: SimulationScenario;
  started_at: string;
  completed_at: string;
  duration_seconds: number;
  seed?: number | null;
}

export interface SimulationRunMetadata {
  scenario: SimulationScenario;
  location_count: number;
  readings_generated: number;
  readings_inserted: number;
  readings_skipped: number;
  started_at: string;
  completed_at: string;
  seed?: number | null;
}
