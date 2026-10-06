import React from 'react';

export type SystemStatusType =
  | 'operational'
  | 'healthy'
  | 'warning'
  | 'degraded'
  | 'offline'
  | 'checking'
  | 'loading';

export interface SystemStatusBadgeProps {
  status?: SystemStatusType | string;
  label?: string;
  className?: string;
  showDot?: boolean;
}

export const SystemStatusBadge: React.FC<SystemStatusBadgeProps> = ({
  status = 'operational',
  label,
  className = '',
  showDot = true,
}) => {
  const norm = (status || 'operational').toLowerCase();

  let defaultLabel = 'Operational';
  let dotColor = 'bg-emerald-400';
  let textColor = 'text-emerald-400';
  let badgeBg = 'bg-emerald-500/10 border-emerald-500/30';
  let pulse = false;

  if (norm.includes('health') || norm.includes('operat') || norm.includes('ok')) {
    defaultLabel = 'System Operational';
    dotColor = 'bg-emerald-400';
    textColor = 'text-emerald-300';
    badgeBg = 'bg-emerald-500/10 border-emerald-500/30';
  } else if (norm.includes('warn')) {
    defaultLabel = 'System Warning';
    dotColor = 'bg-amber-400';
    textColor = 'text-amber-300';
    badgeBg = 'bg-amber-500/10 border-amber-500/30';
  } else if (norm.includes('degrad')) {
    defaultLabel = 'Degraded Performance';
    dotColor = 'bg-orange-400';
    textColor = 'text-orange-300';
    badgeBg = 'bg-orange-500/10 border-orange-500/30';
  } else if (norm.includes('off') || norm.includes('error') || norm.includes('fail')) {
    defaultLabel = 'System Offline';
    dotColor = 'bg-rose-400';
    textColor = 'text-rose-300';
    badgeBg = 'bg-rose-500/10 border-rose-500/30';
  } else if (norm.includes('check') || norm.includes('load')) {
    defaultLabel = 'Checking Status';
    dotColor = 'bg-slate-400';
    textColor = 'text-slate-300';
    badgeBg = 'bg-slate-800 border-slate-700';
    pulse = true;
  }

  const displayText = label || defaultLabel;

  return (
    <div
      className={`inline-flex items-center gap-2 px-2.5 py-1 rounded-full text-xs font-medium border font-mono ${badgeBg} ${textColor} ${className}`}
    >
      {showDot && (
        <span
          className={`w-2 h-2 rounded-full shrink-0 ${dotColor} ${
            pulse ? 'animate-ping' : ''
          }`}
        />
      )}
      <span>{displayText}</span>
    </div>
  );
};

export default SystemStatusBadge;
