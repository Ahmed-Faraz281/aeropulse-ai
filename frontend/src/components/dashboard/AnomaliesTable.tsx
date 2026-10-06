import React from 'react';
import type { AnomalyItem } from '../../types/analytics';
import { POLLUTANT_METADATA } from '../../utils/aqiFormatters';
import { AlertCircle, CheckCircle2 } from 'lucide-react';

interface AnomaliesTableProps {
  anomalies: AnomalyItem[];
  isLoading: boolean;
}

export const AnomaliesTable: React.FC<AnomaliesTableProps> = ({ anomalies, isLoading }) => {
  if (isLoading) {
    return (
      <div className="p-6 rounded-2xl bg-slate-900/60 border border-slate-800 animate-pulse space-y-3">
        <div className="h-4 bg-slate-800 rounded w-1/4" />
        <div className="h-32 bg-slate-800/40 rounded-xl" />
      </div>
    );
  }

  const getSeverityBadge = (severity: string) => {
    switch (severity.toUpperCase()) {
      case 'HIGH':
        return (
          <span className="px-2 py-0.5 rounded-full text-[10px] font-bold bg-rose-500/15 text-rose-400 border border-rose-500/30">
            HIGH
          </span>
        );
      case 'MEDIUM':
        return (
          <span className="px-2 py-0.5 rounded-full text-[10px] font-bold bg-amber-500/15 text-amber-400 border border-amber-500/30">
            MEDIUM
          </span>
        );
      case 'LOW':
      default:
        return (
          <span className="px-2 py-0.5 rounded-full text-[10px] font-bold bg-blue-500/15 text-blue-400 border border-blue-500/30">
            LOW
          </span>
        );
    }
  };

  return (
    <div className="p-6 rounded-2xl bg-slate-900/60 border border-slate-800 shadow-lg space-y-4">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <div className="p-2 rounded-xl bg-amber-500/10 text-amber-400 border border-amber-500/20">
            <AlertCircle className="w-4 h-4" />
          </div>
          <div>
            <h3 className="text-sm font-bold text-white uppercase tracking-wider">
              Statistical Anomalies
            </h3>
            <p className="text-xs text-slate-400">
              Deviations detected via rolling Z-Score and IQR criteria
            </p>
          </div>
        </div>

        <span className="px-2.5 py-1 rounded-lg bg-slate-800/80 text-slate-300 text-xs font-mono">
          {anomalies.length} {anomalies.length === 1 ? 'Anomaly' : 'Anomalies'}
        </span>
      </div>

      {anomalies.length === 0 ? (
        <div className="p-6 rounded-xl border border-dashed border-slate-800 bg-slate-950/40 text-center space-y-2">
          <CheckCircle2 className="w-6 h-6 text-emerald-400 mx-auto" />
          <p className="text-xs font-medium text-slate-300">
            No statistical anomalies detected in this observation window.
          </p>
          <p className="text-[11px] text-slate-500">
            Telemetry exhibits expected statistical baseline characteristics.
          </p>
        </div>
      ) : (
        <div className="overflow-x-auto rounded-xl border border-slate-800 bg-slate-950/30">
          <table className="w-full text-xs text-left">
            <thead className="text-[11px] uppercase tracking-wider bg-slate-900/80 text-slate-400 border-b border-slate-800">
              <tr>
                <th className="py-2.5 px-3">Timestamp</th>
                <th className="py-2.5 px-3">Metric</th>
                <th className="py-2.5 px-3 text-right">Observed</th>
                <th className="py-2.5 px-3 text-right">Expected</th>
                <th className="py-2.5 px-3 text-right">Score</th>
                <th className="py-2.5 px-3 text-center">Severity</th>
                <th className="py-2.5 px-3">Detection Reason</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-800/60 font-mono">
              {anomalies.map((item, idx) => {
                const meta = POLLUTANT_METADATA[item.metric.toLowerCase()] || {
                  label: item.metric.toUpperCase(),
                  unit: '',
                };
                return (
                  <tr key={idx} className="hover:bg-slate-900/40 transition">
                    <td className="py-2.5 px-3 text-slate-300 whitespace-nowrap">
                      {new Date(item.timestamp).toLocaleString(undefined, {
                        month: 'short',
                        day: 'numeric',
                        hour: '2-digit',
                        minute: '2-digit',
                      })}
                    </td>
                    <td className="py-2.5 px-3 font-semibold text-slate-200 whitespace-nowrap">
                      {meta.label}{' '}
                      {meta.unit && (
                        <span className="text-[10px] text-slate-500">({meta.unit})</span>
                      )}
                    </td>
                    <td className="py-2.5 px-3 text-right font-bold text-amber-300 whitespace-nowrap">
                      {item.observed_value.toFixed(1)}
                    </td>
                    <td className="py-2.5 px-3 text-right text-slate-400 whitespace-nowrap">
                      {item.expected_value.toFixed(1)}
                    </td>
                    <td className="py-2.5 px-3 text-right text-slate-300 whitespace-nowrap">
                      {item.score.toFixed(2)}
                    </td>
                    <td className="py-2.5 px-3 text-center whitespace-nowrap">
                      {getSeverityBadge(item.severity)}
                    </td>
                    <td className="py-2.5 px-3 font-sans text-slate-300 text-[11px]">
                      {item.reason}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
};
