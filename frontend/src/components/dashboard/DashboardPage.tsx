import React, { useState, useEffect, useCallback } from 'react';
import type { User } from '../../types/auth';
import type { Location, AirQualityReading } from '../../types/air_quality';
import type { AQIResponse } from '../../types/aqi';
import type {
  LocationAnalyticsSummary,
  TimeAggregatedPoint,
  AnomalyItem,
  PollutionEventItem,
  LocationComparisonItem,
  HotspotIndicatorItem,
} from '../../types/analytics';
import { getLocations, getCurrentReading } from '../../services/air_quality';
import { getLatestAQI } from '../../services/aqi';
import {
  getLocationSummary,
  getAQITrend,
  getPollutantTrend,
  getLocationComparison,
  getAnomalies,
  getPollutionEvents,
  getHotspotIndicators,
} from '../../services/analytics';
import { CurrentAQICard } from './CurrentAQICard';
import { PollutantOverview } from './PollutantOverview';
import { AQITrendChart } from './AQITrendChart';
import { PollutantTrendChart } from './PollutantTrendChart';
import { AnalyticsSummaryCard } from './AnalyticsSummaryCard';
import { AnomaliesTable } from './AnomaliesTable';
import { PollutionEventsTable } from './PollutionEventsTable';
import { LocationComparisonTable } from './LocationComparisonTable';
import { HotspotIndicatorsTable } from './HotspotIndicatorsTable';
import { SystemTrustPanel } from './SystemTrustPanel';
import type { Alert } from '../../types/alert';
import { getActiveAlerts } from '../../services/alert';
import type { RecommendationItem } from '../../types/recommendation';
import { getRecommendationsForLocation } from '../../services/recommendation';
import { getStationTrust } from '../../services/trust';
import type { StationTrustResponse } from '../../types/trust';
import {
  resolveLocationWorkflow,
  type LocationWorkflowResponse,
} from '../../services/locationWorkflow';
import { getAutomationStatus } from '../../services/automation';
import type { AutomationStatusResponse } from '../../types/automation';
import { getAQICategoryStyle } from '../../utils/aqiFormatters';
import {
  MapPin,
  Clock,
  RefreshCw,
  AlertTriangle,
  Layers,
  ShieldCheck,
  ShieldAlert,
  Bell,
  ArrowRight,
  Sparkles,
  Sliders,
  LocateFixed,
  Loader2,
  CheckCircle2,
  XCircle,
  TrendingUp,
  X,
} from 'lucide-react';

interface DashboardPageProps {
  currentUser?: User | null;
  initialSelectedLocationId?: number | null;
  onNavigateToTab?: (tabId: string) => void;
}

type TimeRangeKey = '24h' | '48h' | '7d' | '30d';

const TIME_RANGES: { key: TimeRangeKey; label: string; hours: number }[] = [
  { key: '24h', label: 'Last 24 Hours', hours: 24 },
  { key: '48h', label: 'Last 48 Hours', hours: 48 },
  { key: '7d', label: 'Last 7 Days', hours: 168 },
  { key: '30d', label: 'Last 30 Days', hours: 720 },
];

export const DashboardPage: React.FC<DashboardPageProps> = ({
  currentUser: _currentUser,
  initialSelectedLocationId,
  onNavigateToTab,
}) => {
  // Selection State
  const [locations, setLocations] = useState<Location[]>([]);
  const [selectedLocationId, setSelectedLocationId] = useState<number | null>(
    initialSelectedLocationId || null
  );

  useEffect(() => {
    let ignore = false;
    if (initialSelectedLocationId) {
      Promise.resolve().then(() => {
        if (!ignore) {
          setSelectedLocationId(initialSelectedLocationId);
        }
      });
    }
    return () => {
      ignore = true;
    };
  }, [initialSelectedLocationId]);
  const [timeRange, setTimeRange] = useState<TimeRangeKey>('7d');
  const [aqiAggregation, setAqiAggregation] = useState<'hourly' | 'daily' | 'weekly'>('hourly');
  const [pollutantAggregation, setPollutantAggregation] = useState<'hourly' | 'daily' | 'weekly'>(
    'hourly'
  );
  const [selectedPollutant, setSelectedPollutant] = useState<string>('pm25');

  // Data State
  const [currentReading, setCurrentReading] = useState<AirQualityReading | null>(null);
  const [latestAQI, setLatestAQI] = useState<AQIResponse | null>(null);
  const [aqiTrend, setAqiTrend] = useState<TimeAggregatedPoint[]>([]);
  const [pollutantTrend, setPollutantTrend] = useState<TimeAggregatedPoint[]>([]);
  const [summary, setSummary] = useState<LocationAnalyticsSummary | null>(null);
  const [anomalies, setAnomalies] = useState<AnomalyItem[]>([]);
  const [events, setEvents] = useState<PollutionEventItem[]>([]);
  const [comparison, setComparison] = useState<LocationComparisonItem[]>([]);
  const [hotspots, setHotspots] = useState<HotspotIndicatorItem[]>([]);
  const [activeAlerts, setActiveAlerts] = useState<Alert[]>([]);
  const [recommendations, setRecommendations] = useState<RecommendationItem[]>([]);
  const [trustData, setTrustData] = useState<StationTrustResponse | null>(null);

  // Loading & Error States
  const [loadingLocations, setLoadingLocations] = useState<boolean>(true);
  const [loadingDashboard, setLoadingDashboard] = useState<boolean>(false);
  const [loadingPollutantTrend, setLoadingPollutantTrend] = useState<boolean>(false);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [lastUpdated, setLastUpdated] = useState<string>('');

  // Location Workflow State
  const [workflowState, setWorkflowState] = useState<
    'IDLE' | 'DETECTING_LOCATION' | 'FINDING_STATION' | 'SUCCESS' | 'NO_STATION' | 'ERROR'
  >('IDLE');
  const [workflowResult, setWorkflowResult] = useState<LocationWorkflowResponse | null>(null);
  const [workflowError, setWorkflowError] = useState<string | null>(null);
  const [showWorkflowNotice, setShowWorkflowNotice] = useState<boolean>(true);

  // Automation / Continuous Monitoring Status
  const [automationStatus, setAutomationStatus] = useState<AutomationStatusResponse | null>(null);

  // Calculate start & end ISO strings
  const getRangeISO = useCallback(() => {
    const rangeObj = TIME_RANGES.find((r) => r.key === timeRange) || TIME_RANGES[2];
    const end = new Date();
    const start = new Date(end.getTime() - rangeObj.hours * 60 * 60 * 1000);
    return {
      start_time: start.toISOString(),
      end_time: end.toISOString(),
    };
  }, [timeRange]);

  // Handle "Use My Location" automatic workflow orchestration
  const handleUseMyLocation = useCallback(() => {
    if (!navigator.geolocation) {
      setWorkflowState('ERROR');
      setWorkflowError('Geolocation is not supported by your browser.');
      setShowWorkflowNotice(true);
      return;
    }

    setWorkflowState('DETECTING_LOCATION');
    setWorkflowError(null);
    setShowWorkflowNotice(true);

    navigator.geolocation.getCurrentPosition(
      async (position) => {
        setWorkflowState('FINDING_STATION');
        const { latitude, longitude, accuracy } = position.coords;
        try {
          const res = await resolveLocationWorkflow({
            latitude,
            longitude,
            accuracy_meters: accuracy || null,
            radius_meters: 25000,
          });

          setWorkflowResult(res);

          if (res.status === 'SUCCESS' || res.status === 'PARTIAL_SUCCESS') {
            setWorkflowState('SUCCESS');
            if (res.resolved_station) {
              const resolved = res.resolved_station;
              const stationId = resolved.location_id ?? resolved.id ?? 0;
              // Check if location is already present in dropdown, if not add it
              setLocations((prev) => {
                if (!prev.some((l) => l.id === stationId)) {
                  return [
                    ...prev,
                    {
                      id: stationId,
                      name: resolved.name,
                      city: resolved.city,
                      state: resolved.state || '',
                      country: resolved.country || 'India',
                      latitude: resolved.latitude,
                      longitude: resolved.longitude,
                      is_active: true,
                      description: `OpenAQ station ID ${resolved.external_id}`,
                      external_provider: 'OPENAQ',
                      external_id: String(resolved.external_id),
                      created_at: new Date().toISOString(),
                      updated_at: new Date().toISOString(),
                    },
                  ];
                }
                return prev;
              });
              setSelectedLocationId(stationId);
            }
          } else if (res.status === 'NO_STATIONS_FOUND') {
            setWorkflowState('NO_STATION');
          } else {
            setWorkflowState('ERROR');
            setWorkflowError(res.message || 'Unable to resolve nearby monitoring station.');
          }
        } catch (err: any) {
          setWorkflowState('ERROR');
          setWorkflowError(
            err.response?.data?.detail?.message ||
              err.message ||
              'Failed to communicate with location workflow service. Please try again.'
          );
        }
      },
      (geoError) => {
        setWorkflowState('ERROR');
        if (geoError.code === geoError.PERMISSION_DENIED) {
          setWorkflowError(
            'Location access was denied. Please allow browser location access or select a station manually.'
          );
        } else if (geoError.code === geoError.POSITION_UNAVAILABLE) {
          setWorkflowError('Location information is currently unavailable from your device.');
        } else if (geoError.code === geoError.TIMEOUT) {
          setWorkflowError('Location request timed out. Please try again.');
        } else {
          setWorkflowError('An unknown error occurred while detecting your location.');
        }
      },
      {
        enableHighAccuracy: true,
        timeout: 10000,
        maximumAge: 60000,
      }
    );
  }, []);

  // Initial Load: Fetch Locations
  useEffect(() => {
    let ignore = false;
    const fetchLocs = async () => {
      setLoadingLocations(true);
      try {
        const locs = await getLocations();
        if (!ignore) {
          setLocations(locs);
          if (locs.length > 0 && selectedLocationId === null) {
            setSelectedLocationId(locs[0].id);
          }
        }
      } catch {
        if (!ignore) {
          setErrorMessage('Failed to load monitored locations. Please check backend connection.');
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
  }, [selectedLocationId]);

  // Load Primary Dashboard Data
  const loadDashboardData = useCallback(async () => {
    if (!selectedLocationId) return;

    setLoadingDashboard(true);
    setErrorMessage(null);
    const { start_time, end_time } = getRangeISO();

    try {
      // Parallel requests for all dashboard sections
      const [
        readingRes,
        aqiRes,
        aqiTrendRes,
        summaryRes,
        anomaliesRes,
        eventsRes,
        comparisonRes,
        hotspotsRes,
        alertsRes,
        recsRes,
        trustRes,
      ] = await Promise.allSettled([
        getCurrentReading(selectedLocationId),
        getLatestAQI(selectedLocationId),
        getAQITrend({
          location_id: selectedLocationId,
          aggregation: aqiAggregation,
          start_time,
          end_time,
        }),
        getLocationSummary({
          location_id: selectedLocationId,
          start_time,
          end_time,
        }),
        getAnomalies({
          location_id: selectedLocationId,
          start_time,
          end_time,
        }),
        getPollutionEvents({
          location_id: selectedLocationId,
          start_time,
          end_time,
        }),
        getLocationComparison({
          start_time,
          end_time,
        }),
        getHotspotIndicators({
          start_time,
          end_time,
        }),
        getActiveAlerts(selectedLocationId),
        getRecommendationsForLocation(selectedLocationId, {
          include_forecast: true,
          include_alerts: true,
        }),
        getStationTrust(selectedLocationId),
      ]);

      if (readingRes.status === 'fulfilled') {
        setCurrentReading(readingRes.value.reading);
      }
      if (aqiRes.status === 'fulfilled') {
        setLatestAQI(aqiRes.value);
      }
      if (aqiTrendRes.status === 'fulfilled') {
        setAqiTrend(aqiTrendRes.value);
      }
      if (summaryRes.status === 'fulfilled') {
        setSummary(summaryRes.value);
      }
      if (anomaliesRes.status === 'fulfilled') {
        setAnomalies(anomaliesRes.value);
      }
      if (eventsRes.status === 'fulfilled') {
        setEvents(eventsRes.value);
      }
      if (comparisonRes.status === 'fulfilled') {
        setComparison(comparisonRes.value);
      }
      if (hotspotsRes.status === 'fulfilled') {
        setHotspots(hotspotsRes.value);
      }
      if (alertsRes.status === 'fulfilled') {
        setActiveAlerts(alertsRes.value);
      }
      if (recsRes.status === 'fulfilled') {
        setRecommendations(recsRes.value.recommendations);
      }
      if (trustRes.status === 'fulfilled') {
        setTrustData(trustRes.value);
      }

      setLastUpdated(new Date().toLocaleTimeString());
    } catch {
      setErrorMessage('Some dashboard components could not be refreshed.');
    } finally {
      setLoadingDashboard(false);
    }
  }, [selectedLocationId, aqiAggregation, getRangeISO]);

  // Load Pollutant Trend (triggers when selectedPollutant or aggregation changes)
  const loadPollutantTrend = useCallback(async () => {
    if (!selectedLocationId) return;

    setLoadingPollutantTrend(true);
    const { start_time, end_time } = getRangeISO();

    try {
      const data = await getPollutantTrend(selectedPollutant, {
        location_id: selectedLocationId,
        aggregation: pollutantAggregation,
        start_time,
        end_time,
      });
      setPollutantTrend(data);
    } catch {
      setPollutantTrend([]);
    } finally {
      setLoadingPollutantTrend(false);
    }
  }, [selectedLocationId, selectedPollutant, pollutantAggregation, getRangeISO]);

  // Trigger main dashboard data on location/timeRange/aqiAggregation change
  useEffect(() => {
    let ignore = false;
    if (selectedLocationId) {
      Promise.resolve().then(() => {
        if (!ignore) {
          loadDashboardData();
        }
      });
    }
    return () => {
      ignore = true;
    };
  }, [selectedLocationId, timeRange, aqiAggregation, loadDashboardData]);

  // Trigger pollutant trend
  useEffect(() => {
    let ignore = false;
    if (selectedLocationId) {
      Promise.resolve().then(() => {
        if (!ignore) {
          loadPollutantTrend();
        }
      });
    }
    return () => {
      ignore = true;
    };
  }, [selectedLocationId, selectedPollutant, pollutantAggregation, timeRange, loadPollutantTrend]);

  // Phase 18: Conservative 5-minute auto-refresh while the tab is visible
  useEffect(() => {
    // Initial fetch of automation status
    getAutomationStatus().then(setAutomationStatus).catch(() => {});

    const interval = setInterval(() => {
      if (typeof document !== 'undefined' && document.visibilityState === 'visible' && selectedLocationId) {
        loadDashboardData();
        getAutomationStatus().then(setAutomationStatus).catch(() => {});
      }
    }, 5 * 60 * 1000);

    return () => clearInterval(interval);
  }, [selectedLocationId, loadDashboardData]);

  const activeLocation = locations.find((loc) => loc.id === selectedLocationId);
  const locationDisplayName = activeLocation
    ? `${activeLocation.name}, ${activeLocation.city}`
    : 'Selected Location';

  return (
    <div className="space-y-6">
      {/* SECTION A: Location, Time & Control Bar */}
      <div className="p-4 rounded-2xl bg-slate-900/80 border border-slate-800 shadow-xl flex flex-col lg:flex-row lg:items-center justify-between gap-4">
        {/* Location & Time Range Selectors */}
        <div className="flex flex-wrap items-center gap-3">
          {/* Location Dropdown */}
          <div className="flex items-center gap-2 bg-slate-950/60 px-3 py-2 rounded-xl border border-slate-800">
            <MapPin className="w-4 h-4 text-teal-400 shrink-0" />
            <div className="flex flex-col">
              <span className="text-[10px] text-slate-500 font-semibold uppercase tracking-wider">
                Monitored Station
              </span>
              <select
                aria-label="Select Monitored Station"
                value={selectedLocationId || ''}
                onChange={(e) => setSelectedLocationId(Number(e.target.value))}
                disabled={loadingLocations}
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

          {/* Automatic Location Workflow: Use My Location Button */}
          <button
            type="button"
            onClick={handleUseMyLocation}
            disabled={workflowState === 'DETECTING_LOCATION' || workflowState === 'FINDING_STATION'}
            className="flex items-center gap-1.5 px-3 py-2.5 rounded-xl bg-teal-500/10 hover:bg-teal-500/20 text-teal-300 border border-teal-500/30 text-xs font-semibold transition disabled:opacity-50"
            title="Automatically resolve nearest real monitoring station to your location"
          >
            {workflowState === 'DETECTING_LOCATION' ? (
              <>
                <Loader2 className="w-3.5 h-3.5 animate-spin text-teal-400" />
                <span>Detecting Location...</span>
              </>
            ) : workflowState === 'FINDING_STATION' ? (
              <>
                <Loader2 className="w-3.5 h-3.5 animate-spin text-teal-400" />
                <span>Resolving Station...</span>
              </>
            ) : (
              <>
                <LocateFixed className="w-3.5 h-3.5 text-teal-400" />
                <span>Use My Location</span>
              </>
            )}
          </button>

          {/* Time Range Selector */}
          <div className="flex items-center gap-1 rounded-xl bg-slate-950/60 p-1 border border-slate-800">
            {TIME_RANGES.map((r) => (
              <button
                key={r.key}
                type="button"
                onClick={() => setTimeRange(r.key)}
                className={`px-3 py-1.5 rounded-lg text-xs font-semibold transition ${
                  timeRange === r.key
                    ? 'bg-teal-500 text-slate-950 shadow-sm'
                    : 'text-slate-400 hover:text-white'
                }`}
              >
                {r.label}
              </button>
            ))}
          </div>
        </div>

        {/* Status, Refresh & Provenance Strip */}
        <div className="flex flex-wrap items-center gap-3 self-start lg:self-auto">
          {currentReading?.source_type && (
            <span className="px-2.5 py-1 rounded-full text-[10px] font-mono font-semibold tracking-wider bg-teal-500/10 text-teal-300 border border-teal-500/30">
              ORIGIN: {currentReading.source_type}
            </span>
          )}

          {/* Phase 18 Auto-Sync Live Status Pill */}
          {automationStatus && (
            <div
              title={`Continuous Monitoring: ${automationStatus.status} (${automationStatus.poll_interval_minutes}m interval)`}
              className="flex items-center gap-1.5 px-2.5 py-1 rounded-full text-[10px] font-mono font-medium tracking-wide bg-slate-950/60 border border-slate-800 text-slate-300"
            >
              <span
                className={`w-2 h-2 rounded-full ${
                  automationStatus.status === 'RUNNING'
                    ? 'bg-amber-400 animate-pulse'
                    : automationStatus.status === 'IDLE'
                    ? 'bg-emerald-400'
                    : automationStatus.status === 'BACKOFF'
                    ? 'bg-orange-400'
                    : automationStatus.status === 'PAUSED'
                    ? 'bg-yellow-400'
                    : 'bg-slate-500'
                }`}
              />
              <span>Auto-sync: {automationStatus.status === 'IDLE' ? 'Active' : automationStatus.status.toLowerCase()}</span>
            </div>
          )}

          {lastUpdated && (
            <div className="flex items-center gap-1.5 text-xs text-slate-400 font-mono">
              <Clock className="w-3.5 h-3.5 text-slate-500" />
              <span>Synced {lastUpdated}</span>
            </div>
          )}

          <button
            type="button"
            onClick={() => {
              loadDashboardData();
              loadPollutantTrend();
            }}
            disabled={loadingDashboard}
            className="inline-flex items-center gap-2 px-3.5 py-2 rounded-xl bg-slate-800 hover:bg-slate-700 text-slate-200 text-xs font-medium border border-slate-700 transition disabled:opacity-50"
          >
            <RefreshCw className={`w-3.5 h-3.5 ${loadingDashboard ? 'animate-spin' : ''}`} />
            <span>Refresh</span>
          </button>
        </div>
      </div>

      {/* Location Workflow Resolution Banner */}
      {showWorkflowNotice && workflowState !== 'IDLE' && (
        <div
          className={`p-4 rounded-2xl border flex flex-col sm:flex-row sm:items-center justify-between gap-3 shadow-lg transition-all ${
            workflowState === 'DETECTING_LOCATION' || workflowState === 'FINDING_STATION'
              ? 'bg-blue-500/10 border-blue-500/30 text-blue-300'
              : workflowState === 'SUCCESS'
              ? 'bg-teal-500/10 border-teal-500/30 text-teal-300'
              : workflowState === 'NO_STATION'
              ? 'bg-amber-500/10 border-amber-500/30 text-amber-300'
              : 'bg-rose-500/10 border-rose-500/30 text-rose-300'
          }`}
        >
          <div className="flex items-start sm:items-center gap-3">
            <div className="p-2 rounded-xl shrink-0 mt-0.5 sm:mt-0 bg-slate-950/40">
              {workflowState === 'DETECTING_LOCATION' || workflowState === 'FINDING_STATION' ? (
                <Loader2 className="w-5 h-5 animate-spin text-teal-400" />
              ) : workflowState === 'SUCCESS' ? (
                <CheckCircle2 className="w-5 h-5 text-emerald-400" />
              ) : workflowState === 'NO_STATION' ? (
                <AlertTriangle className="w-5 h-5 text-amber-400" />
              ) : (
                <XCircle className="w-5 h-5 text-rose-400" />
              )}
            </div>

            <div className="space-y-1">
              <div className="flex flex-wrap items-center gap-2">
                <span className="text-xs font-bold uppercase tracking-wider text-slate-200">
                  {workflowState === 'DETECTING_LOCATION'
                    ? 'Detecting Device Location'
                    : workflowState === 'FINDING_STATION'
                    ? 'Discovering Nearest Monitoring Station'
                    : workflowState === 'SUCCESS'
                    ? 'Nearest Station Resolved'
                    : workflowState === 'NO_STATION'
                    ? 'No Station Found Within 25 km'
                    : 'Location Resolution Notice'}
                </span>

                {workflowState === 'SUCCESS' && workflowResult?.resolved_station && (
                  <>
                    <span className="px-2 py-0.5 rounded text-[10px] font-bold uppercase bg-teal-500/20 text-teal-300 border border-teal-500/30 font-mono">
                      {workflowResult.resolved_station.distance_km.toFixed(1)} km away
                    </span>
                    <span
                      className={`px-2 py-0.5 rounded text-[10px] font-bold uppercase font-mono ${
                        workflowResult.resolved_station.data_freshness === 'FRESH'
                          ? 'bg-emerald-500/20 text-emerald-300 border border-emerald-500/30'
                          : workflowResult.resolved_station.data_freshness === 'STALE'
                          ? 'bg-amber-500/20 text-amber-300 border border-amber-500/30'
                          : 'bg-rose-500/20 text-rose-300 border border-rose-500/30'
                      }`}
                    >
                      {workflowResult.resolved_station.data_freshness} Telemetry
                    </span>
                  </>
                )}
              </div>

              <p className="text-xs text-slate-300 leading-relaxed">
                {workflowState === 'DETECTING_LOCATION'
                  ? 'Requesting browser GPS coordinates with high accuracy...'
                  : workflowState === 'FINDING_STATION'
                  ? 'Searching OpenAQ monitoring network within 25 km and evaluating real observations...'
                  : workflowState === 'SUCCESS' && workflowResult?.resolved_station
                  ? `Connected to ${workflowResult.resolved_station.name} (${workflowResult.resolved_station.city}, ${workflowResult.resolved_station.state}). Telemetry and predictions updated.`
                  : workflowState === 'NO_STATION'
                  ? workflowResult?.nearest_distant_station
                    ? `${workflowResult.message} ${workflowResult.nearest_distant_station.notice}`
                    : workflowResult?.message || 'No official monitoring station was found within 25 km of your location.'
                  : workflowError || 'Failed to resolve location.'}
              </p>
            </div>
          </div>

          <div className="flex items-center gap-2 self-end sm:self-auto shrink-0">
            {workflowState === 'ERROR' && (
              <button
                type="button"
                onClick={handleUseMyLocation}
                className="px-3 py-1.5 rounded-lg bg-slate-800 hover:bg-slate-700 text-xs text-white font-medium transition"
              >
                Retry
              </button>
            )}
            <button
              type="button"
              onClick={() => setShowWorkflowNotice(false)}
              className="p-1 rounded-lg hover:bg-slate-800 text-slate-400 hover:text-white transition"
              aria-label="Dismiss banner"
            >
              <X className="w-4 h-4" />
            </button>
          </div>
        </div>
      )}

      {/* Error Alert */}
      {errorMessage && (
        <div className="p-4 rounded-xl bg-rose-500/10 border border-rose-500/20 text-rose-300 text-xs flex items-center justify-between">
          <div className="flex items-center gap-2">
            <AlertTriangle className="w-4 h-4 shrink-0 text-rose-400" />
            <span>{errorMessage}</span>
          </div>
          <button
            onClick={() => {
              loadDashboardData();
              loadPollutantTrend();
            }}
            className="underline hover:text-white text-xs"
          >
            Retry
          </button>
        </div>
      )}

      {/* Active Alerts Banner */}
      {activeAlerts.length > 0 && (
        <div className="p-4 rounded-2xl bg-amber-500/10 border border-amber-500/30 flex flex-col sm:flex-row sm:items-center justify-between gap-3 shadow-lg">
          <div className="flex items-center gap-3">
            <div className="p-2.5 rounded-xl bg-amber-500/20 text-amber-300 shrink-0">
              <Bell className="w-5 h-5 animate-pulse" />
            </div>
            <div>
              <div className="flex items-center gap-2">
                <span className="text-xs font-bold uppercase tracking-wider text-amber-300">
                  {activeAlerts.length} Active {activeAlerts.length === 1 ? 'Alert' : 'Alerts'} Detected
                </span>
                <span className="px-2 py-0.5 rounded text-[10px] font-bold uppercase bg-amber-500/20 text-amber-200 border border-amber-500/30">
                  Highest: {activeAlerts.some((a) => a.severity === 'CRITICAL') ? 'CRITICAL' : activeAlerts.some((a) => a.severity === 'HIGH') ? 'HIGH' : 'WARNING'}
                </span>
              </div>
              <p className="text-xs text-slate-300 mt-0.5">
                {activeAlerts[0].title}: {activeAlerts[0].message}
              </p>
            </div>
          </div>
          {onNavigateToTab && (
            <button
              onClick={() => onNavigateToTab('alerts')}
              className="inline-flex items-center gap-1.5 px-3.5 py-2 rounded-xl bg-amber-500/20 hover:bg-amber-500/30 text-amber-200 text-xs font-semibold border border-amber-500/30 transition self-start sm:self-auto shrink-0"
            >
              <span>View Alert Center</span>
              <ArrowRight className="w-3.5 h-3.5" />
            </button>
          )}
        </div>
      )}

      {/* SECTION B & C: Current AQI & Pollutant Concentrations Overview */}
      <div className="grid grid-cols-1 lg:grid-cols-12 gap-6">
        <div className="lg:col-span-5">
          <CurrentAQICard
            aqiData={latestAQI}
            locationName={locationDisplayName}
            sourceType={currentReading?.source_type}
            freshnessStatus={trustData?.freshness.status}
            freshnessAgeHours={trustData?.freshness.age_hours}
            isLoading={loadingDashboard}
          />
        </div>
        <div className="lg:col-span-7">
          <div className="p-6 rounded-2xl bg-slate-900/60 border border-slate-800 shadow-xl h-full flex flex-col justify-between">
            <PollutantOverview reading={currentReading} isLoading={loadingDashboard} />
          </div>
        </div>
      </div>

      {/* SECTION B.1: Production Data Quality & Trust Panel */}
      <SystemTrustPanel
        trustData={trustData}
        isLoading={loadingDashboard}
        onRefresh={loadDashboardData}
      />

      {/* SECTION B.2: Recommended Preventive Actions */}
      {recommendations.length > 0 && (
        <div className="p-5 rounded-xl bg-slate-900/90 border border-slate-800/80 shadow-lg space-y-3">
          <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-2">
            <div className="flex items-center gap-2">
              <div className="p-1.5 rounded-lg bg-emerald-500/10 text-emerald-400 border border-emerald-500/20">
                <Sparkles className="w-4 h-4" />
              </div>
              <h3 className="text-sm font-bold text-slate-100 tracking-tight">
                Recommended Preventive Actions
              </h3>
            </div>
            {onNavigateToTab && (
              <button
                onClick={() => onNavigateToTab('recommendations')}
                className="text-xs text-emerald-400 hover:text-emerald-300 font-semibold inline-flex items-center gap-1 transition self-start sm:self-auto"
              >
                <span>View Action Center</span>
                <ArrowRight className="w-3.5 h-3.5" />
              </button>
            )}
          </div>

          <div className="grid grid-cols-1 md:grid-cols-3 gap-3 pt-1">
            {recommendations.slice(0, 3).map((rec) => (
              <div
                key={rec.id}
                className="p-3.5 rounded-lg bg-slate-950/60 border border-slate-800/80 space-y-1.5 flex flex-col justify-between"
              >
                <div className="space-y-1">
                  <div className="flex items-center justify-between gap-2">
                    <span className="px-1.5 py-0.5 rounded text-[9px] font-mono font-bold uppercase tracking-wider bg-slate-900 border border-slate-800 text-slate-300">
                      {rec.priority}
                    </span>
                    <span className="text-[10px] text-slate-500 font-mono">
                      {rec.type.replace(/_/g, ' ')}
                    </span>
                  </div>
                  <h4 className="text-xs font-bold text-slate-100 line-clamp-1">{rec.title}</h4>
                  <p className="text-[11px] text-slate-300 leading-snug">{rec.action}</p>
                </div>
                <div className="pt-1 border-t border-slate-800/60 text-[10px] text-slate-400 font-mono truncate">
                  Trigger: {rec.triggered_by}
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* SECTION B.2.5: Automated Real-Data ML AQI Forecast */}
      {workflowResult?.predictions && workflowResult.predictions.length > 0 && (
        <div className="p-5 rounded-2xl bg-slate-900/90 border border-slate-800 space-y-4 shadow-xl">
          <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-2 border-b border-slate-800/80 pb-3">
            <div className="flex items-center gap-2.5">
              <div className="p-2 rounded-xl bg-indigo-500/10 text-indigo-400 border border-indigo-500/20">
                <TrendingUp className="w-5 h-5" />
              </div>
              <div>
                <div className="flex items-center gap-2">
                  <h3 className="text-sm font-bold text-slate-100 uppercase tracking-wider">
                    General Real-Data ML Forecast
                  </h3>
                  <span className="px-2 py-0.5 rounded text-[10px] font-bold uppercase bg-indigo-500/10 text-indigo-300 border border-indigo-500/20 font-mono">
                    Multi-Station Ensemble
                  </span>
                </div>
                <p className="text-xs text-slate-400 mt-0.5">
                  Automated machine learning predictions across 5 forecast horizons for {workflowResult.resolved_station?.name || 'current station'}.
                </p>
              </div>
            </div>
            {onNavigateToTab && (
              <button
                type="button"
                onClick={() => onNavigateToTab('prediction')}
                className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-slate-800 hover:bg-slate-750 text-indigo-300 text-xs font-semibold border border-slate-700 transition self-start sm:self-auto shrink-0"
              >
                <span>Full Prediction Lab</span>
                <ArrowRight className="w-3.5 h-3.5" />
              </button>
            )}
          </div>

          <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-5 gap-3">
            {workflowResult.predictions.map((p) => {
              const catStyle = getAQICategoryStyle(p.category || undefined);
              const isPredicted = p.status === 'PREDICTED' && p.predicted_aqi !== null;
              return (
                <div
                  key={p.horizon_hours}
                  className="p-3.5 rounded-xl bg-slate-950/70 border border-slate-800 flex flex-col justify-between space-y-2 hover:border-slate-700 transition"
                >
                  <div className="flex items-center justify-between">
                    <span className="text-xs font-bold text-slate-300 font-mono">
                      +{p.horizon_hours}h Horizon
                    </span>
                    <span
                      className="w-2 h-2 rounded-full"
                      style={{ backgroundColor: isPredicted ? catStyle.hex : '#64748b' }}
                    />
                  </div>

                  <div>
                    {isPredicted ? (
                      <div className="space-y-1">
                        <div className="text-2xl font-black text-white font-mono tracking-tight">
                          {Math.round(p.predicted_aqi!)}
                        </div>
                        <span
                          className="inline-block px-2 py-0.5 rounded text-[10px] font-bold uppercase"
                          style={{
                            backgroundColor: `${catStyle.hex}20`,
                            color: catStyle.hex,
                            border: `1px solid ${catStyle.hex}40`,
                          }}
                        >
                          {p.category}
                        </span>
                      </div>
                    ) : (
                      <div className="space-y-1 py-1">
                        <div className="text-xs font-medium text-slate-400">
                          {p.status === 'INSUFFICIENT_HISTORY'
                            ? 'Insufficient History'
                            : p.status === 'MODEL_UNAVAILABLE'
                            ? 'Model Unavailable'
                            : 'Pending'}
                        </div>
                        <p className="text-[10px] text-slate-500 line-clamp-2 leading-tight">
                          {p.message || 'Requires at least 4 continuous hourly readings.'}
                        </p>
                      </div>
                    )}
                  </div>

                  {p.target_timestamp && (
                    <div className="text-[10px] text-slate-500 font-mono truncate pt-1 border-t border-slate-900">
                      {new Date(p.target_timestamp).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        </div>
      )}

      {/* SECTION B.3: What-If Pollution Simulation Entry Point */}
      <div className="p-4 rounded-xl bg-slate-900/90 border border-slate-800/80 flex flex-col sm:flex-row sm:items-center justify-between gap-4 shadow-lg">
        <div className="flex items-center gap-3">
          <div className="p-2.5 rounded-lg bg-emerald-500/10 text-emerald-400 border border-emerald-500/20 shrink-0">
            <Sliders className="w-5 h-5" />
          </div>
          <div>
            <div className="flex items-center gap-2">
              <span className="text-xs font-bold uppercase tracking-wider text-slate-200">
                What-If Pollution Simulation & Impact Analysis
              </span>
              <span className="px-2 py-0.5 rounded text-[10px] font-bold uppercase bg-cyan-500/10 text-cyan-300 border border-cyan-500/20 font-mono">
                Interactive Model
              </span>
            </div>
            <p className="text-xs text-slate-400 mt-0.5">
              Simulate hypothetical percentage variations in pollutant concentrations (+/- %) to evaluate recalculated AQI, category shifts, and preventive protocols.
            </p>
          </div>
        </div>
        {onNavigateToTab && (
          <button
            onClick={() => onNavigateToTab('whatif')}
            className="inline-flex items-center gap-1.5 px-3.5 py-2 rounded-lg bg-slate-800 hover:bg-slate-750 text-emerald-400 text-xs font-semibold border border-slate-700 transition self-start sm:self-auto shrink-0"
          >
            <span>Explore What-If Scenarios</span>
            <ArrowRight className="w-3.5 h-3.5" />
          </button>
        )}
      </div>

      {/* SECTION D & E: Recharts Visualizations */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        <AQITrendChart
          data={aqiTrend}
          isLoading={loadingDashboard}
          aggregation={aqiAggregation}
          onAggregationChange={setAqiAggregation}
        />
        <PollutantTrendChart
          data={pollutantTrend}
          isLoading={loadingPollutantTrend}
          selectedPollutant={selectedPollutant}
          onSelectPollutant={setSelectedPollutant}
          aggregation={pollutantAggregation}
          onAggregationChange={setPollutantAggregation}
        />
      </div>

      {/* SECTION F & G: Descriptive Analytics & Distribution Statistics */}
      <AnalyticsSummaryCard summary={summary} isLoading={loadingDashboard} />

      {/* SECTION H & I: Anomaly Detection & Sustained Pollution Episodes */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        <AnomaliesTable anomalies={anomalies} isLoading={loadingDashboard} />
        <PollutionEventsTable events={events} isLoading={loadingDashboard} />
      </div>

      {/* SECTION J & K: Objective Comparison & Hotspot Indicators */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        <LocationComparisonTable
          locations={comparison}
          selectedLocationId={selectedLocationId || undefined}
          onSelectLocation={(locId) => setSelectedLocationId(locId)}
          isLoading={loadingDashboard}
        />
        <HotspotIndicatorsTable
          hotspots={hotspots}
          selectedLocationId={selectedLocationId || undefined}
          onSelectLocation={(locId) => setSelectedLocationId(locId)}
          isLoading={loadingDashboard}
        />
      </div>

      {/* SECTION L: Software-Only System & Data Provenance Notice */}
      <div className="p-5 rounded-2xl bg-slate-900/40 border border-slate-800 space-y-3 text-xs text-slate-400">
        <div className="flex items-center gap-2 text-slate-300 font-semibold text-xs">
          <ShieldAlert className="w-4 h-4 text-amber-400 shrink-0" />
          <span>Software-Only Telemetry Architecture & Data Provenance</span>
        </div>
        <p className="leading-relaxed text-[11px] text-slate-400">
          This system operates as a pure software analytics platform. All telemetry displayed above originates strictly
          from official public air quality APIs, validated batch file uploads, or deterministic software simulations.
          No physical sensors (such as Arduino, ESP32, or Raspberry Pi) are utilized or claimed. In alignment with CPCB
          guidelines, missing pollutant values are strictly preserved as <code className="text-slate-300 bg-slate-800 px-1 py-0.5 rounded">NULL</code> and
          never substituted with zero.
        </p>
        <div className="flex flex-wrap items-center gap-3 pt-1 text-[10px] font-mono text-slate-400">
          <div className="flex items-center gap-1">
            <ShieldCheck className="w-3.5 h-3.5 text-emerald-400" />
            <span>Algorithm: CPCB National AQI (IND-AQI) Sub-index Max</span>
          </div>
          <span>•</span>
          <div className="flex items-center gap-1">
            <Layers className="w-3.5 h-3.5 text-teal-400" />
            <span>Telemetry Provenance: {currentReading?.source_type || 'API / SIMULATED'}</span>
          </div>
        </div>
      </div>
    </div>
  );
};
