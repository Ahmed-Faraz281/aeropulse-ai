import React from 'react';
import type { DataFreshnessStatus } from '../../types/trust';
import { Clock, CheckCircle2, AlertCircle, HelpCircle } from 'lucide-react';

export interface FreshnessBadgeProps {
  status?: DataFreshnessStatus | string | null;
  ageHours?: number | null;
  className?: string;
  size?: 'sm' | 'md';
  showIcon?: boolean;
}

export const FreshnessBadge: React.FC<FreshnessBadgeProps> = ({
  status = 'UNAVAILABLE',
  ageHours,
  className = '',
  size = 'sm',
  showIcon = true,
}) => {
  const norm = (status || 'UNAVAILABLE').toUpperCase();

  let label = 'Data Unavailable';
  let styles = 'bg-slate-800 text-slate-400 border-slate-700';
  let Icon = HelpCircle;
  let dotColor = 'bg-slate-500';

  if (norm === 'FRESH') {
    label = ageHours !== undefined && ageHours !== null
      ? `Fresh (${ageHours < 1 ? '<1h' : `${Math.round(ageHours)}h`})`
      : 'Fresh Data';
    styles = 'bg-emerald-500/10 text-emerald-400 border-emerald-500/30';
    Icon = CheckCircle2;
    dotColor = 'bg-emerald-400';
  } else if (norm === 'STALE') {
    label = ageHours !== undefined && ageHours !== null
      ? `Stale (${Math.round(ageHours)}h ago)`
      : 'Delayed / Stale';
    styles = 'bg-amber-500/10 text-amber-300 border-amber-500/30';
    Icon = Clock;
    dotColor = 'bg-amber-400';
  } else {
    label = ageHours !== undefined && ageHours !== null && ageHours > 24
      ? `Unavailable (>24h)`
      : 'No Recent Data';
    styles = 'bg-slate-800/80 text-slate-400 border-slate-700';
    Icon = AlertCircle;
    dotColor = 'bg-slate-500';
  }

  const sizeClasses = size === 'sm' ? 'px-2 py-0.5 text-xs' : 'px-2.5 py-1 text-xs';

  return (
    <span
      className={`inline-flex items-center gap-1.5 font-medium rounded-full border tracking-wide uppercase font-mono ${sizeClasses} ${styles} ${className}`}
      title={label}
    >
      {showIcon ? (
        <Icon className={size === 'sm' ? 'w-3 h-3' : 'w-3.5 h-3.5'} />
      ) : (
        <span className={`w-1.5 h-1.5 rounded-full ${dotColor}`} />
      )}
      <span>{label}</span>
    </span>
  );
};

export default FreshnessBadge;
