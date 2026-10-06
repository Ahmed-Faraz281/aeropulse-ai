import type { RecommendationItem } from './recommendation';

export interface WhatIfSimulationRequest {
  location_id: number;
  reading_id?: number | null;
  pollutant_changes: Record<string, number>;
}

export interface BaselineState {
  location_id: number;
  location_name: string;
  city: string;
  timestamp: string;
  source_type: string;
  pollutant_values: Record<string, number | null>;
  pollutant_subindices: Record<string, number | null>;
  aqi?: number | null;
  category?: string | null;
  dominant_pollutant?: string | null;
}

export interface ScenarioState {
  modified_pollutant_values: Record<string, number | null>;
  pollutant_changes_percent: Record<string, number>;
  pollutant_subindices: Record<string, number | null>;
  simulated_aqi?: number | null;
  category?: string | null;
  dominant_pollutant?: string | null;
  provenance: string;
  is_valid: boolean;
  warnings: string[];
  message?: string | null;
}

export interface ThresholdImpact {
  crosses_threshold: boolean;
  rule_name?: string | null;
  threshold_value?: number | null;
  severity?: string | null;
  message?: string | null;
}

export interface ImpactAnalysis {
  aqi_delta?: number | null;
  aqi_percent_delta?: number | null;
  category_before?: string | null;
  category_after?: string | null;
  category_transition?: string | null;
  dominant_pollutant_before?: string | null;
  dominant_pollutant_after?: string | null;
  dominant_pollutant_transition?: string | null;
  direction: 'IMPROVED' | 'WORSENED' | 'UNCHANGED';
  threshold_impact?: ThresholdImpact | null;
}

export interface WhatIfSimulationResponse {
  baseline: BaselineState;
  scenario: ScenarioState;
  impact: ImpactAnalysis;
  recommendations: RecommendationItem[];
  calculation_method: string;
  generated_at: string;
  baseline_provenance: string;
  scenario_provenance: string;
  disclaimer: string;
}
