import React from 'react';
import type { StationMapItem } from './StationMap';
import { getAQICategoryStyle } from '../../utils/aqiFormatters';
import { MapPin, ArrowUpRight, AlertCircle } from 'lucide-react';

interface StationListProps {
  stations: StationMapItem[];
  selectedStationId: number | null;
  onSelectStation: (stationId: number) => void;
  onNavigateToDashboard: (stationId: number) => void;
}

export const StationList: React.FC<StationListProps> = ({
  stations,
  selectedStationId,
  onSelectStation,
  onNavigateToDashboard,
}) => {
  return (
    <div className="p-4 rounded-2xl bg-slate-900/80 border border-slate-800 shadow-xl space-y-4">
      <div className="flex items-center justify-between border-b border-slate-800 pb-3">
        <div className="flex items-center gap-2">
          <div className="p-1.5 rounded-lg bg-teal-500/10 text-teal-400 border border-teal-500/20">
            <MapPin className="w-4 h-4" />
          </div>
          <div>
            <h3 className="text-sm font-bold text-white uppercase tracking-wider">
              Monitored Stations
            </h3>
            <p className="text-[11px] text-slate-400">
              Click a station to inspect and center on map
            </p>
          </div>
        </div>

        <span className="text-xs font-mono text-slate-400 bg-slate-950/60 px-2.5 py-1 rounded-lg border border-slate-800">
          {stations.length} Total Stations
        </span>
      </div>

      <div className="space-y-2 max-h-[380px] overflow-y-auto pr-1">
        {stations.map((item) => {
          const { location, aqiData, sourceType } = item;
          const isSelected = selectedStationId === location.id;
          const isCalculated = aqiData && aqiData.status === 'CALCULATED' && aqiData.aqi !== null;
          const categoryStyle = getAQICategoryStyle(aqiData?.category);
          const hasCoords =
            location.latitude !== null &&
            location.latitude !== undefined &&
            !isNaN(location.latitude) &&
            location.longitude !== null &&
            location.longitude !== undefined &&
            !isNaN(location.longitude);

          return (
            <div
              key={location.id}
              onClick={() => onSelectStation(location.id)}
              className={`p-3 rounded-xl border transition cursor-pointer flex flex-col sm:flex-row sm:items-center justify-between gap-3 ${
                isSelected
                  ? 'bg-slate-800/90 border-teal-500/80 shadow-lg shadow-teal-500/5 ring-1 ring-teal-500/40'
                  : 'bg-slate-950/50 border-slate-800/80 hover:border-slate-700 hover:bg-slate-900/60'
              }`}
            >
              {/* Left: Station Identity */}
              <div className="flex items-start gap-2.5">
                <div
                  className="w-3 h-3 rounded-full mt-1 shrink-0"
                  style={{ backgroundColor: categoryStyle.hex }}
                />
                <div className="space-y-0.5">
                  <div className="flex items-center gap-2">
                    <h4 className="text-xs font-bold text-white">{location.name}</h4>
                    {!hasCoords && (
                      <span className="inline-flex items-center gap-1 text-[10px] text-amber-400 bg-amber-500/10 px-1.5 py-0.5 rounded border border-amber-500/30">
                        <AlertCircle className="w-2.5 h-2.5" />
                        No Coords
                      </span>
                    )}
                  </div>
                  <div className="text-[11px] text-slate-400">
                    {location.city}, {location.state}
                  </div>
                </div>
              </div>

              {/* Right: AQI, Badges & Action */}
              <div className="flex items-center gap-3 self-end sm:self-auto">
                <div className="text-right space-y-0.5">
                  <div className="flex items-center justify-end gap-1.5 font-mono">
                    <span className="text-xs text-slate-400 font-sans">AQI:</span>
                    {isCalculated ? (
                      <span className="text-sm font-extrabold text-white font-mono">
                        {aqiData.aqi}
                      </span>
                    ) : (
                      <span className="text-[11px] text-slate-500 italic font-sans">Unavailable</span>
                    )}
                  </div>

                  <div className="flex items-center justify-end gap-1.5">
                    <span
                      className={`px-1.5 py-0.2 rounded text-[9px] font-bold border ${categoryStyle.bg} ${categoryStyle.text} ${categoryStyle.border}`}
                    >
                      {categoryStyle.label}
                    </span>
                    <span className="px-1.5 py-0.2 rounded text-[9px] font-mono text-slate-400 bg-slate-900 border border-slate-800">
                      {sourceType}
                    </span>
                  </div>
                </div>

                <button
                  type="button"
                  title="View detailed station analytics in dashboard"
                  onClick={(e) => {
                    e.stopPropagation();
                    onNavigateToDashboard(location.id);
                  }}
                  className="p-2 rounded-lg bg-slate-800 hover:bg-teal-500 hover:text-slate-950 text-slate-300 border border-slate-700 transition"
                >
                  <ArrowUpRight className="w-3.5 h-3.5" />
                </button>
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
};
