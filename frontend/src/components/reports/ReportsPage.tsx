import React, { useState, useEffect, useCallback } from 'react';
import type { User } from '../../types/auth';
import type { Location } from '../../types/air_quality';
import type { ReportType, ReportPreviewResponse } from '../../types/report';
import type { WhatIfSimulationRequest } from '../../types/whatIf';
import { getLocations } from '../../services/air_quality';
import { previewReport, downloadReportPdf } from '../../services/report';
import { getAQICategoryStyle } from '../../utils/aqiFormatters';
import {
  FileText,
  Download,
  Eye,
  RefreshCw,
  MapPin,
  Calendar,
  Sliders,
  Sparkles,
  AlertTriangle,
  GitCompare,
  TrendingUp,
  TrendingDown,
  Minus,
  CheckCircle2,
  ShieldAlert,
  Activity,
} from 'lucide-react';

interface ReportsPageProps {
  currentUser: User;
  onNavigateToTab?: (tabId: string) => void;
  onNavigateToDashboard?: (locationId: number) => void;
  initialReportType?: ReportType;
  initialLocationId?: number | null;
  initialWhatIfRequest?: WhatIfSimulationRequest | null;
}

const REPORT_TYPES: Array<{
  type: ReportType;
  title: string;
  badge: string;
  description: string;
  icon: React.ElementType;
}> = [
  {
    type: 'LOCATION_SUMMARY',
    title: 'Location Summary Report',
    badge: 'Station Focused',
    description:
      'Detailed single-station environmental assessment including latest CPCB AQI, pollutant distribution, anomalies, alerts, forecasts, and preventive actions.',
    icon: MapPin,
  },
  {
    type: 'PERIOD_REPORT',
    title: 'Environmental Period Report',
    badge: 'Aggregated Analysis',
    description:
      'Multi-day temporal trend performance (24h, 48h, 7d, 30d), category distribution frequencies, sustained pollution episodes, and temporal statistics.',
    icon: Calendar,
  },
  {
    type: 'COMPARISON_REPORT',
    title: 'Location Comparison Report',
    badge: 'Cross-Station',
    description:
      'Factual multi-station comparative analysis across selected monitoring stations with statistical variances and zero subjective rankings.',
    icon: GitCompare,
  },
  {
    type: 'WHAT_IF_REPORT',
    title: 'What-If Scenario Report',
    badge: 'Hypothetical Impact',
    description:
      'Official documentation of hypothetical pollutant variations (+/- %), recalculated AQI deltas, category transitions, and simulated preventive actions.',
    icon: Sliders,
  },
];

export const ReportsPage: React.FC<ReportsPageProps> = ({
  currentUser,
  onNavigateToTab,
  onNavigateToDashboard,
  initialReportType = 'LOCATION_SUMMARY',
  initialLocationId = null,
  initialWhatIfRequest = null,
}) => {
  const [locations, setLocations] = useState<Location[]>([]);
  const [selectedLocationId, setSelectedLocationId] = useState<number | null>(
    initialLocationId || null
  );
  const [selectedReportType, setSelectedReportType] = useState<ReportType>(initialReportType);
  const [periodPreset, setPeriodPreset] = useState<string>('24h');
  const [comparisonIds, setComparisonIds] = useState<number[]>([]);

  // What-If parameters if WHAT_IF_REPORT is chosen
  const [whatIfChanges, setWhatIfChanges] = useState<Record<string, number>>(
    initialWhatIfRequest?.pollutant_changes || { pm25: -25, no2: -15 }
  );

  const [previewData, setPreviewData] = useState<ReportPreviewResponse | null>(null);
  const [loadingPreview, setLoadingPreview] = useState<boolean>(false);
  const [downloadingPdf, setDownloadingPdf] = useState<boolean>(false);
  const [errorMsg, setErrorMsg] = useState<string | null>(null);
  const [downloadSuccess, setDownloadSuccess] = useState<string | null>(null);

  // Fetch locations
  useEffect(() => {
    let ignore = false;
    const fetchLocs = async () => {
      try {
        const locList = await getLocations();
        if (!ignore) {
          setLocations(locList);
          setSelectedLocationId((prev) => prev ?? (locList.length > 0 ? locList[0].id : null));
          setComparisonIds((prev) => (prev.length === 0 && locList.length > 1 ? [locList[1].id] : prev));
        }
      } catch {
        if (!ignore) {
          setErrorMsg('Failed to fetch monitoring locations.');
        }
      }
    };
    Promise.resolve().then(fetchLocs);
    return () => {
      ignore = true;
    };
  }, []);

  // Request payload builder
  const buildRequestPayload = useCallback(() => {
    if (!selectedLocationId) return null;
    return {
      report_type: selectedReportType,
      location_id: selectedLocationId,
      period_preset: periodPreset,
      comparison_location_ids:
        selectedReportType === 'COMPARISON_REPORT' ? comparisonIds : null,
      what_if_request:
        selectedReportType === 'WHAT_IF_REPORT'
          ? {
              location_id: selectedLocationId,
              pollutant_changes: whatIfChanges,
            }
          : null,
    };
  }, [selectedReportType, selectedLocationId, periodPreset, comparisonIds, whatIfChanges]);

  // Load preview
  const handleFetchPreview = useCallback(async () => {
    const payload = buildRequestPayload();
    if (!payload) return;

    try {
      setLoadingPreview(true);
      setErrorMsg(null);
      setDownloadSuccess(null);
      const data = await previewReport(payload);
      setPreviewData(data);
    } catch (err: unknown) {
      const errorObj = err as { response?: { data?: { detail?: string } }; message?: string };
      setErrorMsg(
        errorObj?.response?.data?.detail ||
          errorObj?.message ||
          'Failed to compile report preview. Please check parameters.'
      );
    } finally {
      setLoadingPreview(false);
    }
  }, [buildRequestPayload]);

  // Trigger preview when primary parameters change
  useEffect(() => {
    let ignore = false;
    if (selectedLocationId) {
      Promise.resolve().then(() => {
        if (!ignore) {
          handleFetchPreview();
        }
      });
    }
    return () => {
      ignore = true;
    };
  }, [selectedLocationId, selectedReportType, periodPreset, handleFetchPreview]);

  // Download PDF handler
  const handleDownloadPdf = async () => {
    const payload = buildRequestPayload();
    if (!payload) return;

    try {
      setDownloadingPdf(true);
      setErrorMsg(null);
      setDownloadSuccess(null);
      await downloadReportPdf(payload);
      setDownloadSuccess('PDF generated and downloaded successfully.');
    } catch (err: any) {
      setErrorMsg(
        err?.response?.data?.detail ||
          err?.message ||
          'Failed to generate PDF document. Please try again.'
      );
    } finally {
      setDownloadingPdf(false);
    }
  };

  const handleToggleComparisonLocation = (locId: number) => {
    setComparisonIds((prev) =>
      prev.includes(locId) ? prev.filter((id) => id !== locId) : [...prev, locId]
    );
  };

  const handleAdjustModifier = (pollutant: string, delta: number) => {
    setWhatIfChanges((prev) => ({
      ...prev,
      [pollutant]: Math.min(100, Math.max(-100, (prev[pollutant] || 0) + delta)),
    }));
  };

  const selectedLoc = locations.find((l) => l.id === selectedLocationId);

  return (
    <div className="space-y-6">
      {/* Header Banner */}
      <div className="flex flex-col md:flex-row md:items-center justify-between gap-4">
        <div>
          <div className="flex items-center gap-2.5">
            <div className="p-2 rounded-xl bg-teal-500/20 text-teal-400 border border-teal-500/30">
              <FileText className="w-6 h-6" />
            </div>
            <div>
              <div className="flex items-center gap-2">
                <h1 className="text-xl font-black tracking-tight text-white">
                  Automated Environmental & Air-Quality Report Generator
                </h1>
                <span className="px-2.5 py-0.5 rounded-full text-[10px] font-bold tracking-wide uppercase bg-teal-500/10 text-teal-400 border border-teal-500/20">
                  Phase 13
                </span>
                <span className="px-2 py-0.5 rounded-full text-[10px] font-mono uppercase bg-slate-800 text-slate-300 border border-slate-700">
                  {currentUser.role}
                </span>
              </div>
              <p className="text-xs text-slate-400 mt-0.5">
                Statelessly transform air-quality observations, CPCB NAQI analytics, ML forecasts, active alerts, and What-If scenarios into publication-grade PDF documents.
                {selectedLoc && (
                  <span className="ml-1 text-teal-300 font-medium">
                    (Station: {selectedLoc.name}, {selectedLoc.city})
                  </span>
                )}
              </p>
            </div>
          </div>
        </div>

        {/* Global Action Buttons */}
        <div className="flex items-center gap-2.5 self-start md:self-auto">
          {onNavigateToTab && (
            <button
              onClick={() => onNavigateToTab('whatif')}
              className="px-3 py-2 rounded-xl bg-slate-800 hover:bg-slate-700 text-teal-300 text-xs font-semibold border border-slate-700 transition flex items-center gap-1.5"
            >
              <Sliders className="w-3.5 h-3.5" />
              <span>What-If Lab</span>
            </button>
          )}
          {onNavigateToDashboard && selectedLocationId && (
            <button
              onClick={() => onNavigateToDashboard(selectedLocationId)}
              className="px-3 py-2 rounded-xl bg-slate-800 hover:bg-slate-700 text-slate-300 text-xs font-semibold border border-slate-700 transition"
            >
              Dashboard
            </button>
          )}
        </div>
      </div>

      {/* Mandatory Advisory Banner */}
      <div className="p-3.5 rounded-xl bg-amber-500/5 border border-amber-500/20 flex items-start gap-3 text-xs text-amber-200/90 shadow-sm">
        <ShieldAlert className="w-4 h-4 text-amber-400 shrink-0 mt-0.5" />
        <div className="space-y-0.5">
          <span className="font-bold text-amber-300">Official Report Advisory: </span>
          <span>
            Generated reports reflect software analytics based on authorized monitoring-station telemetry. All calculations strictly adhere to the Indian CPCB NAQI standard. Reports are intended for informational, regulatory transparency, and environmental awareness purposes, and DO NOT constitute medical advice.
          </span>
        </div>
      </div>

      {/* Feedback Alerts */}
      {errorMsg && (
        <div className="p-4 rounded-xl bg-rose-500/10 border border-rose-500/30 text-rose-300 text-xs flex items-start gap-3">
          <AlertTriangle className="w-4 h-4 text-rose-400 shrink-0 mt-0.5" />
          <div>
            <p className="font-semibold text-rose-200">Report Compilation Notice</p>
            <p className="mt-0.5 text-rose-300/90">{errorMsg}</p>
          </div>
        </div>
      )}

      {downloadSuccess && (
        <div className="p-3.5 rounded-xl bg-emerald-500/10 border border-emerald-500/30 text-emerald-300 text-xs flex items-center gap-3">
          <CheckCircle2 className="w-4 h-4 text-emerald-400 shrink-0" />
          <span>{downloadSuccess}</span>
        </div>
      )}

      {/* Configuration Strip: Step 1 & Step 2 */}
      <div className="p-5 rounded-2xl bg-slate-900/60 border border-slate-800 space-y-4 shadow-xl">
        <div className="text-xs font-bold uppercase tracking-wider text-slate-400 flex items-center gap-2">
          <span className="w-5 h-5 rounded-full bg-teal-500/20 text-teal-400 flex items-center justify-center text-[11px]">
            1
          </span>
          <span>Select Report Architecture & Parameters</span>
        </div>

        {/* Report Types Grid */}
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-3">
          {REPORT_TYPES.map((rt) => {
            const Icon = rt.icon;
            const isSelected = selectedReportType === rt.type;
            return (
              <button
                key={rt.type}
                onClick={() => setSelectedReportType(rt.type)}
                className={`text-left p-4 rounded-xl border transition-all relative overflow-hidden flex flex-col justify-between ${
                  isSelected
                    ? 'bg-teal-950/30 border-teal-500 shadow-md ring-1 ring-teal-500/30'
                    : 'bg-slate-950/40 border-slate-800 hover:border-slate-700 hover:bg-slate-900/50 text-slate-300'
                }`}
              >
                <div className="space-y-2">
                  <div className="flex items-center justify-between">
                    <div
                      className={`p-2 rounded-lg ${
                        isSelected
                          ? 'bg-teal-500/20 text-teal-300'
                          : 'bg-slate-800 text-slate-400'
                      }`}
                    >
                      <Icon className="w-4 h-4" />
                    </div>
                    <span
                      className={`text-[9px] font-bold uppercase px-2 py-0.5 rounded-full border ${
                        isSelected
                          ? 'bg-teal-500/20 text-teal-300 border-teal-500/30'
                          : 'bg-slate-800 text-slate-400 border-slate-700'
                      }`}
                    >
                      {rt.badge}
                    </span>
                  </div>
                  <div>
                    <h3
                      className={`text-xs font-bold ${
                        isSelected ? 'text-white' : 'text-slate-200'
                      }`}
                    >
                      {rt.title}
                    </h3>
                    <p className="text-[11px] text-slate-400 mt-1 line-clamp-3">
                      {rt.description}
                    </p>
                  </div>
                </div>
              </button>
            );
          })}
        </div>

        {/* Secondary Parameters: Station Picker & Period Preset */}
        <div className="pt-2 border-t border-slate-800/80 grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
          {/* Primary Station Dropdown */}
          <div className="space-y-1.5">
            <label className="text-xs font-semibold text-slate-300 flex items-center gap-1.5">
              <MapPin className="w-3.5 h-3.5 text-teal-400" />
              <span>Primary Monitoring Station</span>
            </label>
            <select
              value={selectedLocationId || ''}
              onChange={(e) => setSelectedLocationId(Number(e.target.value))}
              className="w-full bg-slate-950 border border-slate-700 text-slate-200 text-xs rounded-xl px-3 py-2.5 focus:outline-none focus:border-teal-500 shadow-inner font-medium"
            >
              {locations.map((loc) => (
                <option key={loc.id} value={loc.id}>
                  {loc.name} ({loc.city}, {loc.state})
                </option>
              ))}
            </select>
          </div>

          {/* Period Presets */}
          <div className="space-y-1.5">
            <label className="text-xs font-semibold text-slate-300 flex items-center gap-1.5">
              <Calendar className="w-3.5 h-3.5 text-teal-400" />
              <span>Reporting Analysis Window</span>
            </label>
            <div className="grid grid-cols-4 gap-1.5">
              {['24h', '48h', '7d', '30d'].map((preset) => (
                <button
                  key={preset}
                  onClick={() => setPeriodPreset(preset)}
                  className={`py-2 text-xs font-semibold rounded-lg border transition ${
                    periodPreset === preset
                      ? 'bg-teal-500/20 text-teal-300 border-teal-500/40'
                      : 'bg-slate-950 border-slate-800 text-slate-400 hover:text-slate-200'
                  }`}
                >
                  {preset.toUpperCase()}
                </button>
              ))}
            </div>
          </div>

          {/* Generation Trigger Actions */}
          <div className="space-y-1.5 sm:col-span-2 lg:col-span-1 flex flex-col justify-end">
            <div className="flex items-center gap-2">
              <button
                onClick={handleFetchPreview}
                disabled={loadingPreview}
                className="flex-1 inline-flex items-center justify-center gap-1.5 px-3 py-2.5 rounded-xl bg-slate-800 hover:bg-slate-700 text-slate-200 text-xs font-semibold border border-slate-700 transition disabled:opacity-50"
              >
                <RefreshCw className={`w-3.5 h-3.5 ${loadingPreview ? 'animate-spin' : ''}`} />
                <span>Refresh Preview</span>
              </button>

              <button
                onClick={handleDownloadPdf}
                disabled={downloadingPdf || loadingPreview}
                className="flex-1 inline-flex items-center justify-center gap-1.5 px-4 py-2.5 rounded-xl bg-gradient-to-r from-teal-500 to-emerald-600 hover:from-teal-400 hover:to-emerald-500 text-slate-950 text-xs font-bold shadow-lg transition disabled:opacity-50"
              >
                {downloadingPdf ? (
                  <>
                    <RefreshCw className="w-3.5 h-3.5 animate-spin" />
                    <span>Building PDF...</span>
                  </>
                ) : (
                  <>
                    <Download className="w-3.5 h-3.5" />
                    <span>Download PDF</span>
                  </>
                )}
              </button>
            </div>
          </div>
        </div>

        {/* COMPARISON_REPORT Extra Station Selectors */}
        {selectedReportType === 'COMPARISON_REPORT' && (
          <div className="p-3.5 rounded-xl bg-slate-950/60 border border-slate-800 space-y-2">
            <div className="text-[11px] font-bold text-slate-300 uppercase tracking-wider flex items-center gap-1.5">
              <GitCompare className="w-3.5 h-3.5 text-teal-400" />
              <span>Select Comparison Stations (Include 1 or more)</span>
            </div>
            <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-2 pt-1">
              {locations
                .filter((l) => l.id !== selectedLocationId)
                .map((loc) => {
                  const isChecked = comparisonIds.includes(loc.id);
                  return (
                    <label
                      key={loc.id}
                      className={`flex items-center gap-2 p-2 rounded-lg border text-xs cursor-pointer transition ${
                        isChecked
                          ? 'bg-teal-950/30 border-teal-500/40 text-teal-200'
                          : 'bg-slate-900/40 border-slate-800 text-slate-400 hover:text-slate-200'
                      }`}
                    >
                      <input
                        type="checkbox"
                        checked={isChecked}
                        onChange={() => handleToggleComparisonLocation(loc.id)}
                        className="rounded border-slate-700 text-teal-500 focus:ring-0"
                      />
                      <span className="font-medium truncate">
                        {loc.name} ({loc.city})
                      </span>
                    </label>
                  );
                })}
            </div>
          </div>
        )}

        {/* WHAT_IF_REPORT Modifier Preview Summary */}
        {selectedReportType === 'WHAT_IF_REPORT' && (
          <div className="p-3.5 rounded-xl bg-slate-950/60 border border-teal-500/30 space-y-2">
            <div className="flex items-center justify-between">
              <div className="text-[11px] font-bold text-teal-300 uppercase tracking-wider flex items-center gap-1.5">
                <Sliders className="w-3.5 h-3.5 text-teal-400" />
                <span>What-If Scenario Configuration</span>
              </div>
              <span className="text-[10px] font-mono text-amber-400 uppercase bg-amber-500/10 px-2 py-0.5 rounded border border-amber-500/20">
                WHAT_IF / SIMULATED
              </span>
            </div>
            <p className="text-xs text-slate-400">
              Hypothetical adjustments applied to baseline observation:
            </p>
            <div className="flex flex-wrap gap-2 pt-1">
              {Object.entries(whatIfChanges).map(([k, v]) => (
                <div
                  key={k}
                  className={`px-2.5 py-1 rounded-lg border text-xs font-mono font-bold flex items-center gap-2 ${
                    v < 0
                      ? 'bg-emerald-500/10 border-emerald-500/30 text-emerald-400'
                      : v > 0
                      ? 'bg-rose-500/10 border-rose-500/30 text-rose-400'
                      : 'bg-slate-800 border-slate-700 text-slate-300'
                  }`}
                >
                  <span className="uppercase">{k}:</span>
                  <div className="flex items-center gap-1">
                    <button
                      type="button"
                      onClick={() => handleAdjustModifier(k, -10)}
                      className="w-4 h-4 rounded bg-slate-900/80 hover:bg-slate-900 text-slate-300 flex items-center justify-center font-bold text-[10px]"
                      title="Decrease by 10%"
                    >
                      -
                    </button>
                    <span>{v > 0 ? `+${v}` : v}%</span>
                    <button
                      type="button"
                      onClick={() => handleAdjustModifier(k, 10)}
                      className="w-4 h-4 rounded bg-slate-900/80 hover:bg-slate-900 text-slate-300 flex items-center justify-center font-bold text-[10px]"
                      title="Increase by 10%"
                    >
                      +
                    </button>
                  </div>
                </div>
              ))}
            </div>
          </div>
        )}
      </div>

      {/* Report Summary Live Preview Panel */}
      <div className="space-y-4">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <Eye className="w-4 h-4 text-teal-400" />
            <h2 className="text-sm font-bold uppercase tracking-wider text-slate-200">
              Live Document Preview
            </h2>
          </div>
          {previewData && (
            <span className="text-xs text-slate-400 font-mono">
              Compiled at {previewData.generated_at}
            </span>
          )}
        </div>

        {loadingPreview ? (
          <div className="p-12 rounded-2xl bg-slate-900/40 border border-slate-800 text-center space-y-3">
            <RefreshCw className="w-6 h-6 animate-spin text-teal-400 mx-auto" />
            <p className="text-xs text-slate-400">
              Aggregating CPCB telemetry, trends, anomalies, and recommendations...
            </p>
          </div>
        ) : previewData ? (
          <div className="p-6 rounded-2xl bg-slate-900/70 border border-slate-800 space-y-6 shadow-2xl relative overflow-hidden">
            {/* Document Header Box */}
            <div className="flex flex-col md:flex-row md:items-center justify-between gap-4 pb-5 border-b border-slate-800">
              <div className="space-y-1">
                <div className="inline-flex items-center gap-2 px-2 py-0.5 rounded-full bg-teal-500/10 text-teal-400 border border-teal-500/20 text-[10px] font-bold uppercase">
                  <span>AeroPulse AI</span>
                  <span>•</span>
                  <span>{previewData.report_type}</span>
                </div>
                <h3 className="text-lg font-black text-white">{previewData.report_title}</h3>
                <p className="text-xs text-slate-400">
                  {previewData.location_name} • {previewData.city}, {previewData.state},{' '}
                  {previewData.country} ({previewData.reporting_period})
                </p>
              </div>

              {/* Provenance Tags */}
              <div className="flex flex-col gap-1 text-[10px] font-mono self-start md:self-auto">
                <div className="flex items-center gap-1.5 text-slate-400">
                  <span>Observed:</span>
                  <span className="px-2 py-0.5 rounded bg-slate-800 text-slate-200 border border-slate-700 font-bold">
                    {previewData.provenance_summary.observed_provenance}
                  </span>
                </div>
                <div className="flex items-center gap-1.5 text-slate-400">
                  <span>Forecast:</span>
                  <span className="px-2 py-0.5 rounded bg-indigo-500/10 text-indigo-300 border border-indigo-500/20 font-bold">
                    {previewData.provenance_summary.forecast_provenance}
                  </span>
                </div>
                {previewData.report_type === 'WHAT_IF_REPORT' && (
                  <div className="flex items-center gap-1.5 text-amber-400">
                    <span>Scenario:</span>
                    <span className="px-2 py-0.5 rounded bg-amber-500/10 text-amber-300 border border-amber-500/30 font-bold">
                      WHAT_IF / SIMULATED
                    </span>
                  </div>
                )}
              </div>
            </div>

            {/* Executive Summary Callout */}
            <div className="p-4 rounded-xl bg-slate-950/60 border-l-4 border-l-teal-500 border-slate-800 space-y-1.5 shadow-inner">
              <span className="text-[10px] font-bold uppercase tracking-wider text-teal-300">
                Executive Environmental Summary
              </span>
              <p className="text-xs text-slate-300 leading-relaxed">
                {previewData.executive_summary}
              </p>
            </div>

            {/* Primary Metrics Grid */}
            <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
              {/* Latest AQI */}
              <div className="p-4 rounded-xl bg-slate-950/50 border border-slate-800 text-center space-y-1">
                <span className="text-[10px] font-bold uppercase tracking-wider text-slate-400">
                  Latest AQI
                </span>
                <div className="text-2xl font-black text-white">
                  {previewData.latest_aqi ?? 'N/A'}
                </div>
                {previewData.latest_category && (
                  <span
                    className={`inline-block px-2 py-0.5 rounded text-[10px] font-bold border ${
                      getAQICategoryStyle(previewData.latest_category).bg
                    } ${getAQICategoryStyle(previewData.latest_category).text} ${
                      getAQICategoryStyle(previewData.latest_category).border
                    }`}
                  >
                    {previewData.latest_category}
                  </span>
                )}
              </div>

              {/* Dominant Pollutant */}
              <div className="p-4 rounded-xl bg-slate-950/50 border border-slate-800 text-center space-y-1">
                <span className="text-[10px] font-bold uppercase tracking-wider text-slate-400">
                  Dominant Pollutant
                </span>
                <div className="text-2xl font-black text-teal-300">
                  {previewData.dominant_pollutant || 'N/A'}
                </div>
                <span className="text-[10px] text-slate-400">Primary Sub-Index</span>
              </div>

              {/* Mean AQI */}
              <div className="p-4 rounded-xl bg-slate-950/50 border border-slate-800 text-center space-y-1">
                <span className="text-[10px] font-bold uppercase tracking-wider text-slate-400">
                  Period Mean AQI
                </span>
                <div className="text-2xl font-black text-white">
                  {previewData.aqi_statistics?.mean ?? 'N/A'}
                </div>
                <span className="text-[10px] text-slate-400 font-mono">
                  Min: {previewData.aqi_statistics?.minimum ?? '-'} | Max:{' '}
                  {previewData.aqi_statistics?.maximum ?? '-'}
                </span>
              </div>

              {/* Trend Direction */}
              <div className="p-4 rounded-xl bg-slate-950/50 border border-slate-800 text-center space-y-1">
                <span className="text-[10px] font-bold uppercase tracking-wider text-slate-400">
                  Trend Trajectory
                </span>
                <div className="flex items-center justify-center gap-1.5 pt-1">
                  {previewData.trend_direction === 'INCREASING' ? (
                    <TrendingUp className="w-5 h-5 text-rose-400" />
                  ) : previewData.trend_direction === 'DECREASING' ? (
                    <TrendingDown className="w-5 h-5 text-emerald-400" />
                  ) : (
                    <Minus className="w-5 h-5 text-slate-400" />
                  )}
                  <span
                    className={`text-sm font-bold ${
                      previewData.trend_direction === 'INCREASING'
                        ? 'text-rose-400'
                        : previewData.trend_direction === 'DECREASING'
                        ? 'text-emerald-400'
                        : 'text-slate-300'
                    }`}
                  >
                    {previewData.trend_direction}
                  </span>
                </div>
                <span className="text-[10px] text-slate-400">Hysteresis Evaluation</span>
              </div>
            </div>

            {/* Pollutant Summary Table */}
            <div className="space-y-2">
              <span className="text-xs font-bold uppercase tracking-wider text-slate-300 flex items-center gap-1.5">
                <Activity className="w-3.5 h-3.5 text-teal-400" />
                <span>Multi-Pollutant Statistics & Monitoring Status</span>
              </span>
              <div className="overflow-x-auto rounded-xl border border-slate-800">
                <table className="w-full text-left text-xs">
                  <thead className="bg-slate-950/80 text-slate-400 border-b border-slate-800 text-[10px] uppercase font-bold">
                    <tr>
                      <th className="p-3">Pollutant</th>
                      <th className="p-3">Unit</th>
                      <th className="p-3">Min</th>
                      <th className="p-3">Mean</th>
                      <th className="p-3">Max</th>
                      <th className="p-3">Latest</th>
                      <th className="p-3">Status</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-slate-800/60 font-mono">
                    {Object.entries(previewData.pollutant_summary || {}).map(([key, p]) => (
                      <tr key={key} className="hover:bg-slate-800/30 transition">
                        <td className="p-3 font-bold text-slate-200">{p.label}</td>
                        <td className="p-3 text-slate-400">{p.unit}</td>
                        {p.available ? (
                          <>
                            <td className="p-3 text-slate-300">{p.statistics.minimum ?? '-'}</td>
                            <td className="p-3 font-bold text-white">
                              {p.statistics.mean ?? '-'}
                            </td>
                            <td className="p-3 text-slate-300">{p.statistics.maximum ?? '-'}</td>
                            <td className="p-3 text-teal-300">{p.latest ?? '-'}</td>
                            <td className="p-3">
                              <span className="px-2 py-0.5 rounded text-[10px] font-sans font-bold bg-emerald-500/10 text-emerald-400 border border-emerald-500/20">
                                Monitored
                              </span>
                            </td>
                          </>
                        ) : (
                          <td colSpan={5} className="p-3 text-slate-500 italic text-[11px]">
                            {p.message}
                          </td>
                        )}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>

            {/* Findings & Events Counters */}
            <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
              <div className="p-3.5 rounded-xl bg-slate-950/40 border border-slate-800 flex items-center justify-between">
                <div>
                  <span className="text-[10px] text-slate-400 uppercase font-bold">
                    Statistical Anomalies
                  </span>
                  <div className="text-xl font-bold text-white">
                    {previewData.anomalies_count}
                  </div>
                </div>
                <span className="text-xs text-slate-400">Z-Score ≥ 2.5</span>
              </div>

              <div className="p-3.5 rounded-xl bg-slate-950/40 border border-slate-800 flex items-center justify-between">
                <div>
                  <span className="text-[10px] text-slate-400 uppercase font-bold">
                    Sustained Episodes
                  </span>
                  <div className="text-xl font-bold text-white">
                    {previewData.events_count}
                  </div>
                </div>
                <span className="text-xs text-slate-400">AQI ≥ 201 (≥2h)</span>
              </div>

              <div className="p-3.5 rounded-xl bg-slate-950/40 border border-slate-800 flex items-center justify-between">
                <div>
                  <span className="text-[10px] text-slate-400 uppercase font-bold">
                    Automated Alerts
                  </span>
                  <div className="text-xl font-bold text-white">{previewData.alerts_count}</div>
                </div>
                <span className="text-xs text-slate-400">Logged Alerts</span>
              </div>
            </div>

            {/* Forecast Section (If Available) */}
            {previewData.forecast_available && previewData.forecast_summary && (
              <div className="p-4 rounded-xl bg-indigo-950/20 border border-indigo-500/30 space-y-1.5 shadow-inner">
                <div className="flex items-center justify-between">
                  <span className="text-[10px] font-bold text-indigo-300 uppercase tracking-wider">
                    Machine Learning Forecast
                  </span>
                  <span className="text-[9px] font-bold uppercase bg-rose-500/20 text-rose-300 px-2 py-0.5 rounded border border-rose-500/30">
                    FORECAST — NOT CURRENT OBSERVATION
                  </span>
                </div>
                <p className="text-xs text-slate-300">
                  Model <b>{previewData.forecast_summary.model_name}</b> predicts AQI of{' '}
                  <b>{previewData.forecast_summary.predicted_aqi}</b> (
                  {previewData.forecast_summary.predicted_category}) for horizon +
                  {previewData.forecast_summary.horizon_hours}h. (Model R²:{' '}
                  {previewData.forecast_summary.r2 ?? 'N/A'})
                </p>
              </div>
            )}

            {/* Top Preventive Recommendations */}
            {previewData.top_recommendations?.length > 0 && (
              <div className="space-y-2">
                <span className="text-xs font-bold uppercase tracking-wider text-slate-300 flex items-center gap-1.5">
                  <Sparkles className="w-3.5 h-3.5 text-teal-400" />
                  <span>Prioritized Preventive Guidance (Phase 11)</span>
                </span>
                <div className="grid grid-cols-1 md:grid-cols-2 gap-2.5">
                  {previewData.top_recommendations.slice(0, 4).map((rec, i) => (
                    <div
                      key={i}
                      className="p-3 rounded-xl bg-slate-950/60 border border-slate-800 space-y-1"
                    >
                      <div className="flex items-center justify-between">
                        <span className="text-[10px] font-bold uppercase text-slate-400 font-mono">
                          {rec.type.replace('_', ' ')}
                        </span>
                        <span
                          className={`text-[9px] font-bold uppercase px-2 py-0.5 rounded-full ${
                            rec.priority === 'CRITICAL'
                              ? 'bg-rose-500/20 text-rose-300 border border-rose-500/30'
                              : rec.priority === 'HIGH'
                              ? 'bg-orange-500/20 text-orange-300 border border-orange-500/30'
                              : 'bg-teal-500/20 text-teal-300 border border-teal-500/30'
                          }`}
                        >
                          {rec.priority}
                        </span>
                      </div>
                      <p className="text-xs font-semibold text-slate-200">{rec.action}</p>
                      <p className="text-[11px] text-slate-400 leading-tight">{rec.reason}</p>
                    </div>
                  ))}
                </div>
              </div>
            )}

            {/* PDF Generation Bottom Bar */}
            <div className="pt-4 border-t border-slate-800 flex flex-col sm:flex-row items-center justify-between gap-3">
              <span className="text-xs text-slate-400">
                Ready to compile publication-grade PDF documentation with full appendices.
              </span>
              <button
                onClick={handleDownloadPdf}
                disabled={downloadingPdf}
                className="inline-flex items-center gap-2 px-6 py-2.5 rounded-xl bg-gradient-to-r from-teal-500 to-emerald-600 hover:from-teal-400 hover:to-emerald-500 text-slate-950 text-xs font-bold shadow-lg transition disabled:opacity-50"
              >
                {downloadingPdf ? (
                  <>
                    <RefreshCw className="w-4 h-4 animate-spin" />
                    <span>Compiling PDF Document...</span>
                  </>
                ) : (
                  <>
                    <Download className="w-4 h-4" />
                    <span>Download Official PDF Report</span>
                  </>
                )}
              </button>
            </div>
          </div>
        ) : null}
      </div>
    </div>
  );
};
