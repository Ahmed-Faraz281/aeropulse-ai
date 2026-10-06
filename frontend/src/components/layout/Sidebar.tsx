import React from 'react';
import {
  LayoutDashboard,
  MapPin,
  TrendingUp,
  Sliders,
  Bell,
  ShieldAlert,
  FileText,
  Settings,
  Cpu,
} from 'lucide-react';

export interface NavSection {
  title: string;
  items: NavItem[];
}

export interface NavItem {
  id: string;
  label: string;
  icon: React.ElementType;
  badge?: string;
  adminOnly?: boolean;
}

const NAV_SECTIONS: NavSection[] = [
  {
    title: 'Overview',
    items: [
      { id: 'dashboard', label: 'Command Center', icon: LayoutDashboard },
      { id: 'map', label: 'Spatial Map', icon: MapPin },
    ],
  },
  {
    title: 'Intelligence',
    items: [
      { id: 'predictions', label: 'ML Forecasts', icon: TrendingUp },
      { id: 'alerts', label: 'Alert Center', icon: Bell },
      { id: 'recommendations', label: 'Prevention Actions', icon: ShieldAlert },
      { id: 'whatif', label: 'What-If Simulation', icon: Sliders },
      { id: 'simulation', label: 'Sensor Simulation', icon: Cpu },
    ],
  },
  {
    title: 'Reports',
    items: [
      { id: 'reports', label: 'Environmental Reports', icon: FileText },
    ],
  },
  {
    title: 'Administration',
    items: [
      { id: 'admin', label: 'Admin Console', icon: Settings, adminOnly: true },
    ],
  },
];

interface SidebarProps {
  activeTab: string;
  onSelectTab: (tabId: string) => void;
  currentUserRole?: string;
}

export const Sidebar: React.FC<SidebarProps> = ({
  activeTab,
  onSelectTab,
  currentUserRole,
}) => {
  const isAdmin = currentUserRole === 'admin';

  return (
    <aside className="w-60 border-r border-slate-800/80 bg-slate-900/60 flex flex-col shrink-0 min-h-[calc(100vh-57px)]">
      <nav className="p-3 space-y-5 flex-1 overflow-y-auto">
        {NAV_SECTIONS.map((section) => {
          // If section only contains admin items and user is not admin, hide it
          const visibleItems = section.items.filter((item) => !item.adminOnly || isAdmin);
          if (visibleItems.length === 0) return null;

          return (
            <div key={section.title} className="space-y-1">
              <div className="px-2.5 pb-1 text-[10px] font-mono uppercase tracking-wider text-slate-500 font-bold">
                {section.title}
              </div>
              {visibleItems.map((item) => {
                const Icon = item.icon;
                const isActive = activeTab === item.id;

                return (
                  <button
                    key={item.id}
                    onClick={() => onSelectTab(item.id)}
                    className={`w-full flex items-center justify-between px-2.5 py-2 rounded-lg text-xs font-medium transition-all ${
                      isActive
                        ? 'bg-slate-800/90 text-emerald-400 border border-slate-700/80 shadow-sm'
                        : 'text-slate-400 hover:text-slate-200 hover:bg-slate-800/40'
                    }`}
                  >
                    <div className="flex items-center gap-2.5 min-w-0">
                      <Icon
                        className={`w-4 h-4 shrink-0 ${
                          isActive ? 'text-emerald-400' : 'text-slate-500'
                        }`}
                      />
                      <span className="truncate">{item.label}</span>
                    </div>
                    {item.badge && (
                      <span className="px-1.5 py-0.2 rounded text-[10px] font-mono font-semibold bg-emerald-500/10 text-emerald-400 border border-emerald-500/20">
                        {item.badge}
                      </span>
                    )}
                  </button>
                );
              })}
            </div>
          );
        })}
      </nav>

      {/* Standards Engine Info Footer */}
      <div className="p-3 border-t border-slate-800/80 bg-slate-900/90">
        <div className="flex items-center justify-between text-xs text-slate-400 mb-0.5">
          <span className="text-[11px] text-slate-500">Standard</span>
          <span className="font-semibold text-emerald-400 font-mono text-[11px]">CPCB NAQI</span>
        </div>
        <div className="text-[10px] text-slate-500 truncate">
          8 Pollutants • In-Memory Math
        </div>
      </div>
    </aside>
  );
};
