import React from 'react';
import type { PollutionEventItem } from '../../types/analytics';
import { getAQICategoryStyle } from '../../utils/aqiFormatters';
import { Flame, CheckCircle2, Clock } from 'lucide-react';

interface PollutionEventsTableProps {
  events: PollutionEventItem[];
  isLoading: boolean;
}

export const PollutionEventsTable: React.FC<PollutionEventsTableProps> = ({
  events,
  isLoading,
}) => {
  if (isLoading) {
    return (
      <div className="p-6 rounded-2xl bg-slate-900/60 border border-slate-800 animate-pulse space-y-3">
        <div className="h-4 bg-slate-800 rounded w-1/4" />
        <div className="h-32 bg-slate-800/40 rounded-xl" />
      </div>
    );
  }

  const getAQICategoryForValue = (val: number) => {
    if (val <= 50) return 'Good';
    if (val <= 100) return 'Satisfactory';
    if (val <= 200) return 'Moderate';
    if (val <= 300) return 'Poor';
    if (val <= 400) return 'Very Poor';
    return 'Severe';
  };

  return (
    <div className="p-6 rounded-2xl bg-slate-900/60 border border-slate-800 shadow-lg space-y-4">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <div className="p-2 rounded-xl bg-rose-500/10 text-rose-400 border border-rose-500/20">
            <Flame className="w-4 h-4" />
          </div>
          <div>
            <h3 className="text-sm font-bold text-white uppercase tracking-wider">
              Sustained Pollution Episodes
            </h3>
            <p className="text-xs text-slate-400">
              Episodes meeting minimum duration and elevated threshold criteria
            </p>
          </div>
        </div>

        <span className="px-2.5 py-1 rounded-lg bg-slate-800/80 text-slate-300 text-xs font-mono">
          {events.length} {events.length === 1 ? 'Event' : 'Events'}
        </span>
      </div>

      {events.length === 0 ? (
        <div className="p-6 rounded-xl border border-dashed border-slate-800 bg-slate-950/40 text-center space-y-2">
          <CheckCircle2 className="w-6 h-6 text-teal-400 mx-auto" />
          <p className="text-xs font-medium text-slate-300">
            No sustained pollution events detected in this observation window.
          </p>
          <p className="text-[11px] text-slate-500">
            No persistent excursions above defined concentration thresholds.
          </p>
        </div>
      ) : (
        <div className="overflow-x-auto rounded-xl border border-slate-800 bg-slate-950/30">
          <table className="w-full text-xs text-left">
            <thead className="text-[11px] uppercase tracking-wider bg-slate-900/80 text-slate-400 border-b border-slate-800">
              <tr>
                <th className="py-2.5 px-3">Time Span</th>
                <th className="py-2.5 px-3">Duration</th>
                <th className="py-2.5 px-3">Peak AQI</th>
                <th className="py-2.5 px-3">Dominant Pollutant</th>
                <th className="py-2.5 px-3 text-right">Surge %</th>
                <th className="py-2.5 px-3">Detection Reason</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-800/60 font-mono">
              {events.map((ev, idx) => {
                const cat = getAQICategoryForValue(ev.max_aqi);
                const style = getAQICategoryStyle(cat);
                const startStr = new Date(ev.start_time).toLocaleString(undefined, {
                  month: 'short',
                  day: 'numeric',
                  hour: '2-digit',
                  minute: '2-digit',
                });
                const endStr = new Date(ev.end_time).toLocaleTimeString(undefined, {
                  hour: '2-digit',
                  minute: '2-digit',
                });

                return (
                  <tr key={idx} className="hover:bg-slate-900/40 transition">
                    <td className="py-2.5 px-3 text-slate-300 whitespace-nowrap">
                      {startStr} – {endStr}
                    </td>
                    <td className="py-2.5 px-3 text-slate-400 whitespace-nowrap">
                      <div className="flex items-center gap-1">
                        <Clock className="w-3 h-3 text-slate-500" />
                        <span>{ev.duration_hours.toFixed(1)} hrs</span>
                      </div>
                    </td>
                    <td className="py-2.5 px-3 whitespace-nowrap">
                      <div className="flex items-center gap-2">
                        <span className="font-bold text-white text-sm">{ev.max_aqi.toFixed(0)}</span>
                        <span
                          className={`px-2 py-0.5 rounded text-[10px] font-bold border ${style.bg} ${style.text} ${style.border}`}
                        >
                          {style.label}
                        </span>
                      </div>
                    </td>
                    <td className="py-2.5 px-3 font-semibold text-slate-200 whitespace-nowrap">
                      {ev.dominant_pollutant || 'N/A'}
                    </td>
                    <td className="py-2.5 px-3 text-right text-rose-400 font-bold whitespace-nowrap">
                      +{ev.increase_percentage.toFixed(1)}%
                    </td>
                    <td className="py-2.5 px-3 font-sans text-slate-300 text-[11px]">
                      {ev.detection_reason}
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
