import React from 'react';
import { POLLUTANT_METADATA, getAQICategoryStyle } from '../../utils/aqiFormatters';
import type { AQICategory } from '../../types/aqi';

export interface PollutantPillCardProps {
  code: string;
  concentration?: number | null;
  subIndex?: number | null;
  category?: AQICategory | string | null;
  className?: string;
}

export const PollutantPillCard: React.FC<PollutantPillCardProps> = ({
  code,
  concentration,
  subIndex,
  category,
  className = '',
}) => {
  const normKey = code.toLowerCase().replace('.', '');
  const meta = POLLUTANT_METADATA[normKey] || {
    label: code.toUpperCase(),
    unit: 'µg/m³',
    description: 'Pollutant',
  };

  const isAvailable =
    concentration !== null && concentration !== undefined && !Number.isNaN(concentration);

  const catStyle = getAQICategoryStyle(category);

  return (
    <div
      className={`p-3.5 rounded-lg bg-slate-900/70 border border-slate-800/80 hover:border-slate-700/80 transition-all flex flex-col justify-between min-h-[96px] ${className}`}
    >
      <div className="flex items-center justify-between gap-2">
        <span className="font-semibold text-xs text-slate-200 tracking-wide">
          {meta.label}
        </span>
        {isAvailable && subIndex !== null && subIndex !== undefined ? (
          <span
            className={`px-1.5 py-0.5 rounded text-[10px] font-mono font-medium border ${catStyle.bg} ${catStyle.text} ${catStyle.border}`}
            title={`Sub-index: ${Math.round(subIndex)} (${catStyle.label})`}
          >
            Sub {Math.round(subIndex)}
          </span>
        ) : (
          <span className="text-[10px] text-slate-500 font-mono">
            {meta.unit}
          </span>
        )}
      </div>

      <div className="mt-2">
        {isAvailable ? (
          <div className="flex items-baseline gap-1.5">
            <span className="text-xl font-bold font-mono tracking-tight text-slate-100">
              {normKey === 'co' ? concentration.toFixed(2) : concentration.toFixed(1)}
            </span>
            <span className="text-[11px] text-slate-400 font-mono">
              {meta.unit}
            </span>
          </div>
        ) : (
          <div className="flex items-baseline gap-1.5">
            <span className="text-xl font-bold font-mono tracking-tight text-slate-600">
              —
            </span>
            <span className="text-[10px] text-slate-500 italic">
              Not Monitored
            </span>
          </div>
        )}
      </div>

      <div className="text-[10px] text-slate-500 truncate mt-1">
        {meta.description}
      </div>
    </div>
  );
};

export default PollutantPillCard;
