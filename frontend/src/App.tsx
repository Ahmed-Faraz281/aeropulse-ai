import { useState, useEffect, useCallback } from 'react';
import { Navbar } from './components/layout/Navbar';
import { Sidebar } from './components/layout/Sidebar';
import { Footer } from './components/layout/Footer';
import { LoginPage } from './components/auth/LoginPage';
import { DashboardPage } from './components/dashboard/DashboardPage';
import { MapPage } from './components/map/MapPage';
import { SimulationPage } from './components/simulation/SimulationPage';
import { PredictionPage } from './components/prediction/PredictionPage';
import { AlertsPage } from './components/alerts/AlertsPage';
import { RecommendationPage } from './components/recommendations/RecommendationPage';
import { WhatIfPage } from './components/whatif/WhatIfPage';
import { ReportsPage } from './components/reports/ReportsPage';
import { AdminPage } from './components/admin/AdminPage';
import { checkHealth, type HealthResponse } from './services/api';
import { getStoredUser, getStoredToken, logout, getMe } from './services/auth';
import type { User } from './types/auth';
import { RefreshCw, ShieldAlert, Lock } from 'lucide-react';

export function App() {
  const [activeTab, setActiveTab] = useState('dashboard');
  const [selectedLocationId, setSelectedLocationId] = useState<number | null>(null);
  const [health, setHealth] = useState<HealthResponse | null>(null);
  const [loadingHealth, setLoadingHealth] = useState(true);

  // Authentication State
  const [currentUser, setCurrentUser] = useState<User | null>(getStoredUser());
  const [checkingAuth, setCheckingAuth] = useState<boolean>(!!getStoredToken());

  const handleLogout = useCallback(async () => {
    await logout();
    setCurrentUser(null);
  }, []);

  // Validate existing session on boot
  useEffect(() => {
    let isMounted = true;

    const initApp = async () => {
      const token = getStoredToken();
      if (token) {
        try {
          const user = await getMe();
          if (isMounted) setCurrentUser(user);
        } catch {
          if (isMounted) await handleLogout();
        }
      }
      if (isMounted) {
        setCheckingAuth(false);
      }

      try {
        const data = await checkHealth();
        if (isMounted) {
          setHealth(data);
          setLoadingHealth(false);
        }
      } catch {
        if (isMounted) {
          setHealth(null);
          setLoadingHealth(false);
        }
      }
    };

    initApp();

    const handleExpired = () => {
      if (isMounted) setCurrentUser(null);
    };
    window.addEventListener('auth-session-expired', handleExpired);
    return () => {
      isMounted = false;
      window.removeEventListener('auth-session-expired', handleExpired);
    };
  }, [handleLogout]);

  // If session is being verified from local storage on first mount
  if (checkingAuth) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-slate-950 text-slate-300">
        <div className="flex items-center gap-3 text-xs font-mono">
          <RefreshCw className="w-4 h-4 animate-spin text-emerald-400" />
          <span>Initializing AeroPulse AI Command Center...</span>
        </div>
      </div>
    );
  }

  // Route Guard: Unauthenticated users redirected to LoginPage
  if (!currentUser) {
    return <LoginPage onLoginSuccess={(user) => setCurrentUser(user)} />;
  }

  const isAdmin = currentUser.role === 'admin';

  return (
    <div className="min-h-screen flex flex-col bg-slate-950 text-slate-100 selection:bg-emerald-500 selection:text-slate-950">
      <Navbar
        backendHealth={health}
        isLoading={loadingHealth}
        currentUser={currentUser}
        onLogout={handleLogout}
      />

      <div className="flex-1 flex overflow-hidden">
        <Sidebar
          activeTab={activeTab}
          onSelectTab={setActiveTab}
          currentUserRole={currentUser.role}
        />

        <main className="flex-1 overflow-y-auto p-5 space-y-5">
          {/* Active Navigation Workspace Shell */}
          {activeTab === 'dashboard' ? (
            <DashboardPage
              currentUser={currentUser}
              initialSelectedLocationId={selectedLocationId}
              onNavigateToTab={(tab) => setActiveTab(tab)}
            />
          ) : activeTab === 'map' ? (
            <MapPage
              onNavigateToDashboard={(locationId) => {
                setSelectedLocationId(locationId);
                setActiveTab('dashboard');
              }}
            />
          ) : activeTab === 'simulation' ? (
            <SimulationPage
              currentUser={currentUser}
              onNavigateToTab={(tab) => setActiveTab(tab)}
            />
          ) : activeTab === 'predictions' ? (
            <PredictionPage
              currentUser={currentUser}
              onNavigateToTab={(tab) => setActiveTab(tab)}
            />
          ) : activeTab === 'alerts' ? (
            <AlertsPage
              currentUser={currentUser}
              onNavigateToDashboard={(locationId: number) => {
                setSelectedLocationId(locationId);
                setActiveTab('dashboard');
              }}
              onNavigateToTab={(tab: string) => setActiveTab(tab)}
            />
          ) : activeTab === 'recommendations' ? (
            <RecommendationPage
              currentUser={currentUser}
              onNavigateToDashboard={(locationId: number) => {
                setSelectedLocationId(locationId);
                setActiveTab('dashboard');
              }}
              onNavigateToTab={(tab: string) => setActiveTab(tab)}
            />
          ) : activeTab === 'whatif' ? (
            <WhatIfPage
              currentUser={currentUser}
              onNavigateToDashboard={(locationId: number) => {
                setSelectedLocationId(locationId);
                setActiveTab('dashboard');
              }}
              onNavigateToTab={(tab: string) => setActiveTab(tab)}
              preselectedLocationId={selectedLocationId}
            />
          ) : activeTab === 'reports' ? (
            <ReportsPage
              currentUser={currentUser}
              initialLocationId={selectedLocationId}
              onNavigateToTab={(tab: string) => setActiveTab(tab)}
              onNavigateToDashboard={(locationId: number) => {
                setSelectedLocationId(locationId);
                setActiveTab('dashboard');
              }}
            />
          ) : activeTab === 'admin' ? (
            isAdmin ? (
              <AdminPage
                currentUser={currentUser}
                onNavigateToDashboard={(locationId: number) => {
                  setSelectedLocationId(locationId);
                  setActiveTab('dashboard');
                }}
                onNavigateToTab={(tab: string) => setActiveTab(tab)}
              />
            ) : (
              <div className="p-8 rounded-xl bg-slate-900/90 border border-slate-800/80 text-center space-y-3">
                <div className="w-12 h-12 rounded-xl bg-rose-500/10 border border-rose-500/20 text-rose-400 flex items-center justify-center mx-auto">
                  <Lock className="w-6 h-6" />
                </div>
                <h3 className="text-base font-bold text-slate-100">
                  Access Restricted
                </h3>
                <p className="text-xs text-slate-400 max-w-md mx-auto">
                  The Administration Console is restricted to administrative personnel. Your current role is <span className="font-mono text-teal-400 uppercase font-bold">{currentUser.role}</span>.
                </p>
              </div>
            )
          ) : (
            <div className="p-8 rounded-xl bg-slate-900/90 border border-slate-800/80 text-center">
              <h3 className="text-base font-bold text-slate-100">Select an item from navigation</h3>
            </div>
          )}

          {/* Software Provenance & Disclaimer Strip */}
          <div className="px-4 py-2.5 rounded-lg bg-slate-900/60 border border-slate-800/60 flex items-center gap-2.5 text-[11px] text-slate-400 font-mono">
            <ShieldAlert className="w-3.5 h-3.5 text-emerald-400 shrink-0" />
            <span>
              <strong className="text-slate-300">Software Assessment:</strong> All air-quality metrics, forecasts, and recommendations are computational estimates based on ingested feeds and mathematical models.
            </span>
          </div>
        </main>
      </div>

      <Footer />
    </div>
  );
}

export default App;
