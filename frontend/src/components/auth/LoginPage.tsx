import React, { useState } from 'react';
import { Wind, Lock, User as UserIcon, ShieldAlert, ArrowRight, Loader2 } from 'lucide-react';
import { login } from '../../services/auth';
import type { User, UserRole } from '../../types/auth';

interface LoginPageProps {
  onLoginSuccess: (user: User) => void;
}

export const LoginPage: React.FC<LoginPageProps> = ({ onLoginSuccess }) => {
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [isLoading, setIsLoading] = useState(false);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!username.trim() || !password) {
      setError('Please enter both username/email and password.');
      return;
    }

    setError(null);
    setIsLoading(true);

    try {
      const response = await login({ username: username.trim(), password });
      onLoginSuccess(response.user);
    } catch (err: unknown) {
      const errorObj = err as { response?: { data?: { detail?: string } } };
      const detail = errorObj.response?.data?.detail;
      setError(
        detail || 'Authentication failed. Please verify your credentials and ensure the backend is running.'
      );
    } finally {
      setIsLoading(false);
    }
  };

  const handleQuickFill = (role: UserRole) => {
    if (role === 'admin') {
      setUsername('admin');
      setPassword('Admin@12345');
    } else if (role === 'analyst') {
      setUsername('analyst');
      setPassword('Analyst@12345');
    } else {
      setUsername('viewer');
      setPassword('Viewer@12345');
    }
    setError(null);
  };

  return (
    <div className="min-h-screen flex flex-col justify-center items-center bg-slate-950 px-4 py-8 relative overflow-hidden">
      {/* Restrained ambient background tint */}
      <div className="absolute top-1/4 left-1/2 -translate-x-1/2 -translate-y-1/2 w-96 h-96 bg-emerald-500/5 rounded-full blur-3xl pointer-events-none" />

      <div className="w-full max-w-md relative z-10 space-y-6">
        {/* Brand header */}
        <div className="text-center space-y-2">
          <div className="inline-flex p-3 rounded-xl bg-gradient-to-tr from-emerald-500 to-teal-400 text-slate-950 font-bold shadow-lg shadow-emerald-500/10 mb-2">
            <Wind className="w-7 h-7" />
          </div>
          <h1 className="text-2xl font-bold tracking-tight text-slate-100">
            AeroPulse AI
          </h1>
          <p className="text-xs text-slate-400">
            Intelligent Air Quality Monitoring, Prediction & Prevention System
          </p>
        </div>

        {/* Login Form Container */}
        <div className="p-6 sm:p-7 rounded-xl bg-slate-900/90 border border-slate-800/80 shadow-2xl space-y-5">
          <div>
            <h2 className="text-base font-semibold text-slate-100">Command Center Login</h2>
            <p className="text-xs text-slate-400 mt-0.5">
              Enter your credentials to access environmental telemetry & intelligence
            </p>
          </div>

          {error && (
            <div className="p-3 rounded-lg bg-rose-500/10 border border-rose-500/20 text-rose-300 text-xs flex items-start gap-2.5">
              <ShieldAlert className="w-4 h-4 text-rose-400 shrink-0 mt-0.5" />
              <span>{error}</span>
            </div>
          )}

          <form onSubmit={handleSubmit} className="space-y-4">
            <div className="space-y-1.5">
              <label className="text-xs font-medium text-slate-300 block">
                Username or Email
              </label>
              <div className="relative">
                <UserIcon className="w-4 h-4 text-slate-500 absolute left-3.5 top-3 pointer-events-none" />
                <input
                  type="text"
                  value={username}
                  onChange={(e) => setUsername(e.target.value)}
                  placeholder="admin, analyst, or viewer"
                  className="w-full pl-10 pr-4 py-2 rounded-lg bg-slate-800/80 border border-slate-700/80 text-slate-100 placeholder-slate-500 text-xs focus:outline-none focus:border-emerald-500 focus:ring-1 focus:ring-emerald-500 transition font-mono"
                  disabled={isLoading}
                />
              </div>
            </div>

            <div className="space-y-1.5">
              <label className="text-xs font-medium text-slate-300 block">
                Password
              </label>
              <div className="relative">
                <Lock className="w-4 h-4 text-slate-500 absolute left-3.5 top-3 pointer-events-none" />
                <input
                  type="password"
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  placeholder="••••••••"
                  className="w-full pl-10 pr-4 py-2 rounded-lg bg-slate-800/80 border border-slate-700/80 text-slate-100 placeholder-slate-500 text-xs focus:outline-none focus:border-emerald-500 focus:ring-1 focus:ring-emerald-500 transition"
                  disabled={isLoading}
                />
              </div>
            </div>

            <button
              type="submit"
              disabled={isLoading}
              className="w-full flex items-center justify-center gap-2 py-2 px-4 rounded-lg bg-emerald-500 hover:bg-emerald-400 text-slate-950 font-bold text-xs shadow-md shadow-emerald-500/10 transition disabled:opacity-50 mt-2"
            >
              {isLoading ? (
                <>
                  <Loader2 className="w-4 h-4 animate-spin" />
                  <span>Authenticating...</span>
                </>
              ) : (
                <>
                  <span>Sign In</span>
                  <ArrowRight className="w-3.5 h-3.5" />
                </>
              )}
            </button>
          </form>

          {/* Quick-fill Demo Accounts */}
          <div className="pt-4 border-t border-slate-800/80 space-y-2">
            <div className="flex items-center justify-between text-[11px] text-slate-400">
              <span className="font-semibold text-slate-300">
                Demo Accounts:
              </span>
              <span className="text-[10px] text-slate-500 font-mono">Click to select role</span>
            </div>

            <div className="grid grid-cols-3 gap-2">
              <button
                type="button"
                onClick={() => handleQuickFill('admin')}
                className="px-2.5 py-1.5 rounded-lg bg-slate-800 hover:bg-slate-750 hover:border-slate-600 text-slate-200 border border-slate-700 text-xs font-mono transition text-center"
              >
                admin
              </button>
              <button
                type="button"
                onClick={() => handleQuickFill('analyst')}
                className="px-2.5 py-1.5 rounded-lg bg-slate-800 hover:bg-slate-750 hover:border-slate-600 text-slate-200 border border-slate-700 text-xs font-mono transition text-center"
              >
                analyst
              </button>
              <button
                type="button"
                onClick={() => handleQuickFill('viewer')}
                className="px-2.5 py-1.5 rounded-lg bg-slate-800 hover:bg-slate-750 hover:border-slate-600 text-slate-200 border border-slate-700 text-xs font-mono transition text-center"
              >
                viewer
              </button>
            </div>
            <p className="text-[10px] text-slate-500 italic text-center">
              Pre-seeded accounts for demonstration. Role-Based Access Control enforced.
            </p>
          </div>
        </div>

        {/* Security & Provenance Banner */}
        <div className="text-center space-y-1">
          <p className="text-[11px] text-slate-500 font-mono">
            JWT Authentication • CPCB Indian NAQI Calculations
          </p>
        </div>
      </div>
    </div>
  );
};

export default LoginPage;
