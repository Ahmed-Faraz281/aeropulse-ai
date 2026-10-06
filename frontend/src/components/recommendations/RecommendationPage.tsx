import React, { useState, useEffect, useCallback } from 'react';
import type { User } from '../../types/auth';
import type { Location } from '../../types/air_quality';
import type {
  LocationRecommendationsResponse,
  RecommendationItem,
  RecommendationPriority,
  RecommendationType,
} from '../../types/recommendation';
import { getLocations } from '../../services/air_quality';
import { getRecommendationsForLocation } from '../../services/recommendation';
import {
  Sparkles,
  ShieldAlert,
  ShieldCheck,
  RefreshCw,
  MapPin,
  Clock,
  ArrowRight,
  TrendingUp,
  TrendingDown,
  Minus,
  Activity,
  Wind,
  Home,
  AlertCircle,
  Filter,
  BrainCircuit,
  Bell,
  CheckCircle2,
  Sliders,
} from 'lucide-react';

interface RecommendationPageProps {
  currentUser: User;
  onNavigateToTab?: (tabId: string) => void;
  onNavigateToDashboard?: (locationId: number) => void;
}

const PRIORITY_THEMES: Record<
  RecommendationPriority,
  { bg: string; text: string; border: string; glow: string; badge: string }
> = {
  CRITICAL: {
    bg: 'bg-rose-950/30',
    text: 'text-rose-300',
    border: 'border-rose-500/40',
    glow: 'from-rose-500/10',
    badge: 'bg-rose-500/20 text-rose-300 border-rose-500/30',
  },
  HIGH: {
    bg: 'bg-amber-950/30',
    text: 'text-amber-300',
    border: 'border-amber-500/40',
    glow: 'from-amber-500/10',
    badge: 'bg-amber-500/20 text-amber-300 border-amber-500/30',
  },
  MEDIUM: {
    bg: 'bg-indigo-950/30',
    text: 'text-indigo-300',
    border: 'border-indigo-500/30',
    glow: 'from-indigo-500/10',
    badge: 'bg-indigo-500/20 text-indigo-300 border-indigo-500/30',
  },
  LOW: {
    bg: 'bg-blue-950/20',
    text: 'text-blue-300',
    border: 'border-blue-500/30',
    glow: 'from-blue-500/10',
    badge: 'bg-blue-500/20 text-blue-300 border-blue-500/30',
  },
  INFO: {
    bg: 'bg-slate-900/40',
    text: 'text-teal-300',
    border: 'border-slate-800',
    glow: 'from-teal-500/5',
    badge: 'bg-teal-500/15 text-teal-300 border-teal-500/30',
  },
};

const TYPE_ICONS: Record<RecommendationType, React.ElementType> = {
  OUTDOOR_ACTIVITY: Activity,
  VENTILATION: Wind,
  INDOOR_AIR: Home,
  EXPOSURE_REDUCTION: ShieldAlert,
  MASK_GUIDANCE: AlertCircle,
  TRAVEL_TIMING: Clock,
  HIGH_RISK_GROUP_CAUTION: AlertCircle,
  POLLUTANT_SPECIFIC: Sparkles,
  FORECAST_PREVENTION: BrainCircuit,
  ALERT_RESPONSE: Bell,
};

export const RecommendationPage: React.FC<RecommendationPageProps> = ({
  currentUser: _currentUser,
  onNavigateToTab,
  onNavigateToDashboard,
}) => {
  const [locations, setLocations] = useState<Location[]>([]);
  const [selectedLocationId, setSelectedLocationId] = useState<number | null>(null);
  const [loadingLocations, setLoadingLocations] = useState(true);

  const [data, setData] = useState<LocationRecommendationsResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Filters
  const [priorityFilter, setPriorityFilter] = useState<string>('ALL');
  const [typeFilter, setTypeFilter] = useState<string>('ALL');

  // Load locations on mount
  useEffect(() => {
    let ignore = false;
    const fetchLocs = async () => {
      setLoadingLocations(true);
      try {
        const locs = await getLocations();
        if (!ignore) {
          setLocations(locs);
          if (locs.length > 0) {
            setSelectedLocationId(locs[0].id);
          }
        }
      } catch {
        if (!ignore) {
          setError('Unable to load monitoring stations. Please check backend connection.');
        }
      } finally {
        if (!ignore) {
          setLoadingLocations(false);
        }
      }
    };
    Promise.resolve().then(fetchLocs);
    return () => {
      ignore = true;
    };
  }, []);

  // Fetch recommendations for selected location
  const loadRecommendations = useCallback(async () => {
    if (!selectedLocationId) return;
    setLoading(true);
    setError(null);
    try {
      const res = await getRecommendationsForLocation(selectedLocationId, {
        include_forecast: true,
        include_alerts: true,
      });
      setData(res);
    } catch {
      setError('Failed to evaluate recommendations for this station.');
    } finally {
      setLoading(false);
    }
  }, [selectedLocationId]);

  useEffect(() => {
    let ignore = false;
    if (selectedLocationId) {
      Promise.resolve().then(() => {
        if (!ignore) {
          loadRecommendations();
        }
      });
    }
    return () => {
      ignore = true;
    };
  }, [selectedLocationId, loadRecommendations]);

  const filteredRecommendations = (data?.recommendations || []).filter((r: RecommendationItem) => {
    if (priorityFilter !== 'ALL' && r.priority !== priorityFilter) return false;
    if (typeFilter !== 'ALL' && r.type !== typeFilter) return false;
    return true;
  });

  return (
    <div className="space-y-6">
      {/* Header & Station Selector */}
      <div className="p-5 rounded-2xl bg-slate-900/80 border border-slate-800 shadow-xl flex flex-col lg:flex-row lg:items-center justify-between gap-4">
        <div className="space-y-1">
          <div className="flex items-center gap-2">
            <div className="p-1.5 rounded-lg bg-teal-500/20 text-teal-400">
              <Sparkles className="w-4 h-4" />
            </div>
            <span className="text-[11px] font-bold uppercase tracking-wider text-teal-400 font-mono">
              Phase 11 Prevention Engine
            </span>
          </div>
          <h2 className="text-xl font-bold text-white tracking-tight">
            Explainable Prevention & Health-Aware Recommendations
          </h2>
          <p className="text-xs text-slate-400">
            Deterministic, rule-based recommendations derived from current AQI, dominant pollutants, trends, ML forecasts, and active alerts.
          </p>
        </div>

        <div className="flex flex-wrap items-center gap-3 self-start lg:self-auto">
          {/* Station selector */}
          <div className="flex items-center gap-2 bg-slate-950/70 px-3 py-2 rounded-xl border border-slate-800">
            <MapPin className="w-4 h-4 text-teal-400 shrink-0" />
            <div className="flex flex-col">
              <span className="text-[10px] text-slate-500 font-semibold uppercase tracking-wider">
                Station
              </span>
              <select
                aria-label="Select Monitored Station"
                value={selectedLocationId || ''}
                onChange={(e) => setSelectedLocationId(Number(e.target.value))}
                disabled={loadingLocations || loading}
                className="bg-transparent text-xs font-semibold text-slate-200 outline-none cursor-pointer pr-4"
              >
                {locations.map((loc) => (
                  <option key={loc.id} value={loc.id} className="bg-slate-900 text-slate-200">
                    {loc.name} ({loc.city})
                  </option>
                ))}
              </select>
            </div>
          </div>

          <button
            onClick={loadRecommendations}
            disabled={loading}
            className="inline-flex items-center gap-2 px-3.5 py-2.5 rounded-xl bg-slate-800 hover:bg-slate-700 text-slate-200 text-xs font-medium border border-slate-700 transition disabled:opacity-50"
          >
            <RefreshCw className={`w-3.5 h-3.5 ${loading ? 'animate-spin' : ''}`} />
            <span>Re-evaluate</span>
          </button>

          {onNavigateToTab && (
            <button
              onClick={() => onNavigateToTab('whatif')}
              className="inline-flex items-center gap-1.5 px-3.5 py-2.5 rounded-xl bg-teal-500/10 hover:bg-teal-500/20 text-teal-300 text-xs font-semibold border border-teal-500/30 transition"
              title="Explore What-If Simulation Impact"
            >
              <Sliders className="w-3.5 h-3.5" />
              <span>Explore What-If Impact</span>
            </button>
          )}
        </div>
      </div>

      {/* Medical Safety Disclaimer Banner */}
      <div className="p-4 rounded-xl bg-blue-500/10 border border-blue-500/20 flex items-start gap-3 text-xs text-blue-200">
        <ShieldCheck className="w-4 h-4 text-blue-400 shrink-0 mt-0.5" />
        <div className="space-y-0.5">
          <span className="font-semibold text-blue-300">Public Health & Safety Notice: </span>
          <span>{data?.disclaimer || 'Recommendations are informational and based on available air-quality data. They are not medical advice.'}</span>
        </div>
      </div>

      {/* Error Banner */}
      {error && (
        <div className="p-4 rounded-xl bg-rose-500/10 border border-rose-500/20 text-rose-300 text-xs flex items-center justify-between">
          <div className="flex items-center gap-2">
            <ShieldAlert className="w-4 h-4 shrink-0 text-rose-400" />
            <span>{error}</span>
          </div>
          <button onClick={loadRecommendations} className="underline hover:text-white">
            Retry
          </button>
        </div>
      )}

      {/* Current Assessment Context Overview */}
      {data && (
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4">
          {/* Current AQI Card */}
          <div className="p-4 rounded-xl bg-slate-900/60 border border-slate-800 space-y-2">
            <div className="flex items-center justify-between text-xs text-slate-400">
              <span>Observed AQI</span>
              <span className="font-mono text-[10px] text-slate-500">CPCB NAQI</span>
            </div>
            <div className="flex items-baseline gap-2">
              <span className="text-3xl font-extrabold text-white">
                {data.current_aqi !== null && data.current_aqi !== undefined ? data.current_aqi : 'N/A'}
              </span>
              {data.current_category && (
                <span className="px-2 py-0.5 rounded-full text-xs font-bold bg-teal-500/20 text-teal-300 border border-teal-500/30">
                  {data.current_category}
                </span>
              )}
            </div>
            <p className="text-[11px] text-slate-500">
              Source: <span className="font-mono text-slate-400 uppercase">{data.source_type}</span>
              {data.has_simulated_data && (
                <span className="ml-1.5 px-1.5 py-0.2 rounded text-[9px] bg-amber-500/20 text-amber-300 border border-amber-500/30">
                  SIMULATED
                </span>
              )}
            </p>
          </div>

          {/* Dominant Pollutant Card */}
          <div className="p-4 rounded-xl bg-slate-900/60 border border-slate-800 space-y-2">
            <div className="flex items-center justify-between text-xs text-slate-400">
              <span>Dominant Pollutant</span>
              <Sparkles className="w-3.5 h-3.5 text-teal-400" />
            </div>
            <div className="text-2xl font-bold text-teal-300">
              {data.dominant_pollutant ? data.dominant_pollutant.toUpperCase() : 'None Identified'}
            </div>
            <p className="text-[11px] text-slate-500">
              Primary driver of the current AQI sub-index.
            </p>
          </div>

          {/* Trend Trajectory Card */}
          <div className="p-4 rounded-xl bg-slate-900/60 border border-slate-800 space-y-2">
            <div className="flex items-center justify-between text-xs text-slate-400">
              <span>Trend Trajectory</span>
              {data.trend === 'INCREASING' ? (
                <TrendingUp className="w-3.5 h-3.5 text-rose-400" />
              ) : data.trend === 'DECREASING' ? (
                <TrendingDown className="w-3.5 h-3.5 text-emerald-400" />
              ) : (
                <Minus className="w-3.5 h-3.5 text-slate-400" />
              )}
            </div>
            <div className="text-2xl font-bold text-white flex items-center gap-2">
              <span>{data.trend || 'STABLE'}</span>
            </div>
            <p className="text-[11px] text-slate-500">
              {data.trend === 'INCREASING'
                ? 'Pollutant accumulation observed.'
                : data.trend === 'DECREASING'
                ? 'Atmospheric clearance underway.'
                : 'Steady concentration levels.'}
            </p>
          </div>

          {/* Alert Status Card */}
          <div className="p-4 rounded-xl bg-slate-900/60 border border-slate-800 space-y-2">
            <div className="flex items-center justify-between text-xs text-slate-400">
              <span>Active Threshold Alerts</span>
              <Bell className="w-3.5 h-3.5 text-amber-400" />
            </div>
            <div className="flex items-baseline gap-2">
              <span className="text-3xl font-extrabold text-white">
                {data.active_alerts_count}
              </span>
              <span className="text-xs text-slate-400">Active</span>
            </div>
            {onNavigateToTab && data.active_alerts_count > 0 ? (
              <button
                onClick={() => onNavigateToTab('alerts')}
                className="text-[11px] text-teal-400 hover:text-teal-300 font-semibold flex items-center gap-1"
              >
                <span>Inspect in Alert Center</span>
                <ArrowRight className="w-3 h-3" />
              </button>
            ) : (
              <p className="text-[11px] text-slate-500">No active threshold alerts.</p>
            )}
          </div>
        </div>
      )}

      {/* Forecast-Aware Preemption Card (if prediction available) */}
      {data?.forecast_summary && (
        <div className="p-4 rounded-2xl bg-gradient-to-r from-indigo-950/40 via-purple-950/30 to-slate-900/60 border border-indigo-500/30 shadow-lg flex flex-col md:flex-row md:items-center justify-between gap-4">
          <div className="flex items-center gap-3">
            <div className="p-2.5 rounded-xl bg-indigo-500/20 text-indigo-300">
              <BrainCircuit className="w-5 h-5" />
            </div>
            <div className="space-y-0.5">
              <div className="flex items-center gap-2">
                <span className="text-xs font-bold uppercase tracking-wider text-indigo-300">
                  ML-Predicted Trajectory ({data.forecast_summary.horizon_hours}h Ahead)
                </span>
                <span className="px-2 py-0.2 rounded text-[10px] font-bold bg-indigo-500/20 text-indigo-200 border border-indigo-500/30">
                  FORECAST-BASED
                </span>
              </div>
              <p className="text-xs text-slate-300">
                Current AQI {data.current_aqi ?? 'N/A'} is projected to reach{' '}
                <span className="font-bold text-white">
                  {data.forecast_summary.predicted_aqi.toFixed(0)} ({data.forecast_summary.predicted_category})
                </span>{' '}
                within {data.forecast_summary.horizon_hours} hours.
              </p>
            </div>
          </div>

          {onNavigateToTab && (
            <button
              onClick={() => onNavigateToTab('predictions')}
              className="inline-flex items-center gap-1.5 px-3.5 py-2 rounded-xl bg-indigo-500/20 hover:bg-indigo-500/30 text-indigo-200 text-xs font-semibold border border-indigo-500/30 transition self-start md:self-auto shrink-0"
            >
              <span>Inspect ML Forecast</span>
              <ArrowRight className="w-3.5 h-3.5" />
            </button>
          )}
        </div>
      )}

      {/* Filter Toolbar */}
      <div className="flex flex-wrap items-center justify-between gap-3 p-3 rounded-xl bg-slate-900/60 border border-slate-800">
        <div className="flex flex-wrap items-center gap-2">
          <div className="flex items-center gap-1.5 text-xs text-slate-400 mr-2">
            <Filter className="w-3.5 h-3.5" />
            <span>Priority:</span>
          </div>
          {['ALL', 'CRITICAL', 'HIGH', 'MEDIUM', 'LOW', 'INFO'].map((prio) => (
            <button
              key={prio}
              onClick={() => setPriorityFilter(prio)}
              className={`px-2.5 py-1 rounded-lg text-xs font-semibold transition ${
                priorityFilter === prio
                  ? 'bg-teal-500 text-slate-950 shadow-sm'
                  : 'text-slate-400 hover:text-white bg-slate-800/40'
              }`}
            >
              {prio}
            </button>
          ))}
        </div>

        <div className="flex items-center gap-2">
          <span className="text-xs text-slate-400">Type:</span>
          <select
            value={typeFilter}
            onChange={(e) => setTypeFilter(e.target.value)}
            className="bg-slate-950 px-2.5 py-1 rounded-lg border border-slate-800 text-xs text-slate-200 outline-none"
          >
            <option value="ALL">All Recommendation Types</option>
            <option value="OUTDOOR_ACTIVITY">Outdoor Activity</option>
            <option value="VENTILATION">Ventilation</option>
            <option value="INDOOR_AIR">Indoor Air</option>
            <option value="EXPOSURE_REDUCTION">Exposure Reduction</option>
            <option value="MASK_GUIDANCE">Mask Guidance</option>
            <option value="POLLUTANT_SPECIFIC">Pollutant Specific</option>
            <option value="FORECAST_PREVENTION">Forecast Prevention</option>
            <option value="ALERT_RESPONSE">Alert Response</option>
          </select>
        </div>
      </div>

      {/* Prioritized Recommendation Cards */}
      <div className="space-y-4">
        {loading && (
          <div className="p-8 text-center text-slate-400 flex items-center justify-center gap-2">
            <RefreshCw className="w-4 h-4 animate-spin text-teal-400" />
            <span className="text-xs">Evaluating deterministic rules and forecasts...</span>
          </div>
        )}

        {!loading && filteredRecommendations.length === 0 && (
          <div className="p-8 rounded-2xl bg-slate-900/40 border border-slate-800 text-center space-y-2">
            <CheckCircle2 className="w-8 h-8 text-teal-400 mx-auto" />
            <h4 className="text-sm font-semibold text-slate-200">No Recommendations Match Current Filter</h4>
            <p className="text-xs text-slate-400">
              Clear active filters or re-evaluate the station to inspect all available preventive guidance.
            </p>
          </div>
        )}

        {!loading &&
          filteredRecommendations.map((rec: RecommendationItem) => {
            const theme = PRIORITY_THEMES[rec.priority] || PRIORITY_THEMES.INFO;
            const Icon = TYPE_ICONS[rec.type] || Sparkles;

            return (
              <div
                key={rec.id}
                className={`p-5 rounded-2xl border ${theme.border} ${theme.bg} shadow-lg relative overflow-hidden transition hover:border-slate-700`}
              >
                <div
                  className={`absolute -right-16 -top-16 w-36 h-36 bg-gradient-to-br ${theme.glow} to-transparent rounded-full blur-2xl pointer-events-none`}
                />

                <div className="flex flex-col md:flex-row md:items-start justify-between gap-4 relative z-10">
                  <div className="flex items-start gap-3.5 flex-1">
                    <div className={`p-2.5 rounded-xl border ${theme.border} bg-slate-950/60 shrink-0 mt-0.5`}>
                      <Icon className={`w-5 h-5 ${theme.text}`} />
                    </div>

                    <div className="space-y-2 flex-1">
                      <div className="flex flex-wrap items-center gap-2">
                        <span className={`px-2 py-0.5 rounded text-[10px] font-bold uppercase tracking-wider border ${theme.badge}`}>
                          {rec.priority}
                        </span>
                        <span className="px-2 py-0.5 rounded text-[10px] font-mono text-slate-400 bg-slate-900 border border-slate-800">
                          {rec.type.replace(/_/g, ' ')}
                        </span>
                        {rec.forecast_based && (
                          <span className="px-2 py-0.5 rounded text-[10px] font-bold bg-indigo-500/20 text-indigo-300 border border-indigo-500/30">
                            FORECAST-BASED
                          </span>
                        )}
                        <span className="text-[10px] text-slate-500 font-mono">
                          Source: {rec.source_type}
                        </span>
                      </div>

                      <h3 className="text-base font-bold text-white tracking-tight">
                        {rec.title}
                      </h3>

                      {/* Action Callout */}
                      <div className="p-3 rounded-xl bg-slate-950/70 border border-slate-800/80 text-xs text-slate-200 font-medium">
                        <span className="text-teal-400 font-bold mr-1.5">Action:</span>
                        {rec.action}
                      </div>

                      {/* Explainability Block */}
                      <div className="p-3 rounded-xl bg-slate-900/60 border border-slate-800 text-xs text-slate-400 space-y-1">
                        <div className="flex items-center gap-2">
                          <span className="text-[11px] font-bold text-slate-300 uppercase tracking-wider font-mono">
                            Explainability Reason:
                          </span>
                          <span className="text-[10px] px-1.5 py-0.2 rounded bg-slate-800 text-slate-300 font-mono">
                            Trigger: {rec.triggered_by}
                          </span>
                        </div>
                        <p className="text-xs text-slate-300 leading-relaxed">
                          {rec.reason}
                        </p>
                      </div>
                    </div>
                  </div>

                  {onNavigateToDashboard && (
                    <button
                      onClick={() => onNavigateToDashboard(rec.location_id)}
                      className="inline-flex items-center gap-1.5 text-xs text-slate-400 hover:text-teal-300 transition shrink-0 self-end md:self-start pt-1"
                    >
                      <span>Station Telemetry</span>
                      <ArrowRight className="w-3.5 h-3.5" />
                    </button>
                  )}
                </div>
              </div>
            );
          })}
      </div>

      {/* Software-Only Architecture Notice */}
      <div className="p-5 rounded-2xl bg-slate-900/40 border border-slate-800 space-y-2 text-xs text-slate-400">
        <div className="flex items-center gap-2 text-slate-300 font-semibold text-xs">
          <ShieldAlert className="w-4 h-4 text-amber-400 shrink-0" />
          <span>Pure Software Positioning & Non-Medical Safeguard</span>
        </div>
        <p className="leading-relaxed text-[11px] text-slate-400">
          AeroPulse AI operates as an advanced analytical modeling software. Recommendations are generated
          algorithmically from published CPCB standards, ambient monitoring stations, and validated machine learning
          forecasts. No hardware sensors are physically installed at the user's immediate premises, and guidance does
          not constitute a personal clinical diagnosis.
        </p>
      </div>
    </div>
  );
};
