import React from 'react';
import type { StationTrustResponse } from '../../types/trust';
import { FreshnessBadge } from '../common/FreshnessBadge';
import { ProvenanceBadge } from '../common/ProvenanceBadge';
import {
  ShieldCheck,
  AlertTriangle,
  Sparkles,
  RefreshCw,
  Cpu,
  Layers,
  Info,
} from 'lucide-react';

interface SystemTrustPanelProps {
  trustData: StationTrustResponse | null;
  isLoading?: boolean;
  onRefresh?: () => void;
  className?: string;
}

export const SystemTrustPanel: React.FC<SystemTrustPanelProps> = ({
  trustData,
  isLoading = false,
  onRefresh,
  className = '',
}) => {
  if (isLoading && !trustData) {
    return (
      <div className={`p-5 rounded-xl bg-slate-900/90 border border-slate-800/80 animate-pulse ${className}`}>
        <div className="h-5 w-48 bg-slate-800 rounded mb-4" />
        <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
          <div className="h-20 bg-slate-800/60 rounded" />
          <div className="h-20 bg-slate-800/60 rounded" />
          <div className="h-20 bg-slate-800/60 rounded" />
        </div>
      </div>
    );
  }

  if (!trustData) {
    return null;
  }

  const { freshness, quality, provenance, prediction, automation, degraded_state } = trustData;

  const getPredictionPillStyle = (readiness: string) => {
    switch (readiness) {
      case 'READY':
        return 'bg-emerald-500/10 text-emerald-400 border-emerald-500/30';
      case 'INSUFFICIENT_HISTORY':
        return 'bg-amber-500/10 text-amber-300 border-amber-500/30';
      case 'STALE_INPUT':
        return 'bg-orange-500/10 text-orange-300 border-orange-500/30';
      default:
        return 'bg-slate-800 text-slate-400 border-slate-700';
    }
  };

  return (
    <div
      className={`p-5 rounded-xl bg-slate-900/90 border border-slate-800/80 shadow-lg shadow-black/20 ${className}`}
    >
      {/* Degraded State Warning Banner */}
      {degraded_state?.is_degraded && (
        <div className="mb-4 p-3 rounded-lg bg-amber-500/10 border border-amber-500/30 text-amber-300 text-xs flex items-start gap-2.5">
          <AlertTriangle className="w-4 h-4 text-amber-400 shrink-0 mt-0.5" />
          <div className="space-y-1">
            <div className="font-semibold text-amber-200">System Operating in Degraded Mode</div>
            <ul className="list-disc pl-4 space-y-0.5 text-amber-300/90">
              {degraded_state.notes.map((note, idx) => (
                <li key={idx}>{note}</li>
              ))}
            </ul>
          </div>
        </div>
      )}

      {/* Header */}
      <div className="flex flex-wrap items-center justify-between gap-3 mb-4 border-b border-slate-800/80 pb-3">
        <div className="flex items-center gap-2">
          <div className="p-1.5 rounded-lg bg-emerald-500/10 border border-emerald-500/20 text-emerald-400">
            <ShieldCheck className="w-4 h-4" />
          </div>
          <div>
            <h3 className="text-sm font-bold text-slate-200 tracking-tight flex items-center gap-2">
              Data Quality & Operational Trust
              <span className="text-xs font-mono font-normal text-slate-400">
                ({trustData.location_name})
              </span>
            </h3>
            <p className="text-xs text-slate-500">
              Deterministic verification of telemetry freshness, CPCB completeness, and forecast readiness.
            </p>
          </div>
        </div>

        <div className="flex items-center gap-2">
          {onRefresh && (
            <button
              onClick={onRefresh}
              disabled={isLoading}
              className="p-1.5 rounded-lg bg-slate-800 hover:bg-slate-700 border border-slate-700 text-slate-300 hover:text-white transition disabled:opacity-50 text-xs flex items-center gap-1"
              title="Refresh trust metrics"
            >
              <RefreshCw className={`w-3.5 h-3.5 ${isLoading ? 'animate-spin' : ''}`} />
              <span className="hidden sm:inline">Verify</span>
            </button>
          )}
        </div>
      </div>

      {/* Trust Grid */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-3.5 text-xs">
        {/* Card 1: Data Freshness & Provenance */}
        <div className="p-3.5 rounded-lg bg-slate-800/40 border border-slate-800 space-y-2.5">
          <div className="flex items-center justify-between">
            <span className="font-semibold text-slate-300 flex items-center gap-1.5">
              <RefreshCw className="w-3.5 h-3.5 text-sky-400" />
              Telemetry Freshness
            </span>
            <FreshnessBadge status={freshness.status} ageHours={freshness.age_hours} size="sm" />
          </div>

          <div className="text-slate-400 text-[11px] leading-relaxed">
            {freshness.message}
          </div>

          <div className="pt-2 border-t border-slate-800/60 flex items-center justify-between">
            <span className="text-slate-500">Source:</span>
            <div className="flex items-center gap-1.5">
              <ProvenanceBadge sourceType={provenance.source_type} size="sm" />
              {provenance.provider && (
                <span className="text-[11px] font-mono text-slate-400">({provenance.provider})</span>
              )}
            </div>
          </div>
        </div>

        {/* Card 2: Data Completeness & CPCB NAQI Validation */}
        <div className="p-3.5 rounded-lg bg-slate-800/40 border border-slate-800 space-y-2.5">
          <div className="flex items-center justify-between">
            <span className="font-semibold text-slate-300 flex items-center gap-1.5">
              <Layers className="w-3.5 h-3.5 text-emerald-400" />
              Data Completeness
            </span>
            <span
              className={`font-mono text-[11px] px-2 py-0.5 rounded border ${
                quality.aqi_valid
                  ? 'bg-emerald-500/10 text-emerald-400 border-emerald-500/30'
                  : 'bg-amber-500/10 text-amber-300 border-amber-500/30'
              }`}
            >
              {quality.available_count}/{quality.total_pollutants_monitored} ({quality.completeness_pct}%)
            </span>
          </div>

          <div className="flex flex-wrap gap-1">
            {['pm25', 'pm10', 'no2', 'so2', 'co', 'o3'].map((pollutant) => {
              const isAvail = quality.pollutants_available.includes(pollutant);
              const isUsed = quality.pollutants_used_for_aqi.includes(pollutant);
              return (
                <span
                  key={pollutant}
                  className={`text-[10px] font-mono px-1.5 py-0.5 rounded border uppercase ${
                    isUsed
                      ? 'bg-emerald-500/20 text-emerald-300 border-emerald-500/40 font-bold'
                      : isAvail
                      ? 'bg-slate-700 text-slate-300 border-slate-600'
                      : 'bg-slate-900/60 text-slate-600 border-slate-800 line-through'
                  }`}
                  title={
                    isUsed
                      ? `${pollutant.toUpperCase()} used in NAQI`
                      : isAvail
                      ? `${pollutant.toUpperCase()} observed`
                      : `${pollutant.toUpperCase()} missing`
                  }
                >
                  {pollutant}
                </span>
              );
            })}
          </div>

          <div className="pt-2 border-t border-slate-800/60 flex items-center justify-between text-[11px]">
            <span className="text-slate-500">CPCB Sufficiency:</span>
            <span
              className={`font-semibold ${
                quality.aqi_valid ? 'text-emerald-400' : 'text-amber-400'
              }`}
            >
              {quality.aqi_valid ? 'Compliant (3+ incl. PM)' : 'Incomplete'}
            </span>
          </div>
        </div>

        {/* Card 3: Prediction Readiness & Background Sync */}
        <div className="p-3.5 rounded-lg bg-slate-800/40 border border-slate-800 space-y-2.5">
          <div className="flex items-center justify-between">
            <span className="font-semibold text-slate-300 flex items-center gap-1.5">
              <Sparkles className="w-3.5 h-3.5 text-violet-400" />
              ML Forecast Readiness
            </span>
            <span
              className={`font-mono text-[10px] px-2 py-0.5 rounded border font-semibold ${getPredictionPillStyle(
                prediction.readiness
              )}`}
            >
              {prediction.readiness.replace('_', ' ')}
            </span>
          </div>

          <div className="text-slate-400 text-[11px] leading-relaxed line-clamp-2" title={prediction.explanation}>
            {prediction.explanation}
          </div>

          <div className="pt-2 border-t border-slate-800/60 flex items-center justify-between text-[11px]">
            <span className="text-slate-500 flex items-center gap-1">
              <Cpu className="w-3 h-3 text-slate-400" />
              Continuous History:
            </span>
            <span className="font-mono text-slate-300">
              {prediction.continuous_hourly_count} / 4 hrs
            </span>
          </div>
        </div>
      </div>

      {/* Bottom Provenance Notice */}
      {provenance.notice && (
        <div className="mt-3 text-[11px] text-slate-500 flex items-center gap-1.5">
          <Info className="w-3.5 h-3.5 text-slate-400 shrink-0" />
          <span>{provenance.notice}</span>
          {automation && typeof automation.status === 'string' && (
            <span className="ml-auto font-mono text-[10px] text-slate-400">
              Supervisor: {automation.status}
            </span>
          )}
        </div>
      )}
    </div>
  );
};

export default SystemTrustPanel;
