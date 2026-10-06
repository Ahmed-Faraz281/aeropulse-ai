import React from 'react';
import { getAQICategoryStyle } from '../../utils/aqiFormatters';
import type { AQICategory } from '../../types/aqi';

interface LegendItem {
  category: AQICategory;
  range: string;
  description: string;
}

const LEGEND_ITEMS: LegendItem[] = [
  { category: 'Good', range: '0–50', description: 'Minimal health impact' },
  { category: 'Satisfactory', range: '51–100', description: 'Minor breathing discomfort to sensitive people' },
  { category: 'Moderate', range: '101–200', description: 'Breathing discomfort to people with lungs/asthma' },
  { category: 'Poor', range: '201–300', description: 'Breathing discomfort to most people on prolonged exposure' },
  { category: 'Very Poor', range: '301–400', description: 'Respiratory illness on prolonged exposure' },
  { category: 'Severe', range: '401–500', description: 'Affects healthy people and seriously impacts sensitive groups' },
];

export const MapLegend: React.FC = () => {
  return (
    <div className="p-4 rounded-xl bg-slate-900/90 border border-slate-800 shadow-xl space-y-3">
      <div className="flex items-center justify-between border-b border-slate-800 pb-2">
        <h4 className="text-xs font-bold uppercase tracking-wider text-slate-300">
          CPCB NAQI Index Scale
        </h4>
        <span className="text-[10px] text-slate-500 font-mono">India Standard</span>
      </div>

      <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-6 gap-2">
        {LEGEND_ITEMS.map((item) => {
          const style = getAQICategoryStyle(item.category);
          return (
            <div
              key={item.category}
              className={`p-2 rounded-lg border ${style.bg} ${style.border} flex flex-col justify-between space-y-1`}
            >
              <div className="flex items-center gap-1.5">
                <span className={`w-2 h-2 rounded-full ${style.dot} shrink-0`} />
                <span className={`text-[11px] font-bold ${style.text}`}>{item.category}</span>
              </div>
              <div className="text-xs font-mono font-extrabold text-white">{item.range}</div>
              <p className="text-[9px] text-slate-400 leading-tight truncate">{item.description}</p>
            </div>
          );
        })}
      </div>
    </div>
  );
};
