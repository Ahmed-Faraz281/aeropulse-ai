import React from 'react';
import {
  ResponsiveContainer,
  LineChart,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  Legend,
} from 'recharts';
import type { TimeAggregatedPoint } from '../../types/analytics';
import { POLLUTANT_METADATA } from '../../utils/aqiFormatters';
import { BarChart3, Calendar } from 'lucide-react';

interface PollutantTrendChartProps {
  data: TimeAggregatedPoint[];
  isLoading: boolean;
  selectedPollutant: string;
  onSelectPollutant: (pollutant: string) => void;
  aggregation: 'hourly' | 'daily' | 'weekly';
  onAggregationChange: (agg: 'hourly' | 'daily' | 'weekly') => void;
}

interface CustomTooltipProps {
  active?: boolean;
  payload?: Array<{
    value: number;
    dataKey: string;
    payload: TimeAggregatedPoint;
  }>;
  unit: string;
}

const CustomPollutantTooltip: React.FC<CustomTooltipProps> = ({ active, payload, unit }) => {
  if (!active || !payload || !payload.length) return null;

  const item = payload[0].payload;
  const avg = item.average;
  const max = item.maximum;
  const count = item.count;
  const dateStr = new Date(item.timestamp).toLocaleString(undefined, {
    month: 'short',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  });

  return (
    <div className="p-3 rounded-xl bg-slate-900 border border-slate-700 shadow-2xl text-xs space-y-2">
      <div className="flex items-center gap-1.5 text-slate-400 font-mono text-[11px] border-b border-slate-800 pb-1.5">
        <Calendar className="w-3.5 h-3.5 text-slate-500" />
        <span>{dateStr}</span>
      </div>

      <div className="space-y-1 font-mono">
        <div className="flex items-center justify-between gap-4">
          <span className="text-slate-400">Mean Concentration:</span>
          <span className="text-white font-bold">
            {avg.toFixed(2)} {unit}
          </span>
        </div>
        <div className="flex items-center justify-between gap-4">
          <span className="text-slate-400">Peak Observed:</span>
          <span className="text-cyan-300 font-bold">
            {max.toFixed(2)} {unit}
          </span>
        </div>
        <div className="flex items-center justify-between gap-4">
          <span className="text-slate-400">Data Points:</span>
          <span className="text-slate-300">{count}</span>
        </div>
      </div>
    </div>
  );
};

export const PollutantTrendChart: React.FC<PollutantTrendChartProps> = ({
  data,
  isLoading,
  selectedPollutant,
  onSelectPollutant,
  aggregation,
  onAggregationChange,
}) => {
  const pollutantKeys = ['pm25', 'pm10', 'no2', 'so2', 'co', 'o3', 'nh3', 'pb'];
  const activeMeta = POLLUTANT_METADATA[selectedPollutant] || {
    label: selectedPollutant.toUpperCase(),
    unit: 'µg/m³',
    description: '',
  };

  const formatXAxis = (tick: string) => {
    const d = new Date(tick);
    if (aggregation === 'hourly') {
      return d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
    }
    return d.toLocaleDateString([], { month: 'short', day: 'numeric' });
  };

  return (
    <div className="p-6 rounded-2xl bg-slate-900/60 border border-slate-800 shadow-lg space-y-4">
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3">
        <div className="flex items-center gap-2">
          <div className="p-2 rounded-xl bg-cyan-500/10 text-cyan-400 border border-cyan-500/20">
            <BarChart3 className="w-4 h-4" />
          </div>
          <div>
            <h3 className="text-sm font-bold text-white uppercase tracking-wider">
              Pollutant Concentration Trend
            </h3>
            <p className="text-xs text-slate-400">
              Mean and peak levels in <span className="font-mono text-cyan-300">{activeMeta.unit}</span>
            </p>
          </div>
        </div>

        {/* Aggregation interval selector */}
        <div className="inline-flex rounded-lg bg-slate-800/80 p-1 border border-slate-700/80 self-start sm:self-auto">
          {(['hourly', 'daily', 'weekly'] as const).map((mode) => (
            <button
              key={mode}
              type="button"
              onClick={() => onAggregationChange(mode)}
              className={`px-3 py-1 rounded-md text-xs font-semibold capitalize transition ${
                aggregation === mode
                  ? 'bg-cyan-500 text-slate-950 shadow'
                  : 'text-slate-400 hover:text-white'
              }`}
            >
              {mode}
            </button>
          ))}
        </div>
      </div>

      {/* Pollutant selector pills */}
      <div className="flex flex-wrap gap-2 pt-1">
        {pollutantKeys.map((key) => {
          const meta = POLLUTANT_METADATA[key] || { label: key.toUpperCase() };
          const isSelected = selectedPollutant === key;
          return (
            <button
              key={key}
              type="button"
              onClick={() => onSelectPollutant(key)}
              className={`px-3 py-1.5 rounded-lg text-xs font-mono font-semibold border transition ${
                isSelected
                  ? 'bg-cyan-500/20 text-cyan-300 border-cyan-500/50 shadow-sm'
                  : 'bg-slate-900/80 text-slate-400 border-slate-800 hover:border-slate-700 hover:text-slate-200'
              }`}
            >
              {meta.label}
            </button>
          );
        })}
      </div>

      {isLoading ? (
        <div className="h-64 flex items-center justify-center animate-pulse">
          <div className="text-xs text-slate-500 font-mono">
            Loading {activeMeta.label} trend data...
          </div>
        </div>
      ) : data.length === 0 ? (
        <div className="h-64 flex flex-col items-center justify-center border border-dashed border-slate-800 rounded-xl bg-slate-950/40 text-center p-6 space-y-2">
          <BarChart3 className="w-8 h-8 text-slate-600" />
          <p className="text-xs text-slate-400 font-medium">
            No {activeMeta.label} records available for the selected time window.
          </p>
          <p className="text-[11px] text-slate-500">
            Missing pollutant values are kept NULL and are never replaced with zero.
          </p>
        </div>
      ) : (
        <div className="h-72 w-full pt-2">
          <ResponsiveContainer width="100%" height="100%">
            <LineChart data={data} margin={{ top: 10, right: 10, left: -20, bottom: 0 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="#1e293b" />
              <XAxis
                dataKey="timestamp"
                tickFormatter={formatXAxis}
                stroke="#64748b"
                tick={{ fill: '#64748b', fontSize: 11 }}
              />
              <YAxis
                stroke="#64748b"
                tick={{ fill: '#64748b', fontSize: 11 }}
                domain={[0, 'dataMax + 5']}
              />
              <Tooltip content={<CustomPollutantTooltip unit={activeMeta.unit} />} />
              <Legend
                verticalAlign="top"
                align="right"
                iconType="circle"
                wrapperStyle={{ paddingBottom: '12px', fontSize: '11px' }}
              />
              <Line
                type="monotone"
                dataKey="maximum"
                name={`Peak ${activeMeta.label}`}
                stroke="#38bdf8"
                strokeWidth={1.5}
                strokeDasharray="4 4"
                dot={{ r: 2, fill: '#38bdf8' }}
              />
              <Line
                type="monotone"
                dataKey="average"
                name={`Mean ${activeMeta.label}`}
                stroke="#06b6d4"
                strokeWidth={2.5}
                dot={{ r: 3, fill: '#06b6d4' }}
              />
            </LineChart>
          </ResponsiveContainer>
        </div>
      )}
    </div>
  );
};
