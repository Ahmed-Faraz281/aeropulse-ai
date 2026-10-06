import React from 'react';
import type { HotspotIndicatorItem } from '../../types/analytics';
import { Target, Info } from 'lucide-react';

interface HotspotIndicatorsTableProps {
  hotspots: HotspotIndicatorItem[];
  selectedLocationId?: number;
  onSelectLocation?: (locationId: number) => void;
  isLoading: boolean;
}

export const HotspotIndicatorsTable: React.FC<HotspotIndicatorsTableProps> = ({
  hotspots,
  selectedLocationId,
  onSelectLocation,
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

  // Objective exposure profile classification (strictly non-subjective)
  const getExposureProfile = (hours: number, eventCount: number, meanAqi: number | null) => {
    if (meanAqi === null) {
      return { label: 'Insufficient Data', color: 'text-slate-400 bg-slate-800 border-slate-700' };
    }
    if (hours >= 20 || eventCount >= 3) {
      return {
        label: 'Persistent Elevated Exposure',
        color: 'text-amber-400 bg-amber-500/10 border-amber-500/30',
      };
    }
    if (hours > 0 || eventCount > 0) {
      return {
        label: 'Periodic Episodic Excursions',
        color: 'text-yellow-400 bg-yellow-500/10 border-yellow-500/30',
      };
    }
    return {
      label: 'Standard Baseline Exposure',
      color: 'text-emerald-400 bg-emerald-500/10 border-emerald-500/30',
    };
  };

  return (
    <div className="p-6 rounded-2xl bg-slate-900/60 border border-slate-800 shadow-lg space-y-4">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <div className="p-2 rounded-xl bg-orange-500/10 text-orange-400 border border-orange-500/20">
            <Target className="w-4 h-4" />
          </div>
          <div>
            <h3 className="text-sm font-bold text-white uppercase tracking-wider">
              Objective Hotspot & Exposure Indicators
            </h3>
            <p className="text-xs text-slate-400">
              Analysis of cumulative elevated hours (AQI &gt; 200) and discrete episode frequency
            </p>
          </div>
        </div>

        <span className="px-2.5 py-1 rounded-lg bg-slate-800/80 text-slate-300 text-xs font-mono">
          {hotspots.length} Monitored Areas
        </span>
      </div>

      {hotspots.length === 0 ? (
        <div className="p-6 rounded-xl border border-dashed border-slate-800 bg-slate-950/40 text-center space-y-2">
          <Info className="w-6 h-6 text-slate-600 mx-auto" />
          <p className="text-xs text-slate-400 font-medium">
            No hotspot indicators computed for the selected period.
          </p>
        </div>
      ) : (
        <div className="overflow-x-auto rounded-xl border border-slate-800 bg-slate-950/30">
          <table className="w-full text-xs text-left">
            <thead className="text-[11px] uppercase tracking-wider bg-slate-900/80 text-slate-400 border-b border-slate-800">
              <tr>
                <th className="py-2.5 px-3">Location & City</th>
                <th className="py-2.5 px-3 text-right">Mean AQI</th>
                <th className="py-2.5 px-3 text-right">Peak AQI</th>
                <th className="py-2.5 px-3 text-right">Elevated Hours (&gt;200 AQI)</th>
                <th className="py-2.5 px-3 text-right">Event Count</th>
                <th className="py-2.5 px-3 text-center">Exposure Profile</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-800/60 font-mono">
              {hotspots.map((item) => {
                const isSelected = selectedLocationId === item.location_id;
                const profile = getExposureProfile(
                  item.high_pollution_hours,
                  item.event_count,
                  item.mean_aqi
                );

                return (
                  <tr
                    key={item.location_id}
                    onClick={() => onSelectLocation && onSelectLocation(item.location_id)}
                    className={`transition cursor-pointer ${
                      isSelected
                        ? 'bg-orange-500/10 border-l-2 border-orange-500'
                        : 'hover:bg-slate-900/40'
                    }`}
                  >
                    <td className="py-2.5 px-3 text-slate-200 font-sans font-medium whitespace-nowrap">
                      <span>{item.location_name}</span>{' '}
                      <span className="text-[10px] text-slate-400 font-mono">({item.city})</span>
                    </td>
                    <td className="py-2.5 px-3 text-right font-bold text-white whitespace-nowrap">
                      {item.mean_aqi !== null ? item.mean_aqi.toFixed(1) : '—'}
                    </td>
                    <td className="py-2.5 px-3 text-right font-bold text-amber-300 whitespace-nowrap">
                      {item.max_aqi !== null ? item.max_aqi.toFixed(1) : '—'}
                    </td>
                    <td className="py-2.5 px-3 text-right text-orange-400 font-bold whitespace-nowrap">
                      {item.high_pollution_hours} hrs
                    </td>
                    <td className="py-2.5 px-3 text-right text-slate-300 whitespace-nowrap">
                      {item.event_count}
                    </td>
                    <td className="py-2.5 px-3 text-center whitespace-nowrap font-sans">
                      <span
                        className={`inline-block px-2.5 py-0.5 rounded-full text-[10px] font-semibold border ${profile.color}`}
                      >
                        {profile.label}
                      </span>
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
