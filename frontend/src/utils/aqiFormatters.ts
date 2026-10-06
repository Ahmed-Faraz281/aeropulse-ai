import type { AQICategory } from '../types/aqi';

export interface AQICategoryStyle {
  label: string;
  bg: string;
  text: string;
  border: string;
  dot: string;
  hex: string;
}

export const getAQICategoryStyle = (category?: AQICategory | string | null): AQICategoryStyle => {
  switch (category) {
    case 'Good':
      return {
        label: 'Good',
        bg: 'bg-emerald-500/10',
        text: 'text-emerald-400',
        border: 'border-emerald-500/30',
        dot: 'bg-emerald-500',
        hex: '#10b981',
      };
    case 'Satisfactory':
      return {
        label: 'Satisfactory',
        bg: 'bg-lime-500/10',
        text: 'text-lime-400',
        border: 'border-lime-500/30',
        dot: 'bg-lime-500',
        hex: '#84cc16',
      };
    case 'Moderate':
      return {
        label: 'Moderate',
        bg: 'bg-amber-500/10',
        text: 'text-amber-400',
        border: 'border-amber-500/30',
        dot: 'bg-amber-500',
        hex: '#f59e0b',
      };
    case 'Poor':
      return {
        label: 'Poor',
        bg: 'bg-orange-500/10',
        text: 'text-orange-400',
        border: 'border-orange-500/30',
        dot: 'bg-orange-500',
        hex: '#f97316',
      };
    case 'Very Poor':
      return {
        label: 'Very Poor',
        bg: 'bg-rose-500/10',
        text: 'text-rose-400',
        border: 'border-rose-500/30',
        dot: 'bg-rose-500',
        hex: '#ef4444',
      };
    case 'Severe':
      return {
        label: 'Severe',
        bg: 'bg-purple-500/10',
        text: 'text-purple-400',
        border: 'border-purple-500/30',
        dot: 'bg-purple-500',
        hex: '#a855f7',
      };
    default:
      return {
        label: 'Unavailable',
        bg: 'bg-slate-800/50',
        text: 'text-slate-400',
        border: 'border-slate-700',
        dot: 'bg-slate-500',
        hex: '#64748b',
      };
  }
};

export const POLLUTANT_METADATA: Record<
  string,
  { label: string; unit: string; description: string }
> = {
  pm25: { label: 'PM2.5', unit: 'µg/m³', description: 'Fine Inhalable Particles' },
  pm10: { label: 'PM10', unit: 'µg/m³', description: 'Coarse Inhalable Particles' },
  no2: { label: 'NO2', unit: 'µg/m³', description: 'Nitrogen Dioxide' },
  so2: { label: 'SO2', unit: 'µg/m³', description: 'Sulfur Dioxide' },
  co: { label: 'CO', unit: 'mg/m³', description: 'Carbon Monoxide' },
  o3: { label: 'O3', unit: 'µg/m³', description: 'Ground-level Ozone' },
  nh3: { label: 'NH3', unit: 'µg/m³', description: 'Ammonia' },
  pb: { label: 'Pb', unit: 'µg/m³', description: 'Lead' },
};
