import React from 'react';
import type { LocationAnalyticsSummary } from '../../types/analytics';
import { POLLUTANT_METADATA } from '../../utils/aqiFormatters';
import {
  TrendingUp,
  TrendingDown,
  Minus,
  HelpCircle,
  Calculator,
  Layers,
} from 'lucide-react';

interface AnalyticsSummaryCardProps {
  summary: LocationAnalyticsSummary | null;
  isLoading: boolean;
}

export const AnalyticsSummaryCard: React.FC<AnalyticsSummaryCardProps> = ({
  summary,
  isLoading,
}) => {
  if (isLoading) {
    return (
      <div className="p-6 rounded-2xl bg-slate-900/60 border border-slate-800 animate-pulse space-y-4">
        <div className="h-4 bg-slate-800 rounded w-1/4" />
        <div className="grid grid-cols-2 sm:grid-cols-5 gap-3">
          {Array.from({ length: 5 }).map((_, i) => (
            <div key={i} className="h-20 bg-slate-800/60 rounded-xl" />
          ))}
        </div>
      </div>
    );
  }

  const aqiStats = summary?.aqi_statistics;
  const trend = summary?.trend_direction;

  const renderTrendBadge = (direction?: string) => {
    switch (direction) {
      case 'INCREASING':
        return (
          <span className="inline-flex items-center gap-1 px-2.5 py-1 rounded-full text-xs font-semibold bg-rose-500/15 text-rose-400 border border-rose-500/30">
            <TrendingUp className="w-3.5 h-3.5" />
            Increasing Trend
          </span>
        );
      case 'DECREASING':
        return (
          <span className="inline-flex items-center gap-1 px-2.5 py-1 rounded-full text-xs font-semibold bg-emerald-500/15 text-emerald-400 border border-emerald-500/30">
            <TrendingDown className="w-3.5 h-3.5" />
            Decreasing Trend
          </span>
        );
      case 'STABLE':
        return (
          <span className="inline-flex items-center gap-1 px-2.5 py-1 rounded-full text-xs font-semibold bg-teal-500/15 text-teal-400 border border-teal-500/30">
            <Minus className="w-3.5 h-3.5" />
            Stable
          </span>
        );
      default:
        return (
          <span className="inline-flex items-center gap-1 px-2.5 py-1 rounded-full text-xs font-semibold bg-slate-800 text-slate-400 border border-slate-700">
            <HelpCircle className="w-3.5 h-3.5" />
            Insufficient Data
          </span>
        );
    }
  };

  const statItems = [
    { label: 'Mean AQI', val: aqiStats?.mean },
    { label: 'Min AQI', val: aqiStats?.minimum },
    { label: 'Max AQI', val: aqiStats?.maximum },
    { label: 'Median AQI', val: aqiStats?.median },
    { label: 'Std Dev', val: aqiStats?.stddev },
  ];

  return (
    <div className="p-6 rounded-2xl bg-slate-900/60 border border-slate-800 shadow-lg space-y-6">
      {/* Header & Trend Status */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3">
        <div className="flex items-center gap-2">
          <div className="p-2 rounded-xl bg-indigo-500/10 text-indigo-400 border border-indigo-500/20">
            <Calculator className="w-4 h-4" />
          </div>
          <div>
            <h3 className="text-sm font-bold text-white uppercase tracking-wider">
              Analytics Summary & Distribution
            </h3>
            <p className="text-xs text-slate-400">
              Descriptive statistics for selected observation period
            </p>
          </div>
        </div>

        <div>{renderTrendBadge(trend)}</div>
      </div>

      {/* AQI Statistics Grid */}
      <div className="grid grid-cols-2 sm:grid-cols-5 gap-3">
        {statItems.map((item, idx) => (
          <div
            key={idx}
            className="p-3.5 rounded-xl bg-slate-950/50 border border-slate-800/80 space-y-1"
          >
            <div className="text-[11px] font-medium text-slate-400 uppercase tracking-wider">
              {item.label}
            </div>
            <div className="text-xl font-bold font-mono text-white">
              {item.val !== null && item.val !== undefined ? (
                item.val.toFixed(1)
              ) : (
                <span className="text-xs font-normal text-slate-500 italic">Not available</span>
              )}
            </div>
          </div>
        ))}
      </div>

      {/* Pollutants Breakdown Table */}
      {summary?.pollutant_statistics &&
        Object.keys(summary.pollutant_statistics).length > 0 && (
          <div className="space-y-3 pt-2">
            <div className="flex items-center gap-2 text-xs font-semibold text-slate-300">
              <Layers className="w-3.5 h-3.5 text-indigo-400" />
              <span>Pollutant Summary Distribution</span>
            </div>

            <div className="overflow-x-auto rounded-xl border border-slate-800 bg-slate-950/30">
              <table className="w-full text-xs text-left">
                <thead className="text-[11px] uppercase tracking-wider bg-slate-900/80 text-slate-400 border-b border-slate-800">
                  <tr>
                    <th className="py-2.5 px-3">Pollutant</th>
                    <th className="py-2.5 px-3">Mean</th>
                    <th className="py-2.5 px-3">Min</th>
                    <th className="py-2.5 px-3">Max</th>
                    <th className="py-2.5 px-3">Median</th>
                    <th className="py-2.5 px-3">Std Dev</th>
                    <th className="py-2.5 px-3 text-right">Readings</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-800/60 font-mono">
                  {Object.entries(summary.pollutant_statistics).map(([code, stats]) => {
                    const meta = POLLUTANT_METADATA[code] || {
                      label: code.toUpperCase(),
                      unit: '',
                    };
                    return (
                      <tr key={code} className="hover:bg-slate-900/40 transition">
                        <td className="py-2 px-3 font-semibold text-slate-200">
                          {meta.label} <span className="text-[10px] text-slate-500">({meta.unit})</span>
                        </td>
                        <td className="py-2 px-3 text-slate-300">
                          {stats.mean !== null ? stats.mean.toFixed(2) : '—'}
                        </td>
                        <td className="py-2 px-3 text-slate-400">
                          {stats.minimum !== null ? stats.minimum.toFixed(2) : '—'}
                        </td>
                        <td className="py-2 px-3 text-amber-300">
                          {stats.maximum !== null ? stats.maximum.toFixed(2) : '—'}
                        </td>
                        <td className="py-2 px-3 text-slate-300">
                          {stats.median !== null ? stats.median.toFixed(2) : '—'}
                        </td>
                        <td className="py-2 px-3 text-slate-400">
                          {stats.stddev !== null ? stats.stddev.toFixed(2) : '—'}
                        </td>
                        <td className="py-2 px-3 text-right text-slate-400 font-sans">
                          {stats.count}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          </div>
        )}
    </div>
  );
};
