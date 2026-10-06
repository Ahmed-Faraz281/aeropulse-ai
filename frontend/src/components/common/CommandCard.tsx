import React from 'react';

export interface CommandCardProps {
  title?: React.ReactNode;
  subtitle?: React.ReactNode;
  icon?: React.ComponentType<{ className?: string }>;
  action?: React.ReactNode;
  className?: string;
  headerClassName?: string;
  bodyClassName?: string;
  glow?: 'emerald' | 'cyan' | 'amber' | 'rose' | 'none';
  children: React.ReactNode;
}

export const CommandCard: React.FC<CommandCardProps> = ({
  title,
  subtitle,
  icon: Icon,
  action,
  className = '',
  headerClassName = '',
  bodyClassName = '',
  glow = 'none',
  children,
}) => {
  const glowClasses = {
    emerald: 'relative before:absolute before:inset-0 before:-z-10 before:rounded-xl before:bg-gradient-to-b before:from-emerald-500/10 before:to-transparent before:opacity-50',
    cyan: 'relative before:absolute before:inset-0 before:-z-10 before:rounded-xl before:bg-gradient-to-b before:from-cyan-500/10 before:to-transparent before:opacity-50',
    amber: 'relative before:absolute before:inset-0 before:-z-10 before:rounded-xl before:bg-gradient-to-b before:from-amber-500/10 before:to-transparent before:opacity-50',
    rose: 'relative before:absolute before:inset-0 before:-z-10 before:rounded-xl before:bg-gradient-to-b before:from-rose-500/10 before:to-transparent before:opacity-50',
    none: '',
  }[glow];

  const hasHeader = title || subtitle || Icon || action;

  return (
    <div
      className={`bg-slate-900/90 border border-slate-800/80 rounded-xl shadow-lg shadow-black/20 transition-all duration-150 ease-out hover:border-slate-700/80 ${glowClasses} ${className}`}
    >
      {hasHeader && (
        <div
          className={`px-5 py-4 border-b border-slate-800/60 flex items-center justify-between gap-4 ${headerClassName}`}
        >
          <div className="flex items-center gap-3 min-w-0">
            {Icon && (
              <div className="p-2 rounded-lg bg-slate-800/80 border border-slate-700/50 text-slate-300 shrink-0">
                <Icon className="w-4 h-4" />
              </div>
            )}
            <div className="min-w-0">
              {title && (
                <div className="text-sm font-semibold text-slate-100 tracking-tight truncate">
                  {title}
                </div>
              )}
              {subtitle && (
                <div className="text-xs text-slate-400 mt-0.5 truncate">{subtitle}</div>
              )}
            </div>
          </div>
          {action && <div className="shrink-0 flex items-center gap-2">{action}</div>}
        </div>
      )}
      <div className={`p-5 ${bodyClassName}`}>{children}</div>
    </div>
  );
};

export default CommandCard;
