import React from 'react';
import { ShieldCheck, Cpu } from 'lucide-react';

export const Footer: React.FC = () => {
  return (
    <footer className="border-t border-slate-800/80 bg-slate-950/80 px-6 py-3 text-xs text-slate-400">
      <div className="flex flex-col sm:flex-row items-center justify-between gap-3">
        <div className="flex items-center gap-2 text-slate-400">
          <ShieldCheck className="w-4 h-4 text-emerald-400 shrink-0" />
          <span className="text-[11px] text-slate-400">
            AeroPulse AI provides computational air-quality assessments based on available monitoring datasets and algorithmic simulations. Not a physical sensor hardware device.
          </span>
        </div>
        <div className="flex items-center gap-4 text-[11px] text-slate-500 font-mono shrink-0">
          <span className="flex items-center gap-1.5">
            <Cpu className="w-3.5 h-3.5 text-cyan-400" />
            <span>FastAPI • CPCB NAQI Engine</span>
          </span>
          <span className="text-slate-600">|</span>
          <span>v1.0.0</span>
        </div>
      </div>
    </footer>
  );
};
