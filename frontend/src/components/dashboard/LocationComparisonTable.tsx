import React from 'react';
import type { LocationComparisonItem } from '../../types/analytics';
import { getAQICategoryStyle } from '../../utils/aqiFormatters';
import { MapPin, Scale } from 'lucide-react';

interface LocationComparisonTableProps {
  locations: LocationComparisonItem[];
  selectedLocationId?: number;
  onSelectLocation?: (locationId: number) => void;
  isLoading: boolean;
}

export const LocationComparisonTable: React.FC<LocationComparisonTableProps> = ({
  locations,
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

  const getAQICategoryForValue = (val: number | null) => {
    if (val === null) return null;
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
          <div className="p-2 rounded-xl bg-teal-500/10 text-teal-400 border border-teal-500/20">
            <Scale className="w-4 h-4" />
          </div>
          <div>
            <h3 className="text-sm font-bold text-white uppercase tracking-wider">
              Objective Location Comparison
            </h3>
            <p className="text-xs text-slate-400">
              Cross-location telemetry metrics for the active observation interval
            </p>
          </div>
        </div>

        <span className="px-2.5 py-1 rounded-lg bg-slate-800/80 text-slate-300 text-xs font-mono">
          {locations.length} Locations
        </span>
      </div>

      {locations.length === 0 ? (
        <div className="p-6 rounded-xl border border-dashed border-slate-800 bg-slate-950/40 text-center space-y-2">
          <MapPin className="w-6 h-6 text-slate-600 mx-auto" />
          <p className="text-xs text-slate-400 font-medium">
            No cross-location comparison data available for this time range.
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
                <th className="py-2.5 px-3 text-center">Mean AQI Category</th>
                <th className="py-2.5 px-3">Dominant Pollutant</th>
                <th className="py-2.5 px-3 text-right">Observations</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-800/60 font-mono">
              {locations.map((loc) => {
                const isSelected = selectedLocationId === loc.location_id;
                const cat = getAQICategoryForValue(loc.average_aqi);
                const style = getAQICategoryStyle(cat);

                return (
                  <tr
                    key={loc.location_id}
                    onClick={() => onSelectLocation && onSelectLocation(loc.location_id)}
                    className={`transition cursor-pointer ${
                      isSelected
                        ? 'bg-teal-500/10 border-l-2 border-teal-500'
                        : 'hover:bg-slate-900/40'
                    }`}
                  >
                    <td className="py-2.5 px-3 text-slate-200 font-sans font-medium whitespace-nowrap">
                      <div className="flex items-center gap-1.5">
                        <MapPin
                          className={`w-3.5 h-3.5 ${
                            isSelected ? 'text-teal-400' : 'text-slate-500'
                          }`}
                        />
                        <span>{loc.location_name}</span>
                        <span className="text-[10px] text-slate-400 font-mono">({loc.city})</span>
                      </div>
                    </td>
                    <td className="py-2.5 px-3 text-right font-bold text-white whitespace-nowrap">
                      {loc.average_aqi !== null ? loc.average_aqi.toFixed(1) : '—'}
                    </td>
                    <td className="py-2.5 px-3 text-right text-amber-300 font-bold whitespace-nowrap">
                      {loc.max_aqi !== null ? loc.max_aqi.toFixed(1) : '—'}
                    </td>
                    <td className="py-2.5 px-3 text-center whitespace-nowrap">
                      {cat ? (
                        <span
                          className={`px-2 py-0.5 rounded text-[10px] font-bold border ${style.bg} ${style.text} ${style.border}`}
                        >
                          {style.label}
                        </span>
                      ) : (
                        <span className="text-[10px] text-slate-500 font-sans italic">
                          Unavailable
                        </span>
                      )}
                    </td>
                    <td className="py-2.5 px-3 text-slate-300 whitespace-nowrap font-sans font-medium">
                      {loc.dominant_pollutant || 'N/A'}
                    </td>
                    <td className="py-2.5 px-3 text-right text-slate-400 font-sans">
                      {loc.observation_count}
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
