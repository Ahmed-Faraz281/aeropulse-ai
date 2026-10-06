import React from 'react';
import { Wind, Activity, Database, LogOut, WifiOff } from 'lucide-react';
import type { User } from '../../types/auth';

interface NavbarProps {
  backendHealth: {
    status: string;
    service: string;
    version: string;
    database?: {
      status: string;
      database: string;
      ok: boolean;
    };
  } | null;
  isLoading: boolean;
  currentUser: User | null;
  onLogout: () => void;
}

export const Navbar: React.FC<NavbarProps> = ({
  backendHealth,
  isLoading,
  currentUser,
  onLogout,
}) => {
  const isHealthy = backendHealth?.status === 'healthy';

  const getRoleBadgeStyle = (role?: string) => {
    switch (role) {
      case 'admin':
        return 'bg-purple-500/10 text-purple-300 border-purple-500/30';
      case 'analyst':
        return 'bg-teal-500/10 text-teal-300 border-teal-500/30';
      default:
        return 'bg-slate-800 text-slate-300 border-slate-700';
    }
  };

  const getInitials = (name?: string) => {
    if (!name) return 'AP';
    return name.slice(0, 2).toUpperCase();
  };

  return (
    <header className="sticky top-0 z-50 border-b border-slate-800/80 bg-slate-900/95 backdrop-blur px-4 lg:px-6 py-2.5">
      <div className="flex items-center justify-between">
        {/* Brand & System Identity */}
        <div className="flex items-center gap-3">
          <div className="p-2 rounded-lg bg-gradient-to-tr from-emerald-500 to-teal-400 text-slate-950 font-bold shadow-md shadow-emerald-500/10">
            <Wind className="w-5 h-5" />
          </div>
          <div>
            <div className="flex items-center gap-2">
              <h1 className="font-bold text-base text-slate-100 tracking-tight">
                AeroPulse AI
              </h1>
              <span className="text-[10px] uppercase font-mono font-medium px-2 py-0.5 rounded bg-emerald-500/10 text-emerald-400 border border-emerald-500/20">
                Command Center
              </span>
            </div>
            <p className="text-[11px] text-slate-400 hidden sm:block">
              Intelligent Air Quality Monitoring, Prediction & Prevention
            </p>
          </div>
        </div>

        {/* System Meta & Health Status Indicators */}
        <div className="flex items-center gap-3">
          {/* Operational Status Pill */}
          <div
            className="flex items-center gap-2 px-3 py-1 rounded-md bg-slate-800/60 border border-slate-700/60 text-xs font-mono"
            title={
              backendHealth?.database
                ? `Engine: ${backendHealth.database.database} (${backendHealth.database.status})`
                : 'Backend health check'
            }
          >
            {isLoading ? (
              <span className="flex items-center gap-1.5 text-slate-400">
                <Activity className="w-3.5 h-3.5 animate-spin" />
                <span>Checking...</span>
              </span>
            ) : isHealthy ? (
              <span className="flex items-center gap-1.5 text-emerald-400">
                <span className="w-2 h-2 rounded-full bg-emerald-400 shrink-0" />
                <span className="font-medium text-slate-200">System Operational</span>
                <span className="text-slate-600 hidden sm:inline">•</span>
                <Database className="w-3 h-3 text-slate-400 hidden sm:inline" />
                <span className="text-slate-400 text-[11px] hidden sm:inline capitalize">
                  {backendHealth?.database?.database || 'DB'}
                </span>
              </span>
            ) : (
              <span className="flex items-center gap-1.5 text-rose-400">
                <WifiOff className="w-3.5 h-3.5" />
                <span>Offline</span>
              </span>
            )}
          </div>

          {/* Authenticated User Profile & Logout Action */}
          {currentUser && (
            <div className="flex items-center gap-3 pl-3 border-l border-slate-800">
              <div className="w-8 h-8 rounded-full bg-slate-800 border border-slate-700 flex items-center justify-center text-xs font-bold text-slate-200 shadow-sm">
                {getInitials(currentUser.username)}
              </div>
              <div className="hidden lg:block text-left">
                <div className="text-xs font-semibold text-slate-200">
                  {currentUser.username}
                </div>
                <div className="flex items-center gap-1.5 mt-0.5">
                  <span
                    className={`text-[9px] uppercase font-mono font-bold px-1.5 py-0.2 rounded border ${getRoleBadgeStyle(
                      currentUser.role
                    )}`}
                  >
                    {currentUser.role}
                  </span>
                </div>
              </div>
              <button
                onClick={onLogout}
                title="Sign out"
                aria-label="Sign out"
                className="p-1.5 rounded-lg text-slate-400 hover:text-rose-400 hover:bg-slate-800/80 transition"
              >
                <LogOut className="w-4 h-4" />
              </button>
            </div>
          )}
        </div>
      </div>
    </header>
  );
};
