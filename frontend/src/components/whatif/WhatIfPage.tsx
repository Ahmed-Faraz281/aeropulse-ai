import React, { useState, useEffect, useCallback } from 'react';
import type { User } from '../../types/auth';
import type { Location, AirQualityReading } from '../../types/air_quality';
import type { WhatIfSimulationResponse } from '../../types/whatIf';
import type { RecommendationPriority } from '../../types/recommendation';
import { getLocations, getCurrentReading } from '../../services/air_quality';
import { simulateWhatIf } from '../../services/whatIf';
import { getAQICategoryStyle } from '../../utils/aqiFormatters';
import {
  Sliders,
  ShieldAlert,
  RotateCcw,
  Play,
  ArrowRight,
  TrendingUp,
  TrendingDown,
  Minus,
  Sparkles,
  MapPin,
  Clock,
  AlertTriangle,
  RefreshCw,
  Layers,
  History,
  Info,
  FileText,
} from 'lucide-react';

interface WhatIfPageProps {
  currentUser: User;
  onNavigateToTab?: (tabId: string) => void;
  onNavigateToDashboard?: (locationId: number) => void;
  preselectedLocationId?: number | null;
}

const POLLUTANTS_INFO: Record<string, { label: string; unit: string; description: string }> = {
  pm25: { label: 'PM2.5', unit: 'µg/m³', description: 'Fine Particulate Matter (≤ 2.5 µm)' },
  pm10: { label: 'PM10', unit: 'µg/m³', description: 'Coarse Particulate Matter (≤ 10 µm)' },
  no2: { label: 'NO2', unit: 'µg/m³', description: 'Nitrogen Dioxide (Combustion/Traffic)' },
  so2: { label: 'SO2', unit: 'µg/m³', description: 'Sulfur Dioxide (Industrial Gas)' },
  co: { label: 'CO', unit: 'mg/m³', description: 'Carbon Monoxide (Vehicle Exhaust)' },
  o3: { label: 'O3', unit: 'µg/m³', description: 'Ozone (Photochemical Smog)' },
  nh3: { label: 'NH3', unit: 'µg/m³', description: 'Ammonia (Chemical Precursor)' },
  pb: { label: 'Pb', unit: 'µg/m³', description: 'Lead Particulate (Industrial)' },
};

const PRIORITY_THEMES: Record<
  RecommendationPriority,
  { bg: string; text: string; border: string; badge: string }
> = {
  CRITICAL: {
    bg: 'bg-rose-950/30',
    text: 'text-rose-300',
    border: 'border-rose-500/40',
    badge: 'bg-rose-500/20 text-rose-300 border-rose-500/30',
  },
  HIGH: {
    bg: 'bg-orange-950/30',
    text: 'text-orange-300',
    border: 'border-orange-500/40',
    badge: 'bg-orange-500/20 text-orange-300 border-orange-500/30',
  },
  MEDIUM: {
    bg: 'bg-amber-950/30',
    text: 'text-amber-300',
    border: 'border-amber-500/40',
    badge: 'bg-amber-500/20 text-amber-300 border-amber-500/30',
  },
  LOW: {
    bg: 'bg-lime-950/30',
    text: 'text-lime-300',
    border: 'border-lime-500/40',
    badge: 'bg-lime-500/20 text-lime-300 border-lime-500/30',
  },
  INFO: {
    bg: 'bg-teal-950/30',
    text: 'text-teal-300',
    border: 'border-teal-500/40',
    badge: 'bg-teal-500/20 text-teal-300 border-teal-500/30',
  },
};

export const WhatIfPage: React.FC<WhatIfPageProps> = ({
  currentUser,
  onNavigateToTab,
  onNavigateToDashboard,
  preselectedLocationId,
}) => {
  const [locations, setLocations] = useState<Location[]>([]);
  const [selectedLocationId, setSelectedLocationId] = useState<number | null>(
    preselectedLocationId || null
  );
  const [loadingLocations, setLoadingLocations] = useState(true);

  const [currentReading, setCurrentReading] = useState<AirQualityReading | null>(null);
  const [loadingReading, setLoadingReading] = useState(false);

  // Pollutant % changes: key -> percentage value between -100 and +200
  const [pollutantChanges, setPollutantChanges] = useState<Record<string, number>>({
    pm25: 0,
    pm10: 0,
    no2: 0,
    so2: 0,
    co: 0,
    o3: 0,
    nh3: 0,
    pb: 0,
  });

  const [simulationResult, setSimulationResult] = useState<WhatIfSimulationResponse | null>(null);
  const [simulating, setSimulating] = useState(false);
  const [errorMsg, setErrorMsg] = useState<string | null>(null);
  const [scenarioHistory, setScenarioHistory] = useState<WhatIfSimulationResponse[]>([]);

  // Load locations on mount
  useEffect(() => {
    let ignore = false;
    const fetchLocs = async () => {
      try {
        setLoadingLocations(true);
        const locList = await getLocations();
        if (!ignore) {
          setLocations(locList);
          if (locList.length > 0) {
            setSelectedLocationId((prev) => prev ?? locList[0].id);
          }
        }
      } catch {
        if (!ignore) {
          setErrorMsg('Failed to fetch monitoring locations.');
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

  // Fetch baseline observation when selected location changes
  const loadBaseline = useCallback(async (locId: number) => {
    try {
      setLoadingReading(true);
      setErrorMsg(null);
      const res = await getCurrentReading(locId);
      setCurrentReading(res.reading);
      // Reset modifiers
      setPollutantChanges({
        pm25: 0,
        pm10: 0,
        no2: 0,
        so2: 0,
        co: 0,
        o3: 0,
        nh3: 0,
        pb: 0,
      });
      setSimulationResult(null);
    } catch {
      setErrorMsg('No current valid observation available for this station.');
      setCurrentReading(null);
      setSimulationResult(null);
    } finally {
      setLoadingReading(false);
    }
  }, []);

  useEffect(() => {
    let ignore = false;
    if (selectedLocationId) {
      Promise.resolve().then(() => {
        if (!ignore) {
          loadBaseline(selectedLocationId);
        }
      });
    }
    return () => {
      ignore = true;
    };
  }, [selectedLocationId, loadBaseline]);

  const handleSliderChange = (pollutantKey: string, value: number) => {
    setPollutantChanges((prev) => ({
      ...prev,
      [pollutantKey]: value,
    }));
  };

  const handleReset = () => {
    setPollutantChanges({
      pm25: 0,
      pm10: 0,
      no2: 0,
      so2: 0,
      co: 0,
      o3: 0,
      nh3: 0,
      pb: 0,
    });
    setErrorMsg(null);
  };

  const handleRunSimulation = async () => {
    if (!selectedLocationId) return;

    // Filter only non-zero changes or all configured
    const activeChanges: Record<string, number> = {};
    Object.entries(pollutantChanges).forEach(([k, v]) => {
      if (v !== 0) {
        activeChanges[k] = v;
      }
    });

    try {
      setSimulating(true);
      setErrorMsg(null);
      const res = await simulateWhatIf({
        location_id: selectedLocationId,
        reading_id: currentReading?.id,
        pollutant_changes: activeChanges,
      });
      setSimulationResult(res);

      // Append to client history (keep max 5)
      setScenarioHistory((prev) => [res, ...prev.slice(0, 4)]);
    } catch (err: any) {
      const detail =
        err?.response?.data?.detail ||
        err?.message ||
        'Simulation calculation failed. Please check input parameters.';
      setErrorMsg(detail);
    } finally {
      setSimulating(false);
    }
  };

  const selectedLoc = locations.find((l) => l.id === selectedLocationId);

  return (
    <div className="space-y-6">
      {/* Header & Title */}
      <div className="flex flex-col md:flex-row md:items-center justify-between gap-4">
        <div>
          <div className="flex items-center gap-2.5">
            <div className="p-2 rounded-xl bg-teal-500/20 text-teal-400 border border-teal-500/30">
              <Sliders className="w-6 h-6" />
            </div>
            <div>
              <div className="flex items-center gap-2">
                <h1 className="text-xl font-black tracking-tight text-white">
                  What-If Pollution Simulation & Impact Analysis
                </h1>
                <span className="px-2.5 py-0.5 rounded-full text-[10px] font-bold tracking-wide uppercase bg-teal-500/10 text-teal-400 border border-teal-500/20">
                  Phase 12
                </span>
                <span className="px-2 py-0.5 rounded-full text-[10px] font-mono uppercase bg-slate-800 text-slate-300 border border-slate-700">
                  {currentUser.role}
                </span>
              </div>
              <p className="text-xs text-slate-400 mt-0.5">
                Simulate hypothetical variations in pollutant concentrations (+/- %) to evaluate recalculated CPCB NAQI, category transitions, and preventive actions.
              </p>
            </div>
          </div>
        </div>

        {/* Location Selector Dropdown & Tab Shortcuts */}
        <div className="flex items-center gap-2 self-start md:self-auto">
          <div className="relative">
            <select
              value={selectedLocationId || ''}
              onChange={(e) => setSelectedLocationId(Number(e.target.value))}
              disabled={loadingLocations || simulating}
              className="bg-slate-900 border border-slate-700 text-slate-200 text-xs rounded-xl px-3 py-2 pr-8 focus:outline-none focus:border-teal-500 transition shadow-inner font-medium disabled:opacity-50"
            >
              {locations.map((loc) => (
                <option key={loc.id} value={loc.id}>
                  {loc.name} ({loc.city})
                </option>
              ))}
            </select>
          </div>
          {onNavigateToDashboard && selectedLocationId && (
            <button
              onClick={() => onNavigateToDashboard(selectedLocationId)}
              className="px-3 py-2 rounded-xl bg-slate-800 hover:bg-slate-700 text-slate-300 text-xs font-semibold border border-slate-700 transition"
              title="View in Dashboard"
            >
              Dashboard
            </button>
          )}
          {onNavigateToTab && (
            <button
              onClick={() => onNavigateToTab('recommendations')}
              className="px-3 py-2 rounded-xl bg-slate-800 hover:bg-slate-700 text-teal-300 text-xs font-semibold border border-slate-700 transition flex items-center gap-1.5"
              title="View Live Recommendations"
            >
              <Sparkles className="w-3.5 h-3.5" />
              <span className="hidden sm:inline">Guidance</span>
            </button>
          )}
        </div>
      </div>

      {/* Mandatory Software Simulation & Non-Medical Disclaimer */}
      <div className="p-3.5 rounded-xl bg-amber-500/5 border border-amber-500/20 flex items-start gap-3 text-xs text-amber-200/90 shadow-sm">
        <ShieldAlert className="w-4 h-4 text-amber-400 shrink-0 mt-0.5" />
        <div className="space-y-0.5">
          <span className="font-bold text-amber-300">Hypothetical Simulation Advisory: </span>
          <span>
            What-If scenarios are purely software-calculated hypothetical evaluations using the official Indian CPCB NAQI formula. They do not alter database observations, do not generate active alarms, and do not constitute medical advice.
          </span>
        </div>
      </div>

      {/* Scenario History Quick Summary */}
      {scenarioHistory.length > 0 && (
        <div className="flex items-center gap-2 text-xs text-slate-400 bg-slate-900/40 px-3.5 py-2 rounded-xl border border-slate-800">
          <History className="w-3.5 h-3.5 text-teal-400 shrink-0" />
          <span className="font-semibold text-slate-300">Session Scenarios Evaluated: {scenarioHistory.length}</span>
          <span className="text-slate-500">
            • Latest result: {scenarioHistory[0].impact.direction} (
            {scenarioHistory[0].impact.aqi_delta != null && scenarioHistory[0].impact.aqi_delta > 0
              ? `+${scenarioHistory[0].impact.aqi_delta}`
              : scenarioHistory[0].impact.aqi_delta}{' '}
            AQI delta)
          </span>
        </div>
      )}

      {/* Error Alert */}
      {errorMsg && (
        <div className="p-4 rounded-xl bg-rose-500/10 border border-rose-500/30 text-rose-300 text-xs flex items-start gap-3">
          <AlertTriangle className="w-4 h-4 text-rose-400 shrink-0 mt-0.5" />
          <div className="flex-1">
            <p className="font-semibold text-rose-200">Simulation Error</p>
            <p className="mt-0.5 text-rose-300/90">{errorMsg}</p>
          </div>
        </div>
      )}

      {/* Main Grid: Modifiers on Left, Results on Right */}
      <div className="grid grid-cols-1 lg:grid-cols-12 gap-6">
        {/* Left Column (5 Cols): Baseline Overview & Pollutant Modifiers */}
        <div className="lg:col-span-5 space-y-6">
          {/* Station Baseline Status Card */}
          <div className="p-5 rounded-2xl bg-slate-900/60 border border-slate-800 shadow-xl space-y-4">
            <div className="flex items-center justify-between pb-3 border-b border-slate-800">
              <div className="flex items-center gap-2">
                <MapPin className="w-4 h-4 text-teal-400" />
                <h2 className="text-xs font-bold uppercase tracking-wider text-slate-300">
                  Current Observed Baseline
                </h2>
              </div>
              <span className="px-2 py-0.5 rounded text-[10px] font-mono bg-slate-800 text-teal-400 border border-slate-700">
                Source: {currentReading?.source_type || 'API'}
              </span>
            </div>

            {loadingReading ? (
              <div className="py-6 flex items-center justify-center gap-2 text-xs text-slate-400">
                <RefreshCw className="w-4 h-4 animate-spin text-teal-400" />
                <span>Loading baseline observation...</span>
              </div>
            ) : currentReading ? (
              <div className="space-y-3">
                <div className="flex items-center justify-between">
                  <div>
                    <p className="text-sm font-bold text-white">{selectedLoc?.name}</p>
                    <p className="text-xs text-slate-400">
                      {selectedLoc?.city}, {selectedLoc?.state}
                    </p>
                  </div>
                  <div className="text-right text-[11px] text-slate-400 font-mono">
                    <div className="flex items-center gap-1 justify-end">
                      <Clock className="w-3 h-3" />
                      <span>{new Date(currentReading.timestamp).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}</span>
                    </div>
                  </div>
                </div>

                {simulationResult && (
                  <div className="grid grid-cols-3 gap-2 pt-2 border-t border-slate-800/80">
                    <div className="p-2.5 rounded-xl bg-slate-950/50 border border-slate-800 text-center">
                      <p className="text-[10px] text-slate-400 uppercase font-semibold">Baseline AQI</p>
                      <p className="text-lg font-black text-white mt-0.5">
                        {simulationResult.baseline.aqi ?? 'N/A'}
                      </p>
                    </div>
                    <div className="p-2.5 rounded-xl bg-slate-950/50 border border-slate-800 text-center">
                      <p className="text-[10px] text-slate-400 uppercase font-semibold">Category</p>
                      <p className="text-xs font-bold text-teal-400 mt-1">
                        {simulationResult.baseline.category ?? 'N/A'}
                      </p>
                    </div>
                    <div className="p-2.5 rounded-xl bg-slate-950/50 border border-slate-800 text-center">
                      <p className="text-[10px] text-slate-400 uppercase font-semibold">Dominant</p>
                      <p className="text-xs font-bold text-indigo-400 mt-1">
                        {simulationResult.baseline.dominant_pollutant ?? 'N/A'}
                      </p>
                    </div>
                  </div>
                )}
              </div>
            ) : (
              <p className="text-xs text-slate-500 italic py-2">No observation available.</p>
            )}
          </div>

          {/* Interactive Modifiers Card */}
          <div className="p-5 rounded-2xl bg-slate-900/60 border border-slate-800 shadow-xl space-y-5">
            <div className="flex items-center justify-between pb-3 border-b border-slate-800">
              <div className="flex items-center gap-2">
                <Sliders className="w-4 h-4 text-teal-400" />
                <h2 className="text-xs font-bold uppercase tracking-wider text-slate-300">
                  Pollutant Modifiers (+/- %)
                </h2>
              </div>
              <button
                onClick={handleReset}
                className="text-[11px] text-slate-400 hover:text-teal-300 flex items-center gap-1 transition"
                title="Reset all percentage modifiers to 0%"
              >
                <RotateCcw className="w-3 h-3" />
                <span>Reset (0%)</span>
              </button>
            </div>

            {/* Pollutants Slider List */}
            <div className="space-y-4 max-h-[440px] overflow-y-auto pr-1">
              {Object.entries(POLLUTANTS_INFO).map(([key, info]) => {
                const currentVal = currentReading ? (currentReading as any)[key] : null;
                const isAvailable = currentVal !== null && currentVal !== undefined;
                const changePct = pollutantChanges[key] || 0;
                const simulatedVal = isAvailable
                  ? Math.max(0, currentVal * (1 + changePct / 100))
                  : null;

                return (
                  <div
                    key={key}
                    className={`p-3.5 rounded-xl border transition ${
                      !isAvailable
                        ? 'bg-slate-950/30 border-slate-800/40 opacity-50'
                        : changePct !== 0
                        ? 'bg-teal-950/10 border-teal-500/30'
                        : 'bg-slate-950/50 border-slate-800'
                    }`}
                  >
                    <div className="flex items-center justify-between text-xs mb-1.5">
                      <div className="flex items-center gap-2">
                        <span className="font-bold text-white">{info.label}</span>
                        <span className="text-[10px] text-slate-400">({info.unit})</span>
                      </div>
                      <div className="text-right font-mono text-xs">
                        {isAvailable ? (
                          <div className="flex items-center gap-1.5">
                            <span className="text-slate-400">{currentVal.toFixed(1)}</span>
                            <ArrowRight className="w-3 h-3 text-slate-500" />
                            <span
                              className={`font-bold ${
                                changePct > 0
                                  ? 'text-rose-400'
                                  : changePct < 0
                                  ? 'text-emerald-400'
                                  : 'text-white'
                              }`}
                            >
                              {simulatedVal?.toFixed(1)}
                            </span>
                            <span
                              className={`text-[10px] px-1.5 py-0.2 rounded font-semibold ${
                                changePct > 0
                                  ? 'bg-rose-500/20 text-rose-300'
                                  : changePct < 0
                                  ? 'bg-emerald-500/20 text-emerald-300'
                                  : 'bg-slate-800 text-slate-400'
                              }`}
                            >
                              {changePct > 0 ? `+${changePct}%` : `${changePct}%`}
                            </span>
                          </div>
                        ) : (
                          <span className="text-slate-500 italic text-[11px]">Unavailable</span>
                        )}
                      </div>
                    </div>

                    {isAvailable && (
                      <div className="space-y-2 mt-2">
                        {/* Slider */}
                        <div className="flex items-center gap-3">
                          <span className="text-[10px] text-slate-500 font-mono">-100%</span>
                          <input
                            type="range"
                            min={-100}
                            max={200}
                            step={5}
                            value={changePct}
                            onChange={(e) => handleSliderChange(key, Number(e.target.value))}
                            className="w-full accent-teal-400 cursor-pointer h-1.5 bg-slate-800 rounded-lg"
                          />
                          <span className="text-[10px] text-slate-500 font-mono">+200%</span>
                        </div>

                        {/* Quick Preset Buttons */}
                        <div className="flex items-center gap-1.5 pt-1 overflow-x-auto text-[10px]">
                          {[-30, -20, -10, 0, 10, 20, 50].map((p) => (
                            <button
                              key={p}
                              type="button"
                              onClick={() => handleSliderChange(key, p)}
                              className={`px-2 py-0.5 rounded font-mono transition ${
                                changePct === p
                                  ? 'bg-teal-500 text-slate-950 font-bold'
                                  : 'bg-slate-800/80 hover:bg-slate-800 text-slate-300 border border-slate-700/60'
                              }`}
                            >
                              {p > 0 ? `+${p}%` : `${p}%`}
                            </button>
                          ))}
                        </div>
                      </div>
                    )}
                  </div>
                );
              })}
            </div>

            {/* Action Buttons */}
            <div className="pt-2">
              <button
                onClick={handleRunSimulation}
                disabled={simulating || loadingReading || !currentReading}
                className="w-full py-3 px-4 rounded-xl bg-teal-500 hover:bg-teal-400 text-slate-950 font-bold text-xs flex items-center justify-center gap-2 shadow-lg shadow-teal-500/20 transition disabled:opacity-50 disabled:cursor-not-allowed"
              >
                {simulating ? (
                  <>
                    <RefreshCw className="w-4 h-4 animate-spin" />
                    <span>Recalculating CPCB AQI & Impact...</span>
                  </>
                ) : (
                  <>
                    <Play className="w-4 h-4 fill-current" />
                    <span>Run What-If Simulation</span>
                  </>
                )}
              </button>
            </div>
          </div>
        </div>

        {/* Right Column (7 Cols): Results, Impact Analysis & Preventive Guidance */}
        <div className="lg:col-span-7 space-y-6">
          {simulationResult ? (
            <>
              {/* SECTION A: Comparison Cards & Delta Banner */}
              <div className="p-5 rounded-2xl bg-slate-900/60 border border-slate-800 shadow-xl space-y-5">
                <div className="flex items-center justify-between pb-3 border-b border-slate-800">
                  <div className="flex items-center gap-2">
                    <Layers className="w-4 h-4 text-teal-400" />
                    <h2 className="text-xs font-bold uppercase tracking-wider text-slate-300">
                      Simulation Impact Analysis
                    </h2>
                  </div>
                  <div className="flex items-center gap-2">
                    {onNavigateToTab && (
                      <button
                        onClick={() => onNavigateToTab('reports')}
                        className="inline-flex items-center gap-1.5 px-3 py-1 rounded-lg bg-teal-500/10 hover:bg-teal-500/20 text-teal-300 border border-teal-500/30 text-xs font-medium transition shadow-sm"
                        title="Open Report Generator to export scenario report"
                      >
                        <FileText className="w-3.5 h-3.5" />
                        <span>Export Scenario Report</span>
                      </button>
                    )}
                    <span className="px-2.5 py-0.5 rounded-full text-[10px] font-mono uppercase bg-teal-500/10 text-teal-400 border border-teal-500/20">
                      WHAT_IF / SIMULATED
                    </span>
                  </div>
                </div>

                {/* Side-by-Side AQI Comparison */}
                <div className="grid grid-cols-1 sm:grid-cols-12 gap-4 items-center">
                  {/* Baseline AQI Card */}
                  <div className="sm:col-span-5 p-4 rounded-xl bg-slate-950/60 border border-slate-800 text-center space-y-1">
                    <span className="text-[10px] font-bold uppercase tracking-wider text-slate-400">
                      Current Baseline
                    </span>
                    <div className="text-3xl font-black text-white">
                      {simulationResult.baseline.aqi ?? 'N/A'}
                    </div>
                    {simulationResult.baseline.category && (
                      <span
                        className={`inline-block px-2.5 py-0.5 rounded-md text-[11px] font-semibold border ${
                          getAQICategoryStyle(simulationResult.baseline.category).bg
                        } ${getAQICategoryStyle(simulationResult.baseline.category).text} ${
                          getAQICategoryStyle(simulationResult.baseline.category).border
                        }`}
                      >
                        {simulationResult.baseline.category}
                      </span>
                    )}
                    <p className="text-[10px] text-slate-400 mt-1">
                      Dominant: <strong className="text-slate-200">{simulationResult.baseline.dominant_pollutant ?? 'N/A'}</strong>
                    </p>
                  </div>

                  {/* Delta & Direction Indicator */}
                  <div className="sm:col-span-2 flex flex-col items-center justify-center py-2">
                    <div
                      className={`p-2 rounded-full border mb-1 ${
                        simulationResult.impact.direction === 'IMPROVED'
                          ? 'bg-emerald-500/10 text-emerald-400 border-emerald-500/30'
                          : simulationResult.impact.direction === 'WORSENED'
                          ? 'bg-rose-500/10 text-rose-400 border-rose-500/30'
                          : 'bg-slate-800 text-slate-400 border-slate-700'
                      }`}
                    >
                      {simulationResult.impact.direction === 'IMPROVED' ? (
                        <TrendingDown className="w-5 h-5" />
                      ) : simulationResult.impact.direction === 'WORSENED' ? (
                        <TrendingUp className="w-5 h-5" />
                      ) : (
                        <Minus className="w-5 h-5" />
                      )}
                    </div>
                    <span
                      className={`text-xs font-mono font-bold ${
                        simulationResult.impact.direction === 'IMPROVED'
                          ? 'text-emerald-400'
                          : simulationResult.impact.direction === 'WORSENED'
                          ? 'text-rose-400'
                          : 'text-slate-400'
                      }`}
                    >
                      {simulationResult.impact.aqi_delta != null
                        ? simulationResult.impact.aqi_delta > 0
                          ? `+${simulationResult.impact.aqi_delta}`
                          : `${simulationResult.impact.aqi_delta}`
                        : '0'}
                    </span>
                    {simulationResult.impact.aqi_percent_delta != null && (
                      <span className="text-[10px] text-slate-400 font-mono">
                        ({simulationResult.impact.aqi_percent_delta > 0 ? `+` : ''}
                        {simulationResult.impact.aqi_percent_delta}%)
                      </span>
                    )}
                  </div>

                  {/* Simulated AQI Card */}
                  <div className="sm:col-span-5 p-4 rounded-xl bg-teal-950/20 border border-teal-500/30 text-center space-y-1 shadow-inner">
                    <span className="text-[10px] font-bold uppercase tracking-wider text-teal-300">
                      Simulated What-If
                    </span>
                    <div className="text-3xl font-black text-teal-200">
                      {simulationResult.scenario.simulated_aqi ?? 'N/A'}
                    </div>
                    {simulationResult.scenario.category && (
                      <span
                        className={`inline-block px-2.5 py-0.5 rounded-md text-[11px] font-semibold border ${
                          getAQICategoryStyle(simulationResult.scenario.category).bg
                        } ${getAQICategoryStyle(simulationResult.scenario.category).text} ${
                          getAQICategoryStyle(simulationResult.scenario.category).border
                        }`}
                      >
                        {simulationResult.scenario.category}
                      </span>
                    )}
                    <p className="text-[10px] text-slate-400 mt-1">
                      Dominant: <strong className="text-teal-300">{simulationResult.scenario.dominant_pollutant ?? 'N/A'}</strong>
                    </p>
                  </div>
                </div>

                {/* Transition Summary Pills */}
                <div className="grid grid-cols-1 sm:grid-cols-2 gap-3 pt-2">
                  <div className="p-3 rounded-xl bg-slate-950/50 border border-slate-800">
                    <span className="text-[10px] text-slate-400 uppercase font-semibold block mb-1">
                      Category Transition
                    </span>
                    <span className="text-xs font-bold text-white">
                      {simulationResult.impact.category_transition}
                    </span>
                  </div>
                  <div className="p-3 rounded-xl bg-slate-950/50 border border-slate-800">
                    <span className="text-[10px] text-slate-400 uppercase font-semibold block mb-1">
                      Dominant Pollutant Transition
                    </span>
                    <span className="text-xs font-bold text-white">
                      {simulationResult.impact.dominant_pollutant_transition}
                    </span>
                  </div>
                </div>

                {/* Threshold Impact Notice */}
                {simulationResult.impact.threshold_impact?.crosses_threshold && (
                  <div className="p-3.5 rounded-xl bg-rose-500/10 border border-rose-500/30 flex items-start gap-3 text-xs text-rose-300">
                    <AlertTriangle className="w-4 h-4 text-rose-400 shrink-0 mt-0.5" />
                    <div>
                      <span className="font-bold text-rose-200">Simulated Threshold Impact: </span>
                      <span>{simulationResult.impact.threshold_impact.message}</span>
                      <p className="text-[10px] text-slate-400 mt-1">
                        Notice: This is a hypothetical threshold calculation for scenario analysis. No active system alert is created.
                      </p>
                    </div>
                  </div>
                )}
              </div>

              {/* SECTION B: Pollutant Concentrations Comparison Table */}
              <div className="p-5 rounded-2xl bg-slate-900/60 border border-slate-800 shadow-xl space-y-4">
                <div className="flex items-center justify-between pb-3 border-b border-slate-800">
                  <h3 className="text-xs font-bold uppercase tracking-wider text-slate-300">
                    Pollutant Concentrations & Sub-Indices Comparison
                  </h3>
                  <span className="text-[10px] text-slate-400 font-mono">CPCB NAQI Standard</span>
                </div>

                <div className="overflow-x-auto">
                  <table className="w-full text-left text-xs font-mono">
                    <thead>
                      <tr className="border-b border-slate-800 text-slate-400 text-[10px] uppercase">
                        <th className="pb-2">Pollutant</th>
                        <th className="pb-2 text-right">Baseline</th>
                        <th className="pb-2 text-right">What-If</th>
                        <th className="pb-2 text-right">Delta %</th>
                        <th className="pb-2 text-right">Sub-Index (Base)</th>
                        <th className="pb-2 text-right">Sub-Index (Sim)</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-slate-800/60 text-slate-300">
                      {Object.entries(POLLUTANTS_INFO).map(([key, info]) => {
                        const baseVal = simulationResult.baseline.pollutant_values[key];
                        const simVal = simulationResult.scenario.modified_pollutant_values[key];
                        const changePct = simulationResult.scenario.pollutant_changes_percent[key] || 0;
                        const baseSub = simulationResult.baseline.pollutant_subindices[key];
                        const simSub = simulationResult.scenario.pollutant_subindices[key];

                        if (baseVal === null && simVal === null) return null;

                        const isChanged = changePct !== 0;

                        return (
                          <tr
                            key={key}
                            className={`hover:bg-slate-800/30 transition ${
                              isChanged ? 'bg-teal-500/5' : ''
                            }`}
                          >
                            <td className="py-2.5 font-bold text-white">
                              {info.label}
                              <span className="text-[10px] text-slate-500 font-normal ml-1">
                                ({info.unit})
                              </span>
                            </td>
                            <td className="py-2.5 text-right font-semibold">
                              {baseVal !== null && baseVal !== undefined ? baseVal.toFixed(1) : '—'}
                            </td>
                            <td
                              className={`py-2.5 text-right font-bold ${
                                isChanged ? 'text-teal-300' : 'text-slate-300'
                              }`}
                            >
                              {simVal !== null && simVal !== undefined ? simVal.toFixed(1) : '—'}
                            </td>
                            <td className="py-2.5 text-right">
                              {isChanged ? (
                                <span
                                  className={`px-1.5 py-0.5 rounded text-[10px] font-bold ${
                                    changePct > 0
                                      ? 'bg-rose-500/20 text-rose-300'
                                      : 'bg-emerald-500/20 text-emerald-300'
                                  }`}
                                >
                                  {changePct > 0 ? `+${changePct}%` : `${changePct}%`}
                                </span>
                              ) : (
                                <span className="text-slate-500">0%</span>
                              )}
                            </td>
                            <td className="py-2.5 text-right text-slate-400">
                              {baseSub !== null && baseSub !== undefined ? baseSub : '—'}
                            </td>
                            <td
                              className={`py-2.5 text-right font-bold ${
                                simSub !== baseSub ? 'text-teal-300' : 'text-slate-400'
                              }`}
                            >
                              {simSub !== null && simSub !== undefined ? simSub : '—'}
                            </td>
                          </tr>
                        );
                      })}
                    </tbody>
                  </table>
                </div>
              </div>

              {/* SECTION C: Recalculated Phase 11 Preventive Guidance */}
              <div className="p-5 rounded-2xl bg-slate-900/60 border border-slate-800 shadow-xl space-y-4">
                <div className="flex items-center justify-between pb-3 border-b border-slate-800">
                  <div className="flex items-center gap-2">
                    <Sparkles className="w-4 h-4 text-teal-400" />
                    <h3 className="text-xs font-bold uppercase tracking-wider text-slate-300">
                      What-If Prevention Impact
                    </h3>
                  </div>
                  <span className="px-2 py-0.5 rounded text-[10px] font-mono text-teal-400 bg-teal-500/10 border border-teal-500/20">
                    SIMULATED SCENARIO
                  </span>
                </div>

                <p className="text-xs text-slate-400">
                  Preventive guidance dynamically recalculated via the Phase 11 engine reflecting the simulated AQI ({simulationResult.scenario.simulated_aqi}) and dominant pollutant ({simulationResult.scenario.dominant_pollutant}).
                </p>

                {simulationResult.recommendations.length > 0 ? (
                  <div className="space-y-3 pt-1">
                    {simulationResult.recommendations.map((rec) => {
                      const theme = PRIORITY_THEMES[rec.priority] || PRIORITY_THEMES.INFO;
                      return (
                        <div
                          key={rec.id}
                          className={`p-4 rounded-xl border ${theme.bg} ${theme.border} space-y-2 transition`}
                        >
                          <div className="flex items-center justify-between gap-2">
                            <div className="flex items-center gap-2">
                              <span className={`px-2 py-0.5 rounded text-[10px] font-bold border ${theme.badge}`}>
                                {rec.priority}
                              </span>
                              <span className="px-2 py-0.5 rounded text-[10px] font-mono bg-slate-900 text-slate-400 border border-slate-800">
                                {rec.type}
                              </span>
                            </div>
                            <span className="text-[10px] font-mono text-slate-500">
                              WHAT_IF / SIMULATED
                            </span>
                          </div>

                          <h4 className="text-xs font-bold text-white">{rec.title}</h4>
                          <p className="text-xs text-slate-300">{rec.action}</p>

                          <div className="p-2.5 rounded-lg bg-slate-950/60 border border-slate-800/80 text-[11px] text-slate-400 flex items-start gap-2">
                            <Info className="w-3.5 h-3.5 text-teal-400 shrink-0 mt-0.5" />
                            <div>
                              <strong className="text-slate-300">Trigger: </strong>
                              <span>{rec.reason}</span>
                            </div>
                          </div>
                        </div>
                      );
                    })}
                  </div>
                ) : (
                  <p className="text-xs text-slate-500 italic py-2">No recommendations generated.</p>
                )}
              </div>
            </>
          ) : (
            /* Empty State Prompt */
            <div className="p-12 rounded-2xl bg-slate-900/40 border border-dashed border-slate-800 text-center space-y-3">
              <div className="w-12 h-12 rounded-2xl bg-slate-800/80 text-teal-400 flex items-center justify-center mx-auto shadow-inner">
                <Sliders className="w-6 h-6" />
              </div>
              <div className="space-y-1 max-w-md mx-auto">
                <h3 className="text-sm font-semibold text-slate-200">
                  Ready to Run What-If Simulation
                </h3>
                <p className="text-xs text-slate-400">
                  Adjust pollutant percentage sliders on the left (e.g. +20% PM2.5, -15% NO2) and click <strong>"Run What-If Simulation"</strong> to evaluate the impact on AQI and prevention protocols.
                </p>
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
};

export default WhatIfPage;
