import React from 'react';
import {
  ResponsiveContainer,
  AreaChart,
  Area,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  Legend,
} from 'recharts';
import type { TimeAggregatedPoint } from '../../types/analytics';
import { TrendingUp, Calendar } from 'lucide-react';
import { getAQICategoryStyle } from '../../utils/aqiFormatters';

interface AQITrendChartProps {
  data: TimeAggregatedPoint[];
  isLoading: boolean;
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
  label?: string;
}

const CustomAQITooltip: React.FC<CustomTooltipProps> = ({ active, payload }) => {
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

  const categoryStyle = getAQICategoryStyle(
    avg <= 50
      ? 'Good'
      : avg <= 100
      ? 'Satisfactory'
      : avg <= 200
      ? 'Moderate'
      : avg <= 300
      ? 'Poor'
      : avg <= 400
      ? 'Very Poor'
      : 'Severe'
  );

  return (
    <div className="p-3 rounded-xl bg-slate-900 border border-slate-700 shadow-2xl text-xs space-y-2">
      <div className="flex items-center gap-1.5 text-slate-400 font-mono text-[11px] border-b border-slate-800 pb-1.5">
        <Calendar className="w-3.5 h-3.5 text-slate-500" />
        <span>{dateStr}</span>
      </div>

      <div className="space-y-1 font-mono">
        <div className="flex items-center justify-between gap-4">
          <span className="text-slate-400">Average AQI:</span>
          <span className="text-white font-bold">{avg.toFixed(1)}</span>
        </div>
        <div className="flex items-center justify-between gap-4">
          <span className="text-slate-400">Peak AQI:</span>
          <span className="text-amber-300 font-bold">{max.toFixed(1)}</span>
        </div>
        <div className="flex items-center justify-between gap-4">
          <span className="text-slate-400">Data Points:</span>
          <span className="text-slate-300">{count}</span>
        </div>
      </div>

      <div
        className={`px-2 py-0.5 rounded text-[10px] font-bold border inline-block ${categoryStyle.bg} ${categoryStyle.text} ${categoryStyle.border}`}
      >
        {categoryStyle.label}
      </div>
    </div>
  );
};

export const AQITrendChart: React.FC<AQITrendChartProps> = ({
  data,
  isLoading,
  aggregation,
  onAggregationChange,
}) => {
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
          <div className="p-2 rounded-xl bg-teal-500/10 text-teal-400 border border-teal-500/20">
            <TrendingUp className="w-4 h-4" />
          </div>
          <div>
            <h3 className="text-sm font-bold text-white uppercase tracking-wider">
              AQI Temporal Trend
            </h3>
            <p className="text-xs text-slate-400">
              Aggregated Air Quality Index over time
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
                  ? 'bg-teal-500 text-slate-950 shadow'
                  : 'text-slate-400 hover:text-white'
              }`}
            >
              {mode}
            </button>
          ))}
        </div>
      </div>

      {isLoading ? (
        <div className="h-64 flex items-center justify-center animate-pulse">
          <div className="text-xs text-slate-500 font-mono">Loading AQI trend data...</div>
        </div>
      ) : data.length === 0 ? (
        <div className="h-64 flex flex-col items-center justify-center border border-dashed border-slate-800 rounded-xl bg-slate-950/40 text-center p-6 space-y-2">
          <TrendingUp className="w-8 h-8 text-slate-600" />
          <p className="text-xs text-slate-400 font-medium">
            No AQI trend records available for the selected time window.
          </p>
          <p className="text-[11px] text-slate-500">
            Ingest air quality readings or select a wider historical range.
          </p>
        </div>
      ) : (
        <div className="h-72 w-full pt-2">
          <ResponsiveContainer width="100%" height="100%">
            <AreaChart data={data} margin={{ top: 10, right: 10, left: -20, bottom: 0 }}>
              <defs>
                <linearGradient id="aqiAvgGrad" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="5%" stopColor="#14b8a6" stopOpacity={0.4} />
                  <stop offset="95%" stopColor="#14b8a6" stopOpacity={0.0} />
                </linearGradient>
                <linearGradient id="aqiMaxGrad" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="5%" stopColor="#f59e0b" stopOpacity={0.2} />
                  <stop offset="95%" stopColor="#f59e0b" stopOpacity={0.0} />
                </linearGradient>
              </defs>
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
                domain={[0, 'dataMax + 20']}
              />
              <Tooltip content={<CustomAQITooltip />} />
              <Legend
                verticalAlign="top"
                align="right"
                iconType="circle"
                wrapperStyle={{ paddingBottom: '12px', fontSize: '11px' }}
              />
              <Area
                type="monotone"
                dataKey="maximum"
                name="Peak AQI"
                stroke="#f59e0b"
                strokeWidth={1.5}
                strokeDasharray="4 4"
                fillOpacity={1}
                fill="url(#aqiMaxGrad)"
              />
              <Area
                type="monotone"
                dataKey="average"
                name="Average AQI"
                stroke="#14b8a6"
                strokeWidth={2.5}
                fillOpacity={1}
                fill="url(#aqiAvgGrad)"
              />
            </AreaChart>
          </ResponsiveContainer>
        </div>
      )}
    </div>
  );
};
