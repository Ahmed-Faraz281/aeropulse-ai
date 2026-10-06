import React from 'react';

export type ProvenanceType =
  | 'API'
  | 'UPLOAD'
  | 'UPLOADED'
  | 'SIMULATED'
  | 'PREDICTED'
  | 'FORECAST'
  | 'WHAT_IF'
  | 'DEMO'
  | string;

export interface ProvenanceBadgeProps {
  sourceType?: ProvenanceType | null;
  className?: string;
  size?: 'sm' | 'md';
}

export const ProvenanceBadge: React.FC<ProvenanceBadgeProps> = ({
  sourceType,
  className = '',
  size = 'sm',
}) => {
  const norm = (sourceType || '').toUpperCase();

  let label = 'Unverified Data';
  let styles = 'bg-slate-800 text-slate-400 border-slate-700';
  let dotColor = 'bg-slate-400';

  if (norm.includes('SIMULAT')) {
    label = 'Simulated — Not an Actual Measurement';
    styles = 'bg-amber-500/10 text-amber-300 border-amber-500/30';
    dotColor = 'bg-amber-400';
  } else if (norm.includes('PREDICT') || norm.includes('FORECAST')) {
    label = 'Forecast — Not Current Observation';
    styles = 'bg-sky-500/10 text-sky-300 border-sky-500/30';
    dotColor = 'bg-sky-400';
  } else if (norm.includes('WHAT_IF')) {
    label = 'Hypothetical What-If Simulation';
    styles = 'bg-amber-500/10 text-amber-300 border-amber-500/30';
    dotColor = 'bg-amber-400';
  } else if (norm === 'API') {
    label = 'Live Telemetry';
    styles = 'bg-emerald-500/10 text-emerald-300 border-emerald-500/30';
    dotColor = 'bg-emerald-400';
  } else if (norm.includes('UPLOAD')) {
    label = 'Uploaded Dataset';
    styles = 'bg-teal-500/10 text-teal-300 border-teal-500/30';
    dotColor = 'bg-teal-400';
  } else if (norm.includes('DEMO')) {
    label = 'Demo Dataset';
    styles = 'bg-slate-800 text-slate-300 border-slate-700';
    dotColor = 'bg-slate-400';
  }

  const sizeClasses = size === 'sm' ? 'px-2 py-0.5 text-xs' : 'px-2.5 py-1 text-xs';

  return (
    <span
      className={`inline-flex items-center gap-1.5 font-medium border rounded-md font-mono ${styles} ${sizeClasses} ${className}`}
      title={`Data Provenance: ${label}`}
    >
      <span className={`w-1.5 h-1.5 rounded-full shrink-0 ${dotColor}`} />
      <span>{label}</span>
    </span>
  );
};

export default ProvenanceBadge;
