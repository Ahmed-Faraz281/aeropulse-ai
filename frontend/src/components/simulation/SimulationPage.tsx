import React, { useState, useEffect } from 'react';
import type { User } from '../../types/auth';
import type { Location } from '../../types/air_quality';
import type {
  SimulationRequest,
  SimulationResponse,
  SimulationScenario,
  SimulationRunMetadata,
} from '../../types/simulation';
import { getLocations } from '../../services/air_quality';
import { runSimulation, getLatestSimulation } from '../../services/simulation';
import {
  Cpu,
  Play,
  CheckCircle2,
  AlertTriangle,
  Layers,
  ShieldAlert,
  Sparkles,
  ArrowRight,
  Info,
  Hash,
  Activity,
} from 'lucide-react';

interface SimulationPageProps {
  currentUser: User;
  onNavigateToTab: (tabId: string) => void;
}

const SCENARIOS: { key: SimulationScenario; label: string; description: string }[] = [
  {
    key: 'NORMAL',
    label: 'Normal Diurnal Dynamics',
    description: 'Standard diurnal rush-hour peaks and nocturnal boundary layer variations.',
  },
  {
    key: 'RISING_POLLUTION',
    label: 'Rising Pollution Trend',
    description: 'Continuous monotonic accumulation simulating meteorological stagnation.',
  },
  {
    key: 'POLLUTION_SPIKE',
    label: 'Transient Pollution Spike',
    description: 'Sharp elevated burst lasting 2 to 4 hours before receding toward baseline.',
  },
  {
    key: 'PERSISTENT_ELEVATED',
    label: 'Persistent Elevated Pollution',
    description: 'Sustained elevated exposure across the duration without artificial clamping.',
  },
  {
    key: 'RECOVERY',
    label: 'Atmospheric Recovery',
    description: 'Initial high pollution gradually cleansing toward clean background baseline.',
  },
];

const DURATIONS = [
  { hours: 6, label: '6 Hours' },
  { hours: 12, label: '12 Hours' },
  { hours: 24, label: '24 Hours' },
  { hours: 48, label: '48 Hours' },
];

const INTERVALS = [
  { minutes: 15, label: '15 Minutes' },
  { minutes: 30, label: '30 Minutes' },
  { minutes: 60, label: '1 Hour' },
];

const INTENSITIES = [
  { value: 0.7, label: 'Low (0.7x)' },
  { value: 1.0, label: 'Normal (1.0x)' },
  { value: 1.5, label: 'High (1.5x)' },
];

export const SimulationPage: React.FC<SimulationPageProps> = ({
  currentUser,
  onNavigateToTab,
}) => {
  const isViewer = currentUser.role === 'viewer';

  // Form State
  const [locations, setLocations] = useState<Location[]>([]);
  const [selectedLocationIds, setSelectedLocationIds] = useState<number[]>([]);
  const [scenario, setScenario] = useState<SimulationScenario>('NORMAL');
  const [durationHours, setDurationHours] = useState<number>(24);
  const [intervalMinutes, setIntervalMinutes] = useState<number>(60);
  const [intensity, setIntensity] = useState<number>(1.0);
  const [seedInput, setSeedInput] = useState<string>('42');

  // Execution State
  const [loadingLocations, setLoadingLocations] = useState<boolean>(true);
  const [running, setRunning] = useState<boolean>(false);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [result, setResult] = useState<SimulationResponse | null>(null);
  const [latestRun, setLatestRun] = useState<SimulationRunMetadata | null>(null);

  // Load locations and latest simulation metadata on mount
  useEffect(() => {
    const init = async () => {
      setLoadingLocations(true);
      try {
        const [locs, latest] = await Promise.allSettled([
          getLocations(),
          getLatestSimulation(),
        ]);
        if (locs.status === 'fulfilled') {
          setLocations(locs.value);
          // Default select all active stations
          setSelectedLocationIds(locs.value.map((l) => l.id));
        }
        if (latest.status === 'fulfilled' && latest.value) {
          setLatestRun(latest.value);
        }
      } catch {
        setErrorMessage('Failed to load simulation environment.');
      } finally {
        setLoadingLocations(false);
      }
    };
    init();
  }, []);

  // Compute calculated records count for backend safety limit
  const stepsPerLocation = Math.floor((durationHours * 60) / intervalMinutes) + 1;
  const estimatedTotalReadings = stepsPerLocation * selectedLocationIds.length;
  const exceedsLimit = estimatedTotalReadings > 1000;

  // Toggle single location
  const toggleLocation = (id: number) => {
    setSelectedLocationIds((prev) =>
      prev.includes(id) ? prev.filter((item) => item !== id) : [...prev, id]
    );
  };

  // Select all / Deselect all
  const selectAllLocations = () => {
    setSelectedLocationIds(locations.map((l) => l.id));
  };
  const deselectAllLocations = () => {
    setSelectedLocationIds([]);
  };

  // Run simulation handler
  const handleExecute = async () => {
    if (isViewer || exceedsLimit || selectedLocationIds.length === 0) return;

    setRunning(true);
    setErrorMessage(null);
    setResult(null);

    const parsedSeed = seedInput.trim() !== '' ? parseInt(seedInput, 10) : null;
    const payload: SimulationRequest = {
      location_ids: selectedLocationIds,
      duration_hours: durationHours,
      interval_minutes: intervalMinutes,
      scenario,
      intensity,
      seed: isNaN(parsedSeed as number) ? null : parsedSeed,
    };

    try {
      const response = await runSimulation(payload);
      setResult(response);
      setLatestRun({
        scenario: response.scenario,
        location_count: response.locations,
        readings_generated: response.readings_generated,
        readings_inserted: response.readings_inserted,
        readings_skipped: response.readings_skipped,
        started_at: response.started_at,
        completed_at: response.completed_at,
        seed: response.seed,
      });
    } catch (err: any) {
      const detail = err.response?.data?.detail || 'Simulation execution failed.';
      setErrorMessage(typeof detail === 'string' ? detail : JSON.stringify(detail));
    } finally {
      setRunning(false);
    }
  };

  return (
    <div className="space-y-6">
      {/* SECTION 1: Page Header & Software Notice */}
      <div className="p-6 rounded-2xl bg-gradient-to-r from-slate-900 via-slate-900/90 to-indigo-950/40 border border-slate-800 shadow-xl relative overflow-hidden">
        <div className="absolute -right-12 -top-12 w-64 h-64 bg-indigo-500/10 rounded-full blur-3xl pointer-events-none" />

        <div className="flex flex-col lg:flex-row lg:items-center justify-between gap-4 relative z-10">
          <div className="space-y-1">
            <div className="inline-flex items-center gap-2 px-2.5 py-1 rounded-full bg-indigo-500/15 border border-indigo-500/30 text-indigo-300 text-xs font-semibold">
              <Cpu className="w-3.5 h-3.5 text-indigo-400" />
              Phase 8 Simulation Engine Operational
            </div>
            <h2 className="text-2xl font-bold tracking-tight text-white">
              Deterministic Air Quality Simulation Engine
            </h2>
            <p className="text-sm text-slate-400 max-w-2xl">
              Generates realistic multi-pollutant diurnal sequences for testing, scenario benchmarking, and ML training.
            </p>
          </div>

          <div className="flex items-center gap-2 self-start lg:self-auto">
            <span className="px-3 py-1.5 rounded-xl text-xs font-mono font-bold bg-indigo-500/10 text-indigo-400 border border-indigo-500/30">
              PROVENANCE: SIMULATED
            </span>
          </div>
        </div>
      </div>

      {/* Prominent Mandatory Simulation Notice */}
      <div className="p-4 rounded-xl bg-amber-500/10 border border-amber-500/20 flex items-start gap-3 text-xs text-amber-200">
        <ShieldAlert className="w-4 h-4 text-amber-400 shrink-0 mt-0.5" />
        <div>
          <span className="font-semibold text-amber-300">Mandatory Data Provenance Notice: </span>
          This data is software-generated for demonstration, testing, and algorithmic analysis. It is not a physical sensor measurement. All generated observations are permanently tagged with source provenance <code className="bg-slate-900 px-1 py-0.5 rounded text-amber-300 font-mono">SIMULATED</code> and passed through the official CPCB calculation engine.
        </div>
      </div>

      {/* Role-Based Access Notice for Viewers */}
      {isViewer && (
        <div className="p-4 rounded-xl bg-slate-900/90 border border-slate-800 text-xs text-slate-400 flex items-center gap-2">
          <Info className="w-4 h-4 text-teal-400 shrink-0" />
          <span>
            <strong className="text-slate-200">Viewing Mode Active: </strong>
            Role-Based Access Control limits simulation execution to <strong>Admin</strong> and <strong>Analyst</strong> accounts. Form controls are display-only.
          </span>
        </div>
      )}

      {/* Error Alert */}
      {errorMessage && (
        <div className="p-4 rounded-xl bg-rose-500/10 border border-rose-500/20 text-rose-300 text-xs flex items-center justify-between">
          <div className="flex items-center gap-2">
            <AlertTriangle className="w-4 h-4 shrink-0 text-rose-400" />
            <span>{errorMessage}</span>
          </div>
          <button onClick={() => setErrorMessage(null)} className="underline hover:text-white">
            Dismiss
          </button>
        </div>
      )}

      {/* SECTION 2: Interactive Simulation Configuration Form */}
      <div className="grid grid-cols-1 lg:grid-cols-12 gap-6">
        {/* Left Column: Form Controls */}
        <div className="lg:col-span-8 space-y-6">
          <div className="p-6 rounded-2xl bg-slate-900/70 border border-slate-800 shadow-xl space-y-6">
            <div className="flex items-center justify-between border-b border-slate-800 pb-3">
              <div className="flex items-center gap-2">
                <Sparkles className="w-4 h-4 text-indigo-400" />
                <h3 className="text-sm font-bold text-white uppercase tracking-wider">
                  Simulation Parameters
                </h3>
              </div>
              <span className="text-[11px] font-mono text-slate-500">
                Safe Backend Bound: Max 1,000 Records
              </span>
            </div>

            {/* 1. Scenario Selection */}
            <div className="space-y-2">
              <label className="text-xs font-semibold text-slate-300 uppercase tracking-wider block">
                Atmospheric Dynamics Scenario
              </label>
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-2.5">
                {SCENARIOS.map((item) => {
                  const isSelected = scenario === item.key;
                  return (
                    <div
                      key={item.key}
                      onClick={() => !isViewer && setScenario(item.key)}
                      className={`p-3 rounded-xl border transition cursor-pointer flex flex-col justify-between ${
                        isSelected
                          ? 'bg-indigo-500/15 border-indigo-500 text-white shadow-md'
                          : 'bg-slate-950/60 border-slate-800 text-slate-400 hover:border-slate-700 hover:text-slate-200'
                      } ${isViewer ? 'opacity-60 cursor-not-allowed' : ''}`}
                    >
                      <div className="flex items-center justify-between">
                        <span className="text-xs font-bold font-mono">{item.label}</span>
                        <div
                          className={`w-3 h-3 rounded-full border ${
                            isSelected ? 'bg-indigo-400 border-indigo-300' : 'border-slate-600'
                          }`}
                        />
                      </div>
                      <p className="text-[10px] text-slate-400 pt-1 leading-snug">{item.description}</p>
                    </div>
                  );
                })}
              </div>
            </div>

            {/* 2. Duration & Temporal Interval */}
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-4 pt-1">
              <div className="space-y-2">
                <label className="text-xs font-semibold text-slate-300 uppercase tracking-wider block">
                  Duration Window
                </label>
                <div className="grid grid-cols-2 gap-2">
                  {DURATIONS.map((d) => (
                    <button
                      key={d.hours}
                      type="button"
                      disabled={isViewer}
                      onClick={() => setDurationHours(d.hours)}
                      className={`py-2 px-3 rounded-xl text-xs font-mono font-semibold border transition ${
                        durationHours === d.hours
                          ? 'bg-teal-500 text-slate-950 border-teal-400 shadow-sm'
                          : 'bg-slate-950/60 border-slate-800 text-slate-400 hover:border-slate-700 hover:text-white'
                      }`}
                    >
                      {d.label}
                    </button>
                  ))}
                </div>
              </div>

              <div className="space-y-2">
                <label className="text-xs font-semibold text-slate-300 uppercase tracking-wider block">
                  Temporal Frequency
                </label>
                <div className="grid grid-cols-3 gap-2">
                  {INTERVALS.map((inv) => (
                    <button
                      key={inv.minutes}
                      type="button"
                      disabled={isViewer}
                      onClick={() => setIntervalMinutes(inv.minutes)}
                      className={`py-2 px-2 rounded-xl text-xs font-mono font-semibold border transition ${
                        intervalMinutes === inv.minutes
                          ? 'bg-teal-500 text-slate-950 border-teal-400 shadow-sm'
                          : 'bg-slate-950/60 border-slate-800 text-slate-400 hover:border-slate-700 hover:text-white'
                      }`}
                    >
                      {inv.label}
                    </button>
                  ))}
                </div>
              </div>
            </div>

            {/* 3. Intensity & Deterministic Seed */}
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-4 pt-1">
              <div className="space-y-2">
                <label className="text-xs font-semibold text-slate-300 uppercase tracking-wider block">
                  Pollutant Intensity Multiplier
                </label>
                <div className="grid grid-cols-3 gap-2">
                  {INTENSITIES.map((int) => (
                    <button
                      key={int.value}
                      type="button"
                      disabled={isViewer}
                      onClick={() => setIntensity(int.value)}
                      className={`py-2 px-2 rounded-xl text-xs font-mono font-semibold border transition ${
                        intensity === int.value
                          ? 'bg-indigo-500 text-white border-indigo-400 shadow-sm'
                          : 'bg-slate-950/60 border-slate-800 text-slate-400 hover:border-slate-700 hover:text-white'
                      }`}
                    >
                      {int.label}
                    </button>
                  ))}
                </div>
              </div>

              <div className="space-y-2">
                <div className="flex items-center justify-between">
                  <label className="text-xs font-semibold text-slate-300 uppercase tracking-wider">
                    Deterministic Seed
                  </label>
                  <span className="text-[10px] text-slate-500 font-mono">Optional</span>
                </div>
                <div className="relative">
                  <Hash className="w-3.5 h-3.5 text-slate-500 absolute left-3 top-1/2 -translate-y-1/2 pointer-events-none" />
                  <input
                    type="number"
                    disabled={isViewer}
                    placeholder="e.g. 42 for reproducible run"
                    value={seedInput}
                    onChange={(e) => setSeedInput(e.target.value)}
                    className="w-full pl-8 pr-3 py-2 rounded-xl bg-slate-950/60 border border-slate-800 text-xs font-mono text-slate-200 placeholder-slate-600 outline-none focus:border-indigo-500/60"
                  />
                </div>
              </div>
            </div>

            {/* 4. Target Stations Selection */}
            <div className="space-y-3 pt-2">
              <div className="flex items-center justify-between">
                <div>
                  <label className="text-xs font-semibold text-slate-300 uppercase tracking-wider block">
                    Target Monitoring Stations
                  </label>
                  <p className="text-[10px] text-slate-500">
                    Each station applies a unique mathematical Simulation Profile
                  </p>
                </div>
                <div className="flex items-center gap-2">
                  <button
                    type="button"
                    disabled={isViewer}
                    onClick={selectAllLocations}
                    className="text-[11px] text-indigo-400 hover:underline disabled:opacity-50"
                  >
                    Select All
                  </button>
                  <span className="text-slate-600">•</span>
                  <button
                    type="button"
                    disabled={isViewer}
                    onClick={deselectAllLocations}
                    className="text-[11px] text-slate-400 hover:underline disabled:opacity-50"
                  >
                    Clear
                  </button>
                </div>
              </div>

              {loadingLocations ? (
                <div className="h-20 bg-slate-950/50 rounded-xl animate-pulse" />
              ) : (
                <div className="grid grid-cols-1 sm:grid-cols-2 gap-2 max-h-48 overflow-y-auto pr-1">
                  {locations.map((loc) => {
                    const isChecked = selectedLocationIds.includes(loc.id);
                    return (
                      <div
                        key={loc.id}
                        onClick={() => !isViewer && toggleLocation(loc.id)}
                        className={`p-2.5 rounded-xl border transition cursor-pointer flex items-center justify-between ${
                          isChecked
                            ? 'bg-slate-800 border-teal-500/50 text-white'
                            : 'bg-slate-950/40 border-slate-800/80 text-slate-400 hover:border-slate-700'
                        } ${isViewer ? 'cursor-not-allowed opacity-60' : ''}`}
                      >
                        <div className="space-y-0.5">
                          <div className="text-xs font-bold text-slate-200">{loc.name}</div>
                          <div className="text-[10px] text-slate-400">
                            {loc.city} • <span className="font-mono text-[9px] text-indigo-400">Simulation Profile</span>
                          </div>
                        </div>
                        <input
                          type="checkbox"
                          checked={isChecked}
                          disabled={isViewer}
                          onChange={() => {}}
                          className="w-4 h-4 rounded text-teal-500 bg-slate-900 border-slate-700"
                        />
                      </div>
                    );
                  })}
                </div>
              )}
            </div>

            {/* Execution Bar */}
            <div className="pt-4 border-t border-slate-800 flex flex-col sm:flex-row sm:items-center justify-between gap-4">
              <div className="text-xs font-mono space-y-0.5">
                <div className="flex items-center gap-2">
                  <span className="text-slate-400">Calculated Batch Size:</span>
                  <span
                    className={`font-bold ${
                      exceedsLimit ? 'text-rose-400' : 'text-teal-300'
                    }`}
                  >
                    {estimatedTotalReadings} readings
                  </span>
                  <span className="text-[10px] text-slate-500">
                    ({stepsPerLocation} steps × {selectedLocationIds.length} stations)
                  </span>
                </div>
                {exceedsLimit && (
                  <p className="text-[11px] text-rose-400">
                    Exceeds maximum safety limit of 1,000 records. Reduce duration or station count.
                  </p>
                )}
              </div>

              <button
                type="button"
                onClick={handleExecute}
                disabled={isViewer || running || exceedsLimit || selectedLocationIds.length === 0}
                className="py-2.5 px-5 rounded-xl font-semibold text-xs transition flex items-center justify-center gap-2 shadow-lg disabled:opacity-40 disabled:cursor-not-allowed bg-indigo-500 hover:bg-indigo-400 text-white shadow-indigo-500/20"
              >
                <Play className={`w-4 h-4 ${running ? 'animate-spin' : ''}`} />
                <span>{running ? 'Simulating Telemetry...' : 'Execute Simulation'}</span>
              </button>
            </div>
          </div>
        </div>

        {/* Right Column: Execution Output & Latest Metadata */}
        <div className="lg:col-span-4 space-y-6">
          {/* Recent Simulation Result Card */}
          {result && (
            <div className="p-6 rounded-2xl bg-slate-900/90 border border-emerald-500/40 shadow-xl space-y-4 animate-fadeIn">
              <div className="flex items-center gap-2 text-emerald-400">
                <CheckCircle2 className="w-5 h-5" />
                <h4 className="text-sm font-bold uppercase tracking-wider">
                  Simulation Succeeded
                </h4>
              </div>

              <div className="p-3.5 rounded-xl bg-slate-950/60 border border-slate-800 space-y-2 text-xs font-mono">
                <div className="flex justify-between">
                  <span className="text-slate-400">Scenario:</span>
                  <span className="text-white font-bold">{result.scenario}</span>
                </div>
                <div className="flex justify-between">
                  <span className="text-slate-400">Stations Processed:</span>
                  <span className="text-white font-bold">{result.locations}</span>
                </div>
                <div className="flex justify-between">
                  <span className="text-slate-400">Readings Generated:</span>
                  <span className="text-white font-bold">{result.readings_generated}</span>
                </div>
                <div className="flex justify-between">
                  <span className="text-slate-400">Committed to DB:</span>
                  <span className="text-emerald-400 font-bold">{result.readings_inserted}</span>
                </div>
                <div className="flex justify-between">
                  <span className="text-slate-400">Skipped (Duplicate):</span>
                  <span className="text-slate-400">{result.readings_skipped}</span>
                </div>
                <div className="flex justify-between">
                  <span className="text-slate-400">Provenance:</span>
                  <span className="text-teal-400 font-bold">{result.source_type}</span>
                </div>
                <div className="flex justify-between">
                  <span className="text-slate-400">Execution Duration:</span>
                  <span className="text-slate-300">{result.duration_seconds}s</span>
                </div>
              </div>

              {/* Navigation Shortcuts */}
              <div className="grid grid-cols-2 gap-2 pt-2">
                <button
                  type="button"
                  onClick={() => onNavigateToTab('dashboard')}
                  className="py-2 px-3 rounded-xl bg-slate-800 hover:bg-teal-500 hover:text-slate-950 text-slate-200 text-xs font-semibold border border-slate-700 transition flex items-center justify-center gap-1.5"
                >
                  <span>Dashboard</span>
                  <ArrowRight className="w-3.5 h-3.5" />
                </button>
                <button
                  type="button"
                  onClick={() => onNavigateToTab('map')}
                  className="py-2 px-3 rounded-xl bg-slate-800 hover:bg-indigo-500 hover:text-white text-slate-200 text-xs font-semibold border border-slate-700 transition flex items-center justify-center gap-1.5"
                >
                  <span>Pollution Map</span>
                  <ArrowRight className="w-3.5 h-3.5" />
                </button>
              </div>
            </div>
          )}

          {/* Historical Latest Run Summary */}
          {latestRun && (
            <div className="p-5 rounded-2xl bg-slate-900/60 border border-slate-800 space-y-3">
              <div className="flex items-center justify-between border-b border-slate-800 pb-2">
                <div className="flex items-center gap-2">
                  <Activity className="w-4 h-4 text-indigo-400" />
                  <h4 className="text-xs font-bold text-slate-300 uppercase tracking-wider">
                    Last Simulation Run
                  </h4>
                </div>
                <span className="px-2 py-0.5 rounded text-[10px] font-mono bg-slate-800 text-slate-300">
                  {latestRun.scenario}
                </span>
              </div>

              <div className="space-y-1.5 text-xs font-mono text-slate-400">
                <div className="flex justify-between">
                  <span>Stations:</span>
                  <span className="text-slate-200">{latestRun.location_count}</span>
                </div>
                <div className="flex justify-between">
                  <span>Total Readings:</span>
                  <span className="text-slate-200">{latestRun.readings_inserted}</span>
                </div>
                <div className="flex justify-between">
                  <span>Completed:</span>
                  <span className="text-slate-200">
                    {new Date(latestRun.completed_at).toLocaleTimeString()}
                  </span>
                </div>
                {latestRun.seed !== null && (
                  <div className="flex justify-between">
                    <span>Seed:</span>
                    <span className="text-slate-200">{latestRun.seed}</span>
                  </div>
                )}
              </div>
            </div>
          )}

          {/* Pipeline Verification Card */}
          <div className="p-5 rounded-2xl bg-slate-900/40 border border-slate-800 space-y-3 text-xs text-slate-400">
            <h4 className="font-bold text-slate-300 text-xs uppercase tracking-wider flex items-center gap-1.5">
              <Layers className="w-3.5 h-3.5 text-teal-400" />
              <span>Full Pipeline Integration</span>
            </h4>
            <div className="space-y-1.5 font-mono text-[11px]">
              <div className="p-1.5 rounded bg-slate-950/60 border border-slate-800/80">
                1. Stochastic Diurnal Generator
              </div>
              <div className="p-1.5 rounded bg-slate-950/60 border border-slate-800/80">
                2. Data Quality Triage & Validation
              </div>
              <div className="p-1.5 rounded bg-slate-950/60 border border-slate-800/80">
                3. CPCB India NAQI Engine
              </div>
              <div className="p-1.5 rounded bg-slate-950/60 border border-slate-800/80">
                4. Pre-cached AQIRecord Storage
              </div>
              <div className="p-1.5 rounded bg-slate-950/60 border border-slate-800/80">
                5. Dashboard & Spatial Map Consumption
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
};
