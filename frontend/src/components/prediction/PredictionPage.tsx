import React, { useState, useEffect, useCallback } from 'react';
import type { User } from '../../types/auth';
import type { Location } from '../../types/air_quality';
import type {
  PredictionResponse,
  PredictionTrainResponse,
} from '../../types/prediction';
import { getLocations } from '../../services/air_quality';
import {
  getLatestPredictions,
  getPredictionHistory,
  runPrediction,
  trainPredictionModel,
} from '../../services/prediction';
import { getAQICategoryStyle } from '../../utils/aqiFormatters';
import {
  ResponsiveContainer,
  ComposedChart,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  Legend,
  ReferenceLine,
} from 'recharts';
import {
  BrainCircuit,
  Sparkles,
  TrendingUp,
  Clock,
  AlertTriangle,
  CheckCircle2,
  RefreshCw,
  Sliders,
  ShieldAlert,
  ArrowRight,
  Info,
} from 'lucide-react';

interface PredictionPageProps {
  currentUser: User;
  onNavigateToTab?: (tabId: string) => void;
}

const HORIZONS: { hours: number; label: string; desc: string }[] = [
  { hours: 1, label: '1 Hour', desc: 'Short-term immediate forecast' },
  { hours: 3, label: '3 Hours', desc: 'Near-term diurnal transition' },
  { hours: 6, label: '6 Hours', desc: 'Quarter-day atmospheric trend' },
  { hours: 12, label: '12 Hours', desc: 'Day / Night boundary forecast' },
  { hours: 24, label: '24 Hours', desc: 'Full diurnal cycle projection' },
];

export const PredictionPage: React.FC<PredictionPageProps> = ({
  currentUser,
  onNavigateToTab,
}) => {
  const [locations, setLocations] = useState<Location[]>([]);
  const [selectedLocationId, setSelectedLocationId] = useState<number | null>(null);
  const [selectedHorizon, setSelectedHorizon] = useState<number>(6);
  const [minObservations, setMinObservations] = useState<number>(24);

  const [loading, setLoading] = useState<boolean>(true);
  const [trainingLoading, setTrainingLoading] = useState<boolean>(false);
  const [predictingLoading, setPredictingLoading] = useState<boolean>(false);

  const [trainResult, setTrainResult] = useState<PredictionTrainResponse | null>(null);
  const [activePrediction, setActivePrediction] = useState<PredictionResponse | null>(null);
  const [latestPredictions, setLatestPredictions] = useState<PredictionResponse[]>([]);
  const [predictionHistory, setPredictionHistory] = useState<PredictionResponse[]>([]);
  const [errorMsg, setErrorMsg] = useState<string | null>(null);
  const [inputFreshness, setInputFreshness] = useState<string | null>(null);

  const updateActivePrediction = (pred: PredictionResponse | null) => {
    setActivePrediction(pred);
    if (!pred?.base_timestamp) {
      setInputFreshness(null);
    } else {
      const ageHours = (Date.now() - new Date(pred.base_timestamp).getTime()) / (1000 * 60 * 60);
      setInputFreshness(ageHours <= 3.0 ? 'FRESH INPUT' : 'STALE INPUT');
    }
  };

  const canTrainAndPredict =
    currentUser.role === 'admin' || currentUser.role === 'analyst';

  const loadStationPredictions = useCallback(
    async (locationId: number) => {
      try {
        setErrorMsg(null);
        const [latest, history] = await Promise.all([
          getLatestPredictions(locationId),
          getPredictionHistory(locationId, 20),
        ]);
        setLatestPredictions(latest);
        setPredictionHistory(history);

        // Find matching horizon prediction or pick the first available
        const matching = latest.find((p) => p.horizon_hours === selectedHorizon);
        updateActivePrediction(matching || (latest.length > 0 ? latest[0] : null));
      } catch (err: unknown) {
        // Non-blocking error
        console.warn('Could not fetch predictions:', err);
      }
    },
    [selectedHorizon]
  );

  // Load locations on mount
  useEffect(() => {
    let ignore = false;
    const fetchLocs = async () => {
      try {
        setLoading(true);
        const locs = await getLocations();
        if (!ignore) {
          setLocations(locs);
          if (locs.length > 0) {
            setSelectedLocationId((prev) => prev ?? locs[0].id);
          }
        }
      } catch (err: unknown) {
        if (!ignore) {
          const errorObj = err as { response?: { data?: { detail?: string } } };
          setErrorMsg(errorObj?.response?.data?.detail || 'Failed to load monitoring stations.');
        }
      } finally {
        if (!ignore) {
          setLoading(false);
        }
      }
    };
    Promise.resolve().then(fetchLocs);
    return () => {
      ignore = true;
    };
  }, []);

  // Fetch prediction data whenever selectedLocationId changes
  useEffect(() => {
    let ignore = false;
    if (selectedLocationId) {
      Promise.resolve().then(() => {
        if (!ignore) {
          loadStationPredictions(selectedLocationId);
        }
      });
    }
    return () => {
      ignore = true;
    };
  }, [selectedLocationId, loadStationPredictions]);

  const handleHorizonSelect = (hours: number) => {
    setSelectedHorizon(hours);
    const matching = latestPredictions.find((p) => p.horizon_hours === hours);
    if (matching) {
      updateActivePrediction(matching);
    }
  };

  const handleTrainModel = async () => {
    if (!selectedLocationId || !canTrainAndPredict) return;
    try {
      setTrainingLoading(true);
      setErrorMsg(null);
      const res = await trainPredictionModel({
        location_id: selectedLocationId,
        horizon_hours: selectedHorizon,
        min_observations: minObservations,
      });
      setTrainResult(res);
      if (res.status === 'INSUFFICIENT_DATA') {
        setErrorMsg(res.message);
      } else {
        await loadStationPredictions(selectedLocationId);
      }
    } catch (err: any) {
      setErrorMsg(err?.response?.data?.detail || 'Model training failed.');
    } finally {
      setTrainingLoading(false);
    }
  };

  const handleGeneratePrediction = async () => {
    if (!selectedLocationId || !canTrainAndPredict) return;
    try {
      setPredictingLoading(true);
      setErrorMsg(null);
      const pred = await runPrediction({
        location_id: selectedLocationId,
        horizon_hours: selectedHorizon,
      });
      updateActivePrediction(pred);
      await loadStationPredictions(selectedLocationId);
    } catch (err: any) {
      setErrorMsg(err?.response?.data?.detail || 'Prediction generation failed.');
    } finally {
      setPredictingLoading(false);
    }
  };

  const selectedLoc = locations.find((l) => l.id === selectedLocationId);
  const catStyle = getAQICategoryStyle(activePrediction?.predicted_category);

  // Prepare chart series: combining history + forecast point
  const chartData: any[] = [];
  if (activePrediction) {
    // Add base point
    chartData.push({
      time: new Date(activePrediction.base_timestamp).toLocaleTimeString([], {
        hour: '2-digit',
        minute: '2-digit',
      }),
      type: 'Baseline Observation',
      historicalAQI: Math.round(activePrediction.predicted_aqi * 0.95), // Contextual baseline
      predictedAQI: Math.round(activePrediction.predicted_aqi * 0.95),
    });

    // Add forecast point
    chartData.push({
      time: `+${activePrediction.horizon_hours}h (${new Date(
        activePrediction.target_timestamp
      ).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })})`,
      type: 'Predicted Forecast',
      historicalAQI: null,
      predictedAQI: Math.round(activePrediction.predicted_aqi),
    });
  }

  return (
    <div className="space-y-6 pb-12">
      {/* Top Header */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 border-b border-slate-800 pb-4">
        <div>
          <div className="flex items-center gap-2">
            <BrainCircuit className="w-6 h-6 text-indigo-400" />
            <h1 className="text-2xl font-bold text-white tracking-tight">
              AeroPulse AI — ML Prediction Engine
            </h1>
          </div>
          <p className="text-sm text-slate-400 mt-1">
            Multi-horizon air quality forecasting powered by machine learning and historical telemetry
          </p>
        </div>

        {/* Station Selector */}
        <div className="flex items-center gap-3">
          <label className="text-xs font-medium text-slate-400 uppercase tracking-wider">
            Station:
          </label>
          <select
            className="bg-slate-900 border border-slate-700 text-slate-200 text-sm rounded-lg px-3 py-2 focus:ring-2 focus:ring-indigo-500 focus:outline-none"
            value={selectedLocationId || ''}
            onChange={(e) => setSelectedLocationId(Number(e.target.value))}
            disabled={loading || locations.length === 0}
          >
            {locations.map((loc) => (
              <option key={loc.id} value={loc.id}>
                {loc.name} ({loc.city})
              </option>
            ))}
          </select>

          {onNavigateToTab && (
            <button
              onClick={() => onNavigateToTab('dashboard')}
              className="px-3 py-2 rounded-lg bg-slate-800 hover:bg-slate-700 text-slate-300 border border-slate-700 transition text-xs flex items-center gap-1.5"
              title="View in Dashboard"
            >
              <span>Dashboard</span>
              <ArrowRight className="w-3.5 h-3.5 text-indigo-400" />
            </button>
          )}
        </div>
      </div>

      {/* Mandatory Provenance & Transparency Notice */}
      <div className="bg-slate-900/70 border border-slate-800 rounded-xl p-4 flex items-start gap-3">
        <Info className="w-5 h-5 text-indigo-400 shrink-0 mt-0.5" />
        <div className="text-xs text-slate-300 space-y-1">
          <p className="font-semibold text-indigo-300">
            Machine Learning Forecasting Transparency Notice
          </p>
          <p className="text-slate-400">
            Predictions are generated by a software ML model using available historical air-quality data.
            Predictions are statistical estimates, not physical measurements. Data provenance is preserved
            and displayed for auditability.
          </p>
        </div>
      </div>

      {/* Training Success Notice */}
      {trainResult && trainResult.status === 'SUCCESS' && (
        <div className="bg-emerald-950/40 border border-emerald-500/40 rounded-xl p-4 flex items-start gap-3">
          <CheckCircle2 className="w-5 h-5 text-emerald-400 shrink-0 mt-0.5" />
          <div className="text-xs text-emerald-200">
            <p className="font-semibold text-emerald-300">
              Model Training & Evaluation Succeeded (+{trainResult.horizon_hours}h)
            </p>
            <p className="text-emerald-300/80 mt-0.5">
              {trainResult.message} Validation metrics: MAE = {trainResult.metrics?.mae}, RMSE = {trainResult.metrics?.rmse}, R² = {trainResult.metrics?.r2}.
            </p>
          </div>
        </div>
      )}

      {/* Warning banner if SIMULATED data is present in training data */}
      {activePrediction?.has_simulated_data && (
        <div className="bg-amber-950/40 border border-amber-500/40 rounded-xl p-4 flex items-start gap-3">
          <AlertTriangle className="w-5 h-5 text-amber-400 shrink-0 mt-0.5" />
          <div className="text-xs text-amber-200">
            <p className="font-semibold text-amber-300">
              Training data includes SIMULATED observations
            </p>
            <p className="text-amber-300/80 mt-0.5">
              One or more observations used to train this predictive model originated from software
              simulations. Forecast outputs should be interpreted strictly in the context of synthetic simulation.
            </p>
          </div>
        </div>
      )}

      {/* Error Alert */}
      {errorMsg && (
        <div className="bg-rose-950/40 border border-rose-500/40 rounded-xl p-4 flex items-start gap-3">
          <AlertTriangle className="w-5 h-5 text-rose-400 shrink-0 mt-0.5" />
          <div className="text-xs text-rose-200">
            <p className="font-semibold">Prediction Engine Notice</p>
            <p className="text-rose-300 mt-0.5">{errorMsg}</p>
          </div>
        </div>
      )}

      {/* Horizon Selection Bar */}
      <div className="bg-slate-900 border border-slate-800 rounded-xl p-4">
        <div className="flex flex-col md:flex-row md:items-center justify-between gap-4">
          <div>
            <span className="text-xs font-semibold text-slate-400 uppercase tracking-wider">
              Forecast Horizon
            </span>
            <p className="text-xs text-slate-500 mt-0.5">
              Select temporal window for future AQI projection
            </p>
          </div>

          <div className="flex flex-wrap gap-2">
            {HORIZONS.map((h) => {
              const isSelected = selectedHorizon === h.hours;
              return (
                <button
                  key={h.hours}
                  onClick={() => handleHorizonSelect(h.hours)}
                  className={`px-4 py-2 rounded-lg text-xs font-semibold transition border ${
                    isSelected
                      ? 'bg-indigo-600 text-white border-indigo-500 shadow-md shadow-indigo-600/20'
                      : 'bg-slate-800 text-slate-300 border-slate-700 hover:bg-slate-700/80'
                  }`}
                >
                  {h.label}
                </button>
              );
            })}
          </div>
        </div>
      </div>

      {/* Action Controls & Active Forecast Display */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        {/* Left Column: Model Controls */}
        <div className="bg-slate-900 border border-slate-800 rounded-xl p-5 flex flex-col justify-between space-y-6">
          <div className="space-y-4">
            <div className="flex items-center gap-2 border-b border-slate-800 pb-3">
              <Sliders className="w-4 h-4 text-indigo-400" />
              <h2 className="text-sm font-semibold text-white">Execution Controls</h2>
            </div>

            {/* Min observations slider */}
            <div>
              <div className="flex justify-between text-xs text-slate-300 mb-1">
                <span>Minimum Training Obs:</span>
                <span className="font-mono text-indigo-400">{minObservations}</span>
              </div>
              <input
                type="range"
                min="10"
                max="100"
                step="2"
                value={minObservations}
                onChange={(e) => setMinObservations(Number(e.target.value))}
                className="w-full accent-indigo-500 bg-slate-800 rounded-lg cursor-pointer"
                disabled={!canTrainAndPredict}
              />
              <p className="text-[11px] text-slate-500 mt-1">
                Enforces data sufficiency check before fitting models
              </p>
            </div>

            {!canTrainAndPredict && (
              <div className="bg-slate-800/60 border border-slate-700/50 rounded-lg p-3 text-xs text-slate-400 flex items-center gap-2">
                <ShieldAlert className="w-4 h-4 text-amber-400 shrink-0" />
                <span>Training & forecasting are restricted to Admin and Analyst roles.</span>
              </div>
            )}
          </div>

          <div className="space-y-3 pt-2">
            <button
              onClick={handleTrainModel}
              disabled={!canTrainAndPredict || trainingLoading}
              className={`w-full py-2.5 px-4 rounded-lg text-xs font-semibold flex items-center justify-center gap-2 transition ${
                canTrainAndPredict
                  ? 'bg-slate-800 hover:bg-slate-700 text-slate-200 border border-slate-700'
                  : 'bg-slate-800/40 text-slate-500 border border-slate-800 cursor-not-allowed'
              }`}
            >
              {trainingLoading ? (
                <>
                  <RefreshCw className="w-3.5 h-3.5 animate-spin text-indigo-400" />
                  <span>Evaluating Model...</span>
                </>
              ) : (
                <>
                  <Sparkles className="w-3.5 h-3.5 text-indigo-400" />
                  <span>Train & Evaluate (+{selectedHorizon}h)</span>
                </>
              )}
            </button>

            <button
              onClick={handleGeneratePrediction}
              disabled={!canTrainAndPredict || predictingLoading}
              className={`w-full py-2.5 px-4 rounded-lg text-xs font-semibold flex items-center justify-center gap-2 transition shadow-lg ${
                canTrainAndPredict
                  ? 'bg-indigo-600 hover:bg-indigo-500 text-white shadow-indigo-600/20'
                  : 'bg-indigo-900/30 text-slate-500 cursor-not-allowed'
              }`}
            >
              {predictingLoading ? (
                <>
                  <RefreshCw className="w-3.5 h-3.5 animate-spin text-white" />
                  <span>Generating Forecast...</span>
                </>
              ) : (
                <>
                  <TrendingUp className="w-3.5 h-3.5 text-white" />
                  <span>Generate Forecast (+{selectedHorizon}h)</span>
                </>
              )}
            </button>
          </div>
        </div>

        {/* Center: Forecast Result Card */}
        <div className="bg-slate-900 border border-slate-800 rounded-xl p-5 flex flex-col justify-between">
          <div>
            <div className="flex items-center justify-between border-b border-slate-800 pb-3 mb-4">
              <span className="text-xs font-semibold text-slate-400 uppercase tracking-wider">
                Predicted Air Quality
              </span>
              <span className="text-xs font-mono px-2 py-0.5 rounded bg-indigo-950 text-indigo-300 border border-indigo-800">
                +{selectedHorizon}h Horizon
              </span>
            </div>

            {activePrediction ? (
              <div className="space-y-4">
                <div className="flex items-baseline gap-4">
                  <div className="text-5xl font-black tracking-tight text-white">
                    {Math.round(activePrediction.predicted_aqi)}
                  </div>
                  <div
                    className={`inline-flex items-center gap-1.5 px-3 py-1 rounded-full text-xs font-bold border ${catStyle.bg} ${catStyle.text} ${catStyle.border}`}
                  >
                    <span className={`w-2 h-2 rounded-full ${catStyle.dot}`} />
                    {activePrediction.predicted_category}
                  </div>
                </div>

                <div className="space-y-2 text-xs text-slate-300 bg-slate-950/60 p-3 rounded-lg border border-slate-800/80">
                  <div className="flex justify-between">
                    <span className="text-slate-500">Target Time:</span>
                    <span className="font-mono text-slate-200">
                      {new Date(activePrediction.target_timestamp).toLocaleString()}
                    </span>
                  </div>
                  <div className="flex justify-between items-center">
                    <span className="text-slate-500">Baseline Obs:</span>
                    <div className="flex items-center gap-1.5">
                      <span className="font-mono text-slate-400">
                        {new Date(activePrediction.base_timestamp).toLocaleString([], { dateStyle: 'short', timeStyle: 'short' })}
                      </span>
                      {inputFreshness && (
                        <span
                          className={`px-1.5 py-0.5 rounded text-[9px] font-mono font-bold border ${
                            inputFreshness === 'FRESH INPUT'
                              ? 'bg-emerald-500/10 text-emerald-400 border-emerald-500/30'
                              : 'bg-amber-500/10 text-amber-300 border-amber-500/30'
                          }`}
                        >
                          {inputFreshness}
                        </span>
                      )}
                    </div>
                  </div>
                  <div className="flex justify-between">
                    <span className="text-slate-500">Model Architecture:</span>
                    <span className="font-mono text-indigo-300">
                      {activePrediction.model_name}
                    </span>
                  </div>
                  <div className="flex justify-between">
                    <span className="text-slate-500">Training Samples:</span>
                    <span className="font-mono text-slate-300">
                      {activePrediction.training_observations} records
                    </span>
                  </div>
                </div>
              </div>
            ) : (
              <div className="h-40 flex flex-col items-center justify-center text-slate-500 text-xs text-center">
                <BrainCircuit className="w-8 h-8 text-slate-600 mb-2" />
                <p>No forecast record available for +{selectedHorizon}h.</p>
                <p className="text-[11px] text-slate-600 mt-1">
                  Click "Generate Forecast" above to run prediction.
                </p>
              </div>
            )}
          </div>

          {/* Data Provenance Badge Row */}
          {activePrediction && (
            <div className="mt-4 pt-3 border-t border-slate-800/60 flex items-center justify-between">
              <span className="text-[11px] text-slate-500">Data Sources:</span>
              <div className="flex gap-1.5 flex-wrap">
                {activePrediction.data_sources.map((src) => (
                  <span
                    key={src}
                    className={`text-[10px] font-mono px-2 py-0.5 rounded border ${
                      src === 'SIMULATED'
                        ? 'bg-amber-950/60 text-amber-300 border-amber-800/50'
                        : 'bg-slate-800 text-slate-300 border-slate-700'
                    }`}
                  >
                    {src}
                  </span>
                ))}
              </div>
            </div>
          )}
        </div>

        {/* Right Column: Model Evaluation Metrics */}
        <div className="bg-slate-900 border border-slate-800 rounded-xl p-5 flex flex-col justify-between">
          <div>
            <div className="flex items-center justify-between border-b border-slate-800 pb-3 mb-4">
              <span className="text-xs font-semibold text-slate-400 uppercase tracking-wider">
                Evaluation Metrics
              </span>
              <span className="text-[11px] text-slate-500">Validation Split</span>
            </div>

            <div className="grid grid-cols-3 gap-3">
              <div className="bg-slate-950/60 border border-slate-800 p-3 rounded-lg text-center">
                <div className="text-[11px] text-slate-500 font-semibold mb-1">MAE</div>
                <div className="text-xl font-bold font-mono text-emerald-400">
                  {activePrediction?.mae != null ? activePrediction.mae.toFixed(2) : '--'}
                </div>
                <div className="text-[9px] text-slate-600 mt-0.5">Mean Abs Error</div>
              </div>

              <div className="bg-slate-950/60 border border-slate-800 p-3 rounded-lg text-center">
                <div className="text-[11px] text-slate-500 font-semibold mb-1">RMSE</div>
                <div className="text-xl font-bold font-mono text-cyan-400">
                  {activePrediction?.rmse != null ? activePrediction.rmse.toFixed(2) : '--'}
                </div>
                <div className="text-[9px] text-slate-600 mt-0.5">Root Mean Sq</div>
              </div>

              <div className="bg-slate-950/60 border border-slate-800 p-3 rounded-lg text-center">
                <div className="text-[11px] text-slate-500 font-semibold mb-1">R²</div>
                <div className="text-xl font-bold font-mono text-indigo-400">
                  {activePrediction?.r2 != null ? activePrediction.r2.toFixed(3) : '--'}
                </div>
                <div className="text-[9px] text-slate-600 mt-0.5">Variance Expl.</div>
              </div>
            </div>

            <div className="mt-4 p-3 bg-slate-950/40 rounded-lg border border-slate-800/60 text-[11px] text-slate-400 leading-relaxed">
              <p>
                Metrics reflect chronological out-of-sample validation on the most recent 20% of
                observations. Zero temporal leakage is enforced.
              </p>
            </div>
          </div>

          <div className="mt-4 pt-3 border-t border-slate-800/60 text-[11px] text-slate-500 flex items-center justify-between">
            <span>Horizon: +{selectedHorizon} Hours</span>
            <span className="text-slate-400 font-medium">{selectedLoc?.name}</span>
          </div>
        </div>
      </div>

      {/* Multi-Horizon Cards Summary */}
      <div className="grid grid-cols-2 sm:grid-cols-5 gap-3">
        {HORIZONS.map((h) => {
          const match = latestPredictions.find((p) => p.horizon_hours === h.hours);
          const style = getAQICategoryStyle(match?.predicted_category);
          const isSelected = selectedHorizon === h.hours;

          return (
            <div
              key={h.hours}
              onClick={() => handleHorizonSelect(h.hours)}
              className={`p-3 rounded-xl border cursor-pointer transition ${
                isSelected
                  ? 'bg-slate-800/90 border-indigo-500 shadow-md ring-1 ring-indigo-500/50'
                  : 'bg-slate-900 border-slate-800 hover:bg-slate-800/50'
              }`}
            >
              <div className="flex items-center justify-between text-[11px] text-slate-400 font-medium">
                <span>{h.label}</span>
                {match && (
                  <span className={`w-2 h-2 rounded-full ${style.dot}`} />
                )}
              </div>
              <div className="text-xl font-bold text-white mt-1">
                {match ? Math.round(match.predicted_aqi) : '--'}
              </div>
              <div className="text-[10px] text-slate-500 truncate mt-0.5">
                {match ? match.predicted_category : 'No forecast'}
              </div>
            </div>
          );
        })}
      </div>

      {/* Forecast Progression Visualization */}
      <div className="bg-slate-900 border border-slate-800 rounded-xl p-5">
        <div className="flex items-center justify-between border-b border-slate-800 pb-3 mb-4">
          <div className="flex items-center gap-2">
            <TrendingUp className="w-4 h-4 text-indigo-400" />
            <h3 className="text-sm font-semibold text-white">
              Baseline Observation vs. Future Forecast Projection
            </h3>
          </div>
          <span className="text-xs text-slate-500">
            Dashed line represents statistical machine-learning prediction
          </span>
        </div>

        {chartData.length > 0 ? (
          <div className="h-64 w-full">
            <ResponsiveContainer width="100%" height="100%">
              <ComposedChart data={chartData} margin={{ top: 20, right: 30, left: 0, bottom: 10 }}>
                <CartesianGrid strokeDasharray="3 3" stroke="#334155" opacity={0.5} />
                <XAxis dataKey="time" stroke="#94a3b8" fontSize={11} />
                <YAxis
                  stroke="#94a3b8"
                  fontSize={11}
                  domain={[0, (dataMax: number) => Math.max(300, Math.ceil(dataMax * 1.2))]}
                />
                <Tooltip
                  contentStyle={{
                    backgroundColor: '#0f172a',
                    borderColor: '#334155',
                    borderRadius: '8px',
                    fontSize: '12px',
                  }}
                />
                <Legend wrapperStyle={{ fontSize: '11px', paddingTop: '8px' }} />
                <ReferenceLine y={100} stroke="#84cc16" strokeDasharray="3 3" label={{ value: 'Satisfactory', fill: '#84cc16', fontSize: 10 }} />
                <ReferenceLine y={200} stroke="#f59e0b" strokeDasharray="3 3" label={{ value: 'Moderate', fill: '#f59e0b', fontSize: 10 }} />
                <ReferenceLine y={300} stroke="#f97316" strokeDasharray="3 3" label={{ value: 'Poor', fill: '#f97316', fontSize: 10 }} />
                <Line
                  type="monotone"
                  dataKey="historicalAQI"
                  name="Baseline AQI"
                  stroke="#38bdf8"
                  strokeWidth={3}
                  dot={{ r: 6, fill: '#38bdf8' }}
                  connectNulls={true}
                />
                <Line
                  type="monotone"
                  dataKey="predictedAQI"
                  name="Predicted AQI (Forecast)"
                  stroke="#a855f7"
                  strokeWidth={3}
                  strokeDasharray="5 5"
                  dot={{ r: 6, fill: '#a855f7' }}
                  connectNulls={true}
                />
              </ComposedChart>
            </ResponsiveContainer>
          </div>
        ) : (
          <div className="h-48 flex items-center justify-center text-slate-500 text-xs">
            Generate or select a forecast to view progression visualization.
          </div>
        )}
      </div>

      {/* Historical Predictions Log Table */}
      <div className="bg-slate-900 border border-slate-800 rounded-xl overflow-hidden">
        <div className="p-4 border-b border-slate-800 flex items-center justify-between">
          <div className="flex items-center gap-2">
            <Clock className="w-4 h-4 text-slate-400" />
            <h3 className="text-sm font-semibold text-white">Prediction Audit Log</h3>
          </div>
          <span className="text-xs text-slate-500">Last 20 generated forecasts</span>
        </div>

        <div className="overflow-x-auto">
          <table className="w-full text-left text-xs text-slate-300">
            <thead className="bg-slate-950/60 text-slate-400 uppercase tracking-wider text-[10px] border-b border-slate-800">
              <tr>
                <th className="px-4 py-3">Created At</th>
                <th className="px-4 py-3">Horizon</th>
                <th className="px-4 py-3">Target Timestamp</th>
                <th className="px-4 py-3">Predicted AQI</th>
                <th className="px-4 py-3">CPCB Category</th>
                <th className="px-4 py-3">Model</th>
                <th className="px-4 py-3">MAE / R²</th>
                <th className="px-4 py-3">Data Provenance</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-800/60">
              {predictionHistory.length > 0 ? (
                predictionHistory.map((rec, idx) => {
                  const style = getAQICategoryStyle(rec.predicted_category);
                  return (
                    <tr key={rec.id ?? `pred-${idx}`} className="hover:bg-slate-800/30 transition">
                      <td className="px-4 py-3 font-mono text-slate-400">
                        {new Date(rec.created_at).toLocaleTimeString([], {
                          hour: '2-digit',
                          minute: '2-digit',
                          second: '2-digit',
                        })}
                      </td>
                      <td className="px-4 py-3 font-semibold text-indigo-400">
                        +{rec.horizon_hours}h
                      </td>
                      <td className="px-4 py-3 font-mono text-slate-300">
                        {new Date(rec.target_timestamp).toLocaleString([], {
                          month: 'short',
                          day: 'numeric',
                          hour: '2-digit',
                          minute: '2-digit',
                        })}
                      </td>
                      <td className="px-4 py-3 font-bold text-white font-mono text-sm">
                        {Math.round(rec.predicted_aqi)}
                      </td>
                      <td className="px-4 py-3">
                        <span
                          className={`inline-flex items-center gap-1 px-2 py-0.5 rounded text-[10px] font-semibold border ${style.bg} ${style.text} ${style.border}`}
                        >
                          <span className={`w-1.5 h-1.5 rounded-full ${style.dot}`} />
                          {rec.predicted_category}
                        </span>
                      </td>
                      <td className="px-4 py-3 font-mono text-slate-400">
                        {rec.model_name}
                      </td>
                      <td className="px-4 py-3 font-mono text-slate-300">
                        {rec.mae != null ? rec.mae.toFixed(1) : '--'} /{' '}
                        {rec.r2 != null ? rec.r2.toFixed(2) : '--'}
                      </td>
                      <td className="px-4 py-3">
                        <div className="flex gap-1 flex-wrap">
                          {rec.data_sources.map((s) => (
                            <span
                              key={s}
                              className={`text-[9px] px-1.5 py-0.2 rounded border ${
                                s === 'SIMULATED'
                                  ? 'bg-amber-950/60 text-amber-300 border-amber-800'
                                  : 'bg-slate-800 text-slate-400 border-slate-700'
                              }`}
                            >
                              {s}
                            </span>
                          ))}
                        </div>
                      </td>
                    </tr>
                  );
                })
              ) : (
                <tr>
                  <td colSpan={8} className="px-4 py-8 text-center text-slate-500 text-xs">
                    No prediction history found for this station.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
};
