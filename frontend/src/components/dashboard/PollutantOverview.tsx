import React from 'react';
import type { AirQualityReading } from '../../types/air_quality';
import { PollutantPillCard } from '../common/PollutantPillCard';
import { Wind, Thermometer, Droplets, Compass, Gauge } from 'lucide-react';

interface PollutantOverviewProps {
  reading: AirQualityReading | null;
  isLoading: boolean;
}

export const PollutantOverview: React.FC<PollutantOverviewProps> = ({ reading, isLoading }) => {
  if (isLoading) {
    return (
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 animate-pulse">
        {Array.from({ length: 8 }).map((_, i) => (
          <div key={i} className="p-4 rounded-xl bg-slate-800/50 border border-slate-700/60 h-24" />
        ))}
      </div>
    );
  }

  // All 8 CPCB NAQI pollutants preserved
  const pollutantKeys = ['pm25', 'pm10', 'no2', 'so2', 'co', 'o3', 'nh3', 'pb'];

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <h3 className="text-xs font-semibold text-slate-300 uppercase tracking-wider font-mono">
          CPCB Monitored Pollutants (8 Parameters)
        </h3>
        <span className="text-[11px] text-slate-500 font-mono">
          Concentrations
        </span>
      </div>

      {/* 8 Pollutants Grid with PollutantPillCard */}
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
        {pollutantKeys.map((key) => {
          const val = reading ? (reading as unknown as Record<string, unknown>)[key] : null;
          const numVal =
            val !== null && val !== undefined && typeof val === 'number' && !Number.isNaN(val)
              ? val
              : null;

          return (
            <PollutantPillCard
              key={key}
              code={key}
              concentration={numVal}
            />
          );
        })}
      </div>

      {/* Meteorology Strip */}
      <div className="p-3.5 rounded-xl bg-slate-900/60 border border-slate-800/80 flex flex-wrap items-center justify-between gap-4 text-xs font-mono">
        <div className="flex items-center gap-2 text-slate-400">
          <Thermometer className="w-3.5 h-3.5 text-amber-400" />
          <span>Temp:</span>
          <span className="text-slate-200 font-bold">
            {reading?.temperature !== null && reading?.temperature !== undefined
              ? `${reading.temperature.toFixed(1)}°C`
              : '—'}
          </span>
        </div>

        <div className="flex items-center gap-2 text-slate-400">
          <Droplets className="w-3.5 h-3.5 text-cyan-400" />
          <span>Humidity:</span>
          <span className="text-slate-200 font-bold">
            {reading?.humidity !== null && reading?.humidity !== undefined
              ? `${reading.humidity.toFixed(1)}%`
              : '—'}
          </span>
        </div>

        <div className="flex items-center gap-2 text-slate-400">
          <Wind className="w-3.5 h-3.5 text-emerald-400" />
          <span>Wind Speed:</span>
          <span className="text-slate-200 font-bold">
            {reading?.wind_speed !== null && reading?.wind_speed !== undefined
              ? `${reading.wind_speed.toFixed(1)} m/s`
              : '—'}
          </span>
        </div>

        <div className="flex items-center gap-2 text-slate-400">
          <Compass className="w-3.5 h-3.5 text-indigo-400" />
          <span>Wind Dir:</span>
          <span className="text-slate-200 font-bold">
            {reading?.wind_direction !== null && reading?.wind_direction !== undefined
              ? `${reading.wind_direction.toFixed(0)}°`
              : '—'}
          </span>
        </div>

        <div className="flex items-center gap-2 text-slate-400">
          <Gauge className="w-3.5 h-3.5 text-rose-400" />
          <span>Pressure:</span>
          <span className="text-slate-200 font-bold">
            {reading?.pressure !== null && reading?.pressure !== undefined
              ? `${reading.pressure.toFixed(0)} hPa`
              : '—'}
          </span>
        </div>
      </div>
    </div>
  );
};

export default PollutantOverview;
