import React from 'react';
import { getAQICategoryStyle } from '../../utils/aqiFormatters';
import type { AQICategory, AQIStatus } from '../../types/aqi';
import ProvenanceBadge, { type ProvenanceType } from './ProvenanceBadge';
import FreshnessBadge from './FreshnessBadge';
import type { DataFreshnessStatus } from '../../types/trust';
import { Activity, AlertTriangle } from 'lucide-react';

export interface HeroAQIDisplayProps {
  aqi?: number | null;
  category?: AQICategory | string | null;
  dominantPollutant?: string | null;
  status?: AQICategory | AQIStatus | string | null;
  stationName?: string;
  cityName?: string;
  timestamp?: string | null;
  sourceType?: ProvenanceType | null;
  freshnessStatus?: DataFreshnessStatus | string | null;
  freshnessAgeHours?: number | null;
  isLoading?: boolean;
  className?: string;
}

export const HeroAQIDisplay: React.FC<HeroAQIDisplayProps> = ({
  aqi,
  category,
  dominantPollutant,
  status,
  stationName,
  cityName,
  timestamp,
  sourceType,
  freshnessStatus,
  freshnessAgeHours,
  isLoading = false,
  className = '',
}) => {
  if (isLoading) {
    return (
      <div
        className={`p-6 rounded-xl bg-slate-900/90 border border-slate-800/80 animate-pulse ${className}`}
      >
        <div className="h-4 w-32 bg-slate-800 rounded mb-4" />
        <div className="h-16 w-48 bg-slate-800 rounded mb-3" />
        <div className="h-4 w-40 bg-slate-800 rounded" />
      </div>
    );
  }

  const hasValidAQI = aqi !== null && aqi !== undefined && !Number.isNaN(aqi);
  const catStyle = getAQICategoryStyle(category);
  const normStatus = (status || '').toUpperCase();
  const isInsufficient = normStatus.includes('INSUFFICIENT');
  const isInvalid = normStatus.includes('INVALID');

  // Dominant pollutant display string
  const dominantFormatted = dominantPollutant
    ? dominantPollutant.toUpperCase().replace('.', '')
    : null;

  return (
    <div
      className={`p-6 rounded-xl bg-slate-900/90 border border-slate-800/80 shadow-xl shadow-black/30 relative overflow-hidden ${className}`}
    >
      {/* Background ambient tint based on category */}
      {hasValidAQI && (
        <div
          className="absolute -right-12 -bottom-12 w-64 h-64 rounded-full blur-3xl opacity-10 pointer-events-none"
          style={{ backgroundColor: catStyle.hex }}
        />
      )}

      {/* Header row: Station & Provenance */}
      <div className="flex flex-wrap items-center justify-between gap-3 mb-4">
        <div className="min-w-0">
          <div className="text-xs uppercase font-mono tracking-wider text-slate-400 font-semibold flex items-center gap-1.5">
            <Activity className="w-3.5 h-3.5 text-emerald-400" />
            <span>Real-Time Air Quality Assessment</span>
          </div>
          {(stationName || cityName) && (
            <div className="text-base font-bold text-slate-100 tracking-tight mt-0.5 truncate">
              {stationName || 'Monitoring Station'}{' '}
              {cityName && <span className="text-slate-400 font-normal">({cityName})</span>}
            </div>
          )}
        </div>

        <div className="flex items-center gap-2 flex-wrap">
          {freshnessStatus && (
            <FreshnessBadge status={freshnessStatus} ageHours={freshnessAgeHours} size="sm" />
          )}
          <ProvenanceBadge sourceType={sourceType || 'API'} />
        </div>
      </div>

      {/* Main Metric Row */}
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div>
          {hasValidAQI ? (
            <div className="flex items-baseline gap-3">
              <span className="text-6xl font-black font-mono tracking-tighter text-slate-100 tabular-nums">
                {Math.round(aqi)}
              </span>
              <div className="flex flex-col gap-1">
                <span className="text-xs font-mono text-slate-500 font-semibold uppercase">
                  CPCB NAQI Index
                </span>
                <span
                  className={`inline-flex items-center gap-1.5 px-2.5 py-0.5 rounded-full text-xs font-semibold border ${catStyle.bg} ${catStyle.text} ${catStyle.border}`}
                >
                  <span className={`w-1.5 h-1.5 rounded-full ${catStyle.dot}`} />
                  {catStyle.label}
                </span>
              </div>
            </div>
          ) : (
            <div className="flex items-baseline gap-3">
              <span className="text-6xl font-black font-mono tracking-tighter text-slate-600">
                —
              </span>
              <div className="flex flex-col gap-1">
                <span className="text-xs font-mono text-slate-500 font-semibold uppercase">
                  Status
                </span>
                <span className="inline-flex items-center gap-1.5 px-2.5 py-0.5 rounded-full text-xs font-semibold border bg-slate-800 text-slate-400 border-slate-700">
                  {isInsufficient
                    ? 'Insufficient Data'
                    : isInvalid
                    ? 'Invalid Sensor Data'
                    : 'Data Unavailable'}
                </span>
              </div>
            </div>
          )}
        </div>

        {/* Diagnostics & Metadata */}
        <div className="text-right space-y-1 text-xs">
          {dominantFormatted && hasValidAQI && (
            <div className="text-slate-300 font-mono">
              Driver Pollutant:{' '}
              <span className="font-bold text-slate-100 px-1.5 py-0.5 bg-slate-800 border border-slate-700 rounded">
                {dominantFormatted}
              </span>
            </div>
          )}

          {isInsufficient && (
            <div className="flex items-center gap-1.5 text-amber-400 font-mono">
              <AlertTriangle className="w-3.5 h-3.5" />
              <span>Requires min. 3 pollutants (incl. PM2.5 or PM10)</span>
            </div>
          )}

          {timestamp && (
            <div className="text-slate-500 font-mono">
              Recorded:{' '}
              <span className="text-slate-400">
                {new Date(timestamp).toLocaleTimeString([], {
                  hour: '2-digit',
                  minute: '2-digit',
                })}{' '}
                ({new Date(timestamp).toLocaleDateString()})
              </span>
            </div>
          )}
        </div>
      </div>
    </div>
  );
};

export default HeroAQIDisplay;
