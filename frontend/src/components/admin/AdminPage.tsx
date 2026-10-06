import React, { useState, useEffect, useCallback } from 'react';
import type { User, UserRole } from '../../types/auth';
import type { Location, DataSource, SourceType } from '../../types/air_quality';
import type { AlertRule } from '../../types/alert';
import type {
  AdminOverviewResponse,
  SystemSetting,
  AuditLog,
} from '../../types/admin';
import {
  getAdminOverview,
  listUsers,
  createUserAdmin,
  updateUserAdmin,
  listAuditLogs,
  getSystemSettings,
  updateSystemSetting,
  createLocation,
  updateLocation,
  createDataSource,
  updateDataSource,
} from '../../services/admin';
import { getLocations, getDataSources } from '../../services/air_quality';
import { getAlertRules, updateAlertRule, deleteAlertRule } from '../../services/alert';
import {
  getAutomationStatus,
  triggerAutomationCycle,
  pauseAutomationScheduler,
  resumeAutomationScheduler,
} from '../../services/automation';
import type { AutomationStatusResponse } from '../../types/automation';
import { getSystemTrustOverview } from '../../services/trust';
import type { SystemTrustOverview } from '../../types/trust';
import {
  ShieldAlert,
  ShieldCheck,
  Users,
  FileText,
  MapPin,
  Radio,
  Bell,
  Activity,
  Plus,
  Edit2,
  RefreshCw,
  Search,
  CheckCircle2,
  AlertTriangle,
  Server,
  Lock,
  Eye,
  ChevronLeft,
  ChevronRight,
  Sliders,
  Play,
  Pause,
} from 'lucide-react';


interface AdminPageProps {
  currentUser: User;
  onNavigateToDashboard?: (locationId: number) => void;
  onNavigateToTab?: (tabId: string) => void;
}

type AdminTab =
  | 'overview'
  | 'users'
  | 'locations'
  | 'data-sources'
  | 'alert-rules'
  | 'settings'
  | 'audit';

export const AdminPage: React.FC<AdminPageProps> = ({
  currentUser,
  onNavigateToTab,
}) => {
  const isAdmin = currentUser.role === 'admin';

  // Navigation sub-tab
  const [activeTab, setActiveTab] = useState<AdminTab>('overview');

  // Overview state
  const [overview, setOverview] = useState<AdminOverviewResponse | null>(null);
  const [loadingOverview, setLoadingOverview] = useState(false);

  // Users state
  const [users, setUsers] = useState<User[]>([]);
  const [usersTotal, setUsersTotal] = useState(0);
  const [usersPage, setUsersPage] = useState(1);
  const [usersRoleFilter, setUsersRoleFilter] = useState<string>('');
  const [usersSearch, setUsersSearch] = useState('');
  const [loadingUsers, setLoadingUsers] = useState(false);
  const [showAddUserModal, setShowAddUserModal] = useState(false);
  const [showEditUserModal, setShowEditUserModal] = useState(false);
  const [selectedUser, setSelectedUser] = useState<User | null>(null);

  // New user form state
  const [newUsername, setNewUsername] = useState('');
  const [newEmail, setNewEmail] = useState('');
  const [newPassword, setNewPassword] = useState('');
  const [newRole, setNewRole] = useState<UserRole>('viewer');

  // Edit user form state
  const [editRole, setEditRole] = useState<UserRole>('viewer');
  const [editIsActive, setEditIsActive] = useState(true);

  // Locations state
  const [locations, setLocations] = useState<Location[]>([]);
  const [loadingLocations, setLoadingLocations] = useState(false);
  const [showAddLocationModal, setShowAddLocationModal] = useState(false);
  const [locName, setLocName] = useState('');
  const [locCity, setLocCity] = useState('');
  const [locState, setLocState] = useState('');
  const [locCountry] = useState('India');
  const [locLat, setLocLat] = useState('28.6139');
  const [locLon, setLocLon] = useState('77.2090');
  const [locDesc, setLocDesc] = useState('');

  // Data Sources state
  const [dataSources, setDataSources] = useState<DataSource[]>([]);
  const [loadingDataSources, setLoadingDataSources] = useState(false);
  const [showAddSourceModal, setShowAddSourceModal] = useState(false);
  const [dsName, setDsName] = useState('');
  const [dsType, setDsType] = useState<SourceType>('API');
  const [dsProvider, setDsProvider] = useState('');
  const [dsDesc, setDsDesc] = useState('');

  // Alert Rules state
  const [alertRules, setAlertRules] = useState<AlertRule[]>([]);
  const [loadingAlertRules, setLoadingAlertRules] = useState(false);

  // System Settings state
  const [settings, setSettings] = useState<SystemSetting[]>([]);
  const [loadingSettings, setLoadingSettings] = useState(false);
  const [settingCategoryFilter, setSettingCategoryFilter] = useState<string>('');
  const [editingSetting, setEditingSetting] = useState<SystemSetting | null>(null);
  const [settingValueInput, setSettingValueInput] = useState('');

  // Audit Logs state
  const [auditLogs, setAuditLogs] = useState<AuditLog[]>([]);
  const [auditTotal, setAuditTotal] = useState(0);
  const [auditPage, setAuditPage] = useState(1);
  const [auditActionFilter, setAuditActionFilter] = useState('');
  const [auditResourceFilter, setAuditResourceFilter] = useState('');
  const [loadingAudit, setLoadingAudit] = useState(false);
  const [selectedAuditLog, setSelectedAuditLog] = useState<AuditLog | null>(null);

  // Feedback notifications
  const [notification, setNotification] = useState<{ type: 'success' | 'error'; message: string } | null>(null);

  const showFeedback = (type: 'success' | 'error', message: string) => {
    setNotification({ type, message });
    setTimeout(() => {
      setNotification(null);
    }, 5000);
  };

  // Automation State (Phase 18)
  const [automationStatus, setAutomationStatus] = useState<AutomationStatusResponse | null>(null);
  const [loadingAutomation, setLoadingAutomation] = useState(false);
  const [triggeringSync, setTriggeringSync] = useState(false);

  // Trust Layer State (Phase 19)
  const [trustOverview, setTrustOverview] = useState<SystemTrustOverview | null>(null);

  // 1. Fetch Overview
  const fetchOverview = useCallback(async () => {
    if (!isAdmin) return;
    setLoadingOverview(true);
    try {
      const [data, trustData] = await Promise.all([
        getAdminOverview(),
        getSystemTrustOverview().catch(() => null),
      ]);
      setOverview(data);
      if (trustData) {
        setTrustOverview(trustData);
      }
    } catch (err: any) {
      showFeedback('error', err.response?.data?.detail || 'Failed to load system overview');
    } finally {
      setLoadingOverview(false);
    }
  }, [isAdmin]);

  const fetchAutomation = useCallback(async () => {
    setLoadingAutomation(true);
    try {
      const data = await getAutomationStatus();
      setAutomationStatus(data);
    } catch {
      // Non-blocking
    } finally {
      setLoadingAutomation(false);
    }
  }, []);

  const handleTriggerSync = async () => {
    setTriggeringSync(true);
    try {
      const res = await triggerAutomationCycle();
      showFeedback('success', res.message || 'Automation sync cycle initiated.');
      setTimeout(fetchAutomation, 1500);
    } catch (err: any) {
      showFeedback('error', err.response?.data?.detail || 'Failed to trigger automation sync.');
    } finally {
      setTriggeringSync(false);
    }
  };

  const handleTogglePause = async () => {
    if (!automationStatus) return;
    try {
      if (automationStatus.paused) {
        await resumeAutomationScheduler();
        showFeedback('success', 'Automation scheduler resumed.');
      } else {
        await pauseAutomationScheduler();
        showFeedback('success', 'Automation scheduler paused.');
      }
      fetchAutomation();
    } catch (err: any) {
      showFeedback('error', err.response?.data?.detail || 'Failed to update scheduler state.');
    }
  };


  // 2. Fetch Users
  const fetchUsers = useCallback(async () => {
    if (!isAdmin) return;
    setLoadingUsers(true);
    try {
      const data = await listUsers({
        page: usersPage,
        page_size: 10,
        role: (usersRoleFilter || undefined) as UserRole | undefined,
        search: usersSearch || undefined,
      });
      setUsers(data.items);
      setUsersTotal(data.total);
    } catch (err: any) {
      showFeedback('error', err.response?.data?.detail || 'Failed to load user directory');
    } finally {
      setLoadingUsers(false);
    }
  }, [isAdmin, usersPage, usersRoleFilter, usersSearch]);

  // 3. Fetch Locations
  const fetchLocationsList = useCallback(async () => {
    if (!isAdmin) return;
    setLoadingLocations(true);
    try {
      const data = await getLocations();
      setLocations(data);
    } catch (err: any) {
      showFeedback('error', err.response?.data?.detail || 'Failed to load locations');
    } finally {
      setLoadingLocations(false);
    }
  }, [isAdmin]);

  // 4. Fetch Data Sources
  const fetchDataSourcesList = useCallback(async () => {
    if (!isAdmin) return;
    setLoadingDataSources(true);
    try {
      const data = await getDataSources();
      setDataSources(data);
    } catch (err: any) {
      showFeedback('error', err.response?.data?.detail || 'Failed to load data sources');
    } finally {
      setLoadingDataSources(false);
    }
  }, [isAdmin]);

  // 5. Fetch Alert Rules
  const fetchAlertRulesList = useCallback(async () => {
    if (!isAdmin) return;
    setLoadingAlertRules(true);
    try {
      const data = await getAlertRules();
      setAlertRules(data);
    } catch (err: any) {
      showFeedback('error', err.response?.data?.detail || 'Failed to load alert rules');
    } finally {
      setLoadingAlertRules(false);
    }
  }, [isAdmin]);

  // 6. Fetch System Settings
  const fetchSettingsList = useCallback(async () => {
    if (!isAdmin) return;
    setLoadingSettings(true);
    try {
      const data = await getSystemSettings(settingCategoryFilter || undefined);
      setSettings(data);
    } catch (err: any) {
      showFeedback('error', err.response?.data?.detail || 'Failed to load system settings');
    } finally {
      setLoadingSettings(false);
    }
  }, [isAdmin, settingCategoryFilter]);

  // 7. Fetch Audit Logs
  const fetchAuditLogsList = useCallback(async () => {
    if (!isAdmin) return;
    setLoadingAudit(true);
    try {
      const data = await listAuditLogs({
        page: auditPage,
        page_size: 15,
        action: auditActionFilter || undefined,
        resource_type: auditResourceFilter || undefined,
      });
      setAuditLogs(data.items);
      setAuditTotal(data.total);
    } catch (err: any) {
      showFeedback('error', err.response?.data?.detail || 'Failed to load audit logs');
    } finally {
      setLoadingAudit(false);
    }
  }, [isAdmin, auditPage, auditActionFilter, auditResourceFilter]);

  // Initial load according to active tab
  useEffect(() => {
    let ignore = false;
    if (!isAdmin) return;
    Promise.resolve().then(() => {
      if (ignore) return;
      if (activeTab === 'overview') {
        fetchOverview();
        fetchAutomation();
      }
      else if (activeTab === 'users') fetchUsers();
      else if (activeTab === 'locations') fetchLocationsList();
      else if (activeTab === 'data-sources') fetchDataSourcesList();
      else if (activeTab === 'alert-rules') fetchAlertRulesList();
      else if (activeTab === 'settings') fetchSettingsList();
      else if (activeTab === 'audit') fetchAuditLogsList();
    });
    return () => {
      ignore = true;
    };
  }, [
    isAdmin,
    activeTab,
    fetchOverview,
    fetchAutomation,
    fetchUsers,
    fetchLocationsList,
    fetchDataSourcesList,
    fetchAlertRulesList,
    fetchSettingsList,
    fetchAuditLogsList,
  ]);

  // -------------------------------------------------------------
  // User Handlers
  // -------------------------------------------------------------
  const handleCreateUser = async (e: React.FormEvent) => {
    e.preventDefault();
    try {
      await createUserAdmin({
        username: newUsername,
        email: newEmail,
        password: newPassword,
        role: newRole,
      });
      showFeedback('success', `User '${newUsername}' created successfully.`);
      setShowAddUserModal(false);
      setNewUsername('');
      setNewEmail('');
      setNewPassword('');
      setNewRole('viewer');
      fetchUsers();
    } catch (err: any) {
      showFeedback('error', err.response?.data?.detail || 'Failed to create user');
    }
  };

  const handleUpdateUser = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!selectedUser) return;
    try {
      await updateUserAdmin(selectedUser.id, {
        role: editRole,
        is_active: editIsActive,
      });
      showFeedback('success', `User '${selectedUser.username}' updated successfully.`);
      setShowEditUserModal(false);
      setSelectedUser(null);
      fetchUsers();
    } catch (err: any) {
      showFeedback('error', err.response?.data?.detail || 'Failed to update user');
    }
  };

  // -------------------------------------------------------------
  // Location Handlers
  // -------------------------------------------------------------
  const handleCreateLocation = async (e: React.FormEvent) => {
    e.preventDefault();
    const lat = parseFloat(locLat);
    const lon = parseFloat(locLon);
    if (isNaN(lat) || lat < -90 || lat > 90) {
      showFeedback('error', 'Latitude must be between -90 and 90');
      return;
    }
    if (isNaN(lon) || lon < -180 || lon > 180) {
      showFeedback('error', 'Longitude must be between -180 and 180');
      return;
    }

    try {
      await createLocation({
        name: locName,
        city: locCity,
        state: locState,
        country: locCountry,
        latitude: lat,
        longitude: lon,
        description: locDesc || undefined,
        is_active: true,
      });
      showFeedback('success', `Monitoring station '${locName}' added.`);
      setShowAddLocationModal(false);
      setLocName('');
      setLocCity('');
      setLocState('');
      setLocDesc('');
      fetchLocationsList();
    } catch (err: any) {
      showFeedback('error', err.response?.data?.detail || 'Failed to create location');
    }
  };

  const handleToggleLocationStatus = async (loc: Location) => {
    try {
      await updateLocation(loc.id, { is_active: !loc.is_active });
      showFeedback('success', `Station '${loc.name}' ${!loc.is_active ? 'activated' : 'deactivated'}.`);
      fetchLocationsList();
    } catch (err: any) {
      showFeedback('error', err.response?.data?.detail || 'Failed to update location');
    }
  };

  // -------------------------------------------------------------
  // Data Source Handlers
  // -------------------------------------------------------------
  const handleCreateDataSource = async (e: React.FormEvent) => {
    e.preventDefault();
    try {
      await createDataSource({
        name: dsName,
        source_type: dsType,
        provider: dsProvider || undefined,
        description: dsDesc || undefined,
        is_active: true,
      });
      showFeedback('success', `Data source '${dsName}' registered.`);
      setShowAddSourceModal(false);
      setDsName('');
      setDsProvider('');
      setDsDesc('');
      fetchDataSourcesList();
    } catch (err: any) {
      showFeedback('error', err.response?.data?.detail || 'Failed to create data source');
    }
  };

  const handleToggleDataSourceStatus = async (ds: DataSource) => {
    try {
      await updateDataSource(ds.id, { is_active: !ds.is_active });
      showFeedback('success', `Data source '${ds.name}' ${!ds.is_active ? 'activated' : 'deactivated'}.`);
      fetchDataSourcesList();
    } catch (err: any) {
      showFeedback('error', err.response?.data?.detail || 'Failed to update data source');
    }
  };

  // -------------------------------------------------------------
  // Alert Rule Handlers
  // -------------------------------------------------------------
  const handleToggleAlertRule = async (rule: AlertRule) => {
    try {
      await updateAlertRule(rule.id, { enabled: !rule.enabled });
      showFeedback('success', `Alert rule '${rule.name}' ${!rule.enabled ? 'enabled' : 'disabled'}.`);
      fetchAlertRulesList();
    } catch (err: any) {
      showFeedback('error', err.response?.data?.detail || 'Failed to update alert rule');
    }
  };

  const handleDeleteAlertRule = async (ruleId: number, ruleName: string) => {
    if (!window.confirm(`Are you sure you want to permanently delete alert rule '${ruleName}'?`)) {
      return;
    }
    try {
      await deleteAlertRule(ruleId);
      showFeedback('success', `Alert rule '${ruleName}' deleted.`);
      fetchAlertRulesList();
    } catch (err: any) {
      showFeedback('error', err.response?.data?.detail || 'Failed to delete alert rule');
    }
  };

  // -------------------------------------------------------------
  // System Setting Handlers
  // -------------------------------------------------------------
  const handleSaveSetting = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!editingSetting) return;

    // Validate prediction horizons if editing prediction_forecast_horizons_hours
    if (editingSetting.key === 'prediction_forecast_horizons_hours') {
      try {
        const parsed = JSON.parse(settingValueInput);
        if (!Array.isArray(parsed) || parsed.length === 0) {
          showFeedback('error', 'Prediction horizons must be a non-empty JSON array of numbers.');
          return;
        }
        const allowed = [1, 3, 6, 12, 24];
        const invalid = parsed.filter((v: number) => !allowed.includes(v));
        if (invalid.length > 0) {
          showFeedback(
            'error',
            `Invalid horizons: ${invalid.join(', ')}. Phase 9 ML prediction strictly supports horizons: [1, 3, 6, 12, 24].`
          );
          return;
        }
      } catch {
        showFeedback('error', 'Prediction horizons must be valid JSON format, e.g. [1, 3, 6, 12, 24]');
        return;
      }
    }

    try {
      await updateSystemSetting(editingSetting.key, settingValueInput);
      showFeedback('success', `System setting '${editingSetting.key}' updated.`);
      setEditingSetting(null);
      fetchSettingsList();
    } catch (err: any) {
      showFeedback('error', err.response?.data?.detail || 'Failed to update system setting');
    }
  };

  // -------------------------------------------------------------
  // Access Denied Screen (Strict RBAC Guard)
  // -------------------------------------------------------------
  if (!isAdmin) {
    return (
      <div className="p-8 rounded-2xl bg-slate-900/60 border border-slate-800 space-y-6">
        <div className="flex items-center gap-3 pb-4 border-b border-slate-800">
          <div className="p-2.5 rounded-xl bg-rose-500/10 text-rose-400 border border-rose-500/20">
            <ShieldAlert className="w-6 h-6" />
          </div>
          <div>
            <h2 className="text-xl font-bold text-white">Access Denied: Administrator Privilege Required</h2>
            <p className="text-xs text-slate-400">
              Role-Based Access Control (RBAC) Policy Enforcement
            </p>
          </div>
        </div>

        <div className="p-6 rounded-xl bg-rose-950/20 border border-rose-500/30 space-y-3">
          <p className="text-sm text-slate-200">
            You are logged in as <span className="font-semibold text-white">{currentUser.username}</span> with the role of{' '}
            <span className="font-mono font-bold uppercase text-amber-400">{currentUser.role}</span>.
          </p>
          <p className="text-xs text-slate-400 leading-relaxed">
            The Administration Console, Audit Trail, User Management, and System Settings are strictly reserved for users holding the <span className="font-semibold text-rose-300">admin</span> role. Analyst and Viewer roles are permitted access to data visualizations, What-If simulation, automated alerting, and environmental report generation.
          </p>
          <div className="pt-2 flex items-center gap-3">
            <button
              onClick={() => onNavigateToTab?.('dashboard')}
              className="px-4 py-2 rounded-lg bg-teal-600 hover:bg-teal-500 text-white text-xs font-semibold transition"
            >
              Return to Monitoring Dashboard
            </button>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      {/* Notifications banner */}
      {notification && (
        <div
          className={`p-4 rounded-xl border flex items-center justify-between text-xs font-medium transition-all ${
            notification.type === 'success'
              ? 'bg-emerald-950/40 text-emerald-300 border-emerald-500/30'
              : 'bg-rose-950/40 text-rose-300 border-rose-500/30'
          }`}
        >
          <div className="flex items-center gap-2.5">
            {notification.type === 'success' ? (
              <CheckCircle2 className="w-4 h-4 text-emerald-400 shrink-0" />
            ) : (
              <AlertTriangle className="w-4 h-4 text-rose-400 shrink-0" />
            )}
            <span>{notification.message}</span>
          </div>
          <button
            onClick={() => setNotification(null)}
            className="text-slate-400 hover:text-white text-xs"
          >
            Dismiss
          </button>
        </div>
      )}

      {/* Admin Header */}
      <div className="p-6 rounded-2xl bg-gradient-to-r from-slate-900 via-slate-900/90 to-purple-950/30 border border-slate-800 shadow-xl flex flex-col md:flex-row md:items-center justify-between gap-4">
        <div>
          <div className="inline-flex items-center gap-2 px-2.5 py-1 rounded-full bg-purple-500/15 border border-purple-500/30 text-purple-300 text-xs font-semibold mb-2">
            <ShieldCheck className="w-3.5 h-3.5 text-purple-400" />
            Phase 14 Administration & Configuration
          </div>
          <h1 className="text-2xl font-bold tracking-tight text-white">System Administration Panel</h1>
          <p className="text-xs text-slate-400">
            User administration, telemetry station governance, data provenance safeguards, immutable audit logging, and runtime parameters.
          </p>
        </div>

        <div className="flex items-center gap-2">
          <button
            onClick={() => {
              if (activeTab === 'overview') fetchOverview();
              else if (activeTab === 'users') fetchUsers();
              else if (activeTab === 'locations') fetchLocationsList();
              else if (activeTab === 'data-sources') fetchDataSourcesList();
              else if (activeTab === 'alert-rules') fetchAlertRulesList();
              else if (activeTab === 'settings') fetchSettingsList();
              else if (activeTab === 'audit') fetchAuditLogsList();
            }}
            className="flex items-center gap-2 px-3.5 py-2 rounded-lg bg-slate-800 hover:bg-slate-700 text-slate-200 text-xs font-medium border border-slate-700 transition"
          >
            <RefreshCw
              className={`w-3.5 h-3.5 ${
                loadingOverview || loadingUsers || loadingLocations || loadingDataSources || loadingAlertRules || loadingSettings || loadingAudit
                  ? 'animate-spin'
                  : ''
              }`}
            />
            <span>Refresh</span>
          </button>
        </div>
      </div>

      {/* Sub-Navigation Tabs */}
      <div className="flex items-center gap-1 overflow-x-auto pb-1 border-b border-slate-800">
        {[
          { id: 'overview', label: 'Overview', icon: Activity },
          { id: 'users', label: 'User Directory', icon: Users },
          { id: 'locations', label: 'Stations & Locations', icon: MapPin },
          { id: 'data-sources', label: 'Data Sources & Provenance', icon: Radio },
          { id: 'alert-rules', label: 'Alert Rules', icon: Bell },
          { id: 'settings', label: 'System Settings', icon: Sliders },
          { id: 'audit', label: 'Audit Trail', icon: FileText },
        ].map((tab) => {
          const Icon = tab.icon;
          const isActive = activeTab === tab.id;
          return (
            <button
              key={tab.id}
              onClick={() => setActiveTab(tab.id as AdminTab)}
              className={`flex items-center gap-2 px-4 py-2.5 rounded-lg text-xs font-medium whitespace-nowrap transition-all ${
                isActive
                  ? 'bg-purple-500/20 text-purple-300 border border-purple-500/30'
                  : 'text-slate-400 hover:text-slate-200 hover:bg-slate-800/60'
              }`}
            >
              <Icon className={`w-4 h-4 ${isActive ? 'text-purple-400' : 'text-slate-400'}`} />
              <span>{tab.label}</span>
            </button>
          );
        })}
      </div>

      {/* ===================================================================== */}
      {/* TAB 1: OVERVIEW */}
      {/* ===================================================================== */}
      {activeTab === 'overview' && (
        <div className="space-y-6">
          {/* Status & Metrics Summary Cards */}
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4">
            {/* Users Metric */}
            <div className="p-5 rounded-xl bg-slate-900/70 border border-slate-800 space-y-2">
              <div className="flex items-center justify-between text-xs text-slate-400">
                <span>Total Users</span>
                <Users className="w-4 h-4 text-purple-400" />
              </div>
              <div className="text-2xl font-bold text-white">
                {overview?.users?.total ?? '...'}
              </div>
              <div className="text-[11px] text-slate-400 flex items-center gap-2">
                <span className="text-emerald-400 font-medium">
                  {overview?.users?.active ?? 0} active
                </span>
                <span>•</span>
                <span>{overview?.users?.by_role?.admin ?? 0} admin</span>
                <span>•</span>
                <span>{overview?.users?.by_role?.analyst ?? 0} analyst</span>
              </div>
            </div>

            {/* Stations Metric */}
            <div className="p-5 rounded-xl bg-slate-900/70 border border-slate-800 space-y-2">
              <div className="flex items-center justify-between text-xs text-slate-400">
                <span>Monitoring Stations</span>
                <MapPin className="w-4 h-4 text-teal-400" />
              </div>
              <div className="text-2xl font-bold text-white">
                {overview?.locations?.total ?? '...'}
              </div>
              <div className="text-[11px] text-slate-400 flex items-center gap-2">
                <span className="text-emerald-400 font-medium">
                  {overview?.locations?.active ?? 0} online
                </span>
                <span>•</span>
                <span className="text-slate-500">
                  {overview?.locations?.inactive ?? 0} decommissioned
                </span>
              </div>
            </div>

            {/* Data Sources Metric */}
            <div className="p-5 rounded-xl bg-slate-900/70 border border-slate-800 space-y-2">
              <div className="flex items-center justify-between text-xs text-slate-400">
                <span>Data Sources</span>
                <Radio className="w-4 h-4 text-blue-400" />
              </div>
              <div className="text-2xl font-bold text-white">
                {overview?.data_sources?.total ?? '...'}
              </div>
              <div className="text-[11px] text-slate-400 flex items-center gap-2">
                <span>API: {overview?.data_sources?.by_type?.API ?? 0}</span>
                <span>•</span>
                <span>SIM: {overview?.data_sources?.by_type?.SIMULATED ?? 0}</span>
                <span>•</span>
                <span>DEMO: {overview?.data_sources?.by_type?.DEMO ?? 0}</span>
              </div>
            </div>

            {/* Alert Rules Metric */}
            <div className="p-5 rounded-xl bg-slate-900/70 border border-slate-800 space-y-2">
              <div className="flex items-center justify-between text-xs text-slate-400">
                <span>Alert Rules</span>
                <Bell className="w-4 h-4 text-amber-400" />
              </div>
              <div className="text-2xl font-bold text-white">
                {overview?.alert_rules?.total ?? '...'}
              </div>
              <div className="text-[11px] text-slate-400 flex items-center gap-2">
                <span className="text-emerald-400 font-medium">
                  {overview?.alert_rules?.enabled ?? 0} active
                </span>
                <span>•</span>
                <span className="text-slate-500">
                  {overview?.alert_rules?.disabled ?? 0} disabled
                </span>
              </div>
            </div>
          </div>

          {/* System Runtime Health Status */}
          <div className="p-5 rounded-xl bg-slate-900/70 border border-slate-800 space-y-4">
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-2.5">
                <Server className="w-5 h-5 text-indigo-400" />
                <h3 className="text-sm font-bold text-white">Runtime Environment & Engine Connectivity</h3>
              </div>
              <span className="px-2.5 py-1 rounded-full text-xs font-semibold bg-emerald-500/10 text-emerald-400 border border-emerald-500/20">
                HEALTHY
              </span>
            </div>

            <div className="grid grid-cols-1 md:grid-cols-4 gap-4 text-xs">
              <div className="p-3 rounded-lg bg-slate-950/60 border border-slate-800/80">
                <span className="text-slate-400 block text-[10px] uppercase font-semibold">Application</span>
                <span className="font-mono text-slate-200">{overview?.system_status?.app_name || 'AeroPulse AI'}</span>
              </div>
              <div className="p-3 rounded-lg bg-slate-950/60 border border-slate-800/80">
                <span className="text-slate-400 block text-[10px] uppercase font-semibold">Version</span>
                <span className="font-mono text-slate-200">{overview?.system_status?.version || '1.0.0'}</span>
              </div>
              <div className="p-3 rounded-lg bg-slate-950/60 border border-slate-800/80">
                <span className="text-slate-400 block text-[10px] uppercase font-semibold">Environment</span>
                <span className="font-mono text-purple-300 uppercase">{overview?.system_status?.environment || 'development'}</span>
              </div>
              <div className="p-3 rounded-lg bg-slate-950/60 border border-slate-800/80">
                <span className="text-slate-400 block text-[10px] uppercase font-semibold">Database Engine</span>
                <span className="font-mono text-teal-300 uppercase">
                  {overview?.system_status?.database_dialect || 'SQLAlchemy / SQLite'}
                </span>
              </div>
            </div>
          </div>

          {/* Phase 19 Production Data Quality & Trust Layer Summary */}
          <div className="p-5 rounded-xl bg-slate-900/70 border border-slate-800 space-y-4">
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-2.5">
                <ShieldCheck className="w-5 h-5 text-emerald-400" />
                <div>
                  <h3 className="text-sm font-bold text-white flex items-center gap-2">
                    Production Data Quality, Reliability & Freshness
                    <span className="text-[10px] font-mono px-1.5 py-0.5 rounded bg-emerald-950/80 border border-emerald-800/60 text-emerald-300">
                      Phase 19
                    </span>
                  </h3>
                  <p className="text-xs text-slate-400">
                    Deterministic verification of station telemetry freshness, CPCB completeness, and ML prediction readiness.
                  </p>
                </div>
              </div>
              <span className="px-2.5 py-1 rounded-full text-xs font-semibold bg-emerald-500/10 text-emerald-400 border border-emerald-500/20">
                ACTIVE
              </span>
            </div>

            <div className="grid grid-cols-1 md:grid-cols-4 gap-4 text-xs">
              <div className="p-3 rounded-lg bg-slate-950/60 border border-slate-800/80">
                <span className="text-slate-400 block text-[10px] uppercase font-semibold">Fresh Telemetry (≤3h)</span>
                <span className="font-mono text-xl font-bold text-emerald-400">
                  {trustOverview?.fresh_stations_count ?? 0}
                </span>
                <span className="text-[10px] text-slate-500 block mt-0.5">Live current stations</span>
              </div>
              <div className="p-3 rounded-lg bg-slate-950/60 border border-slate-800/80">
                <span className="text-slate-400 block text-[10px] uppercase font-semibold">Delayed / Stale (3–24h)</span>
                <span className="font-mono text-xl font-bold text-amber-400">
                  {trustOverview?.stale_stations_count ?? 0}
                </span>
                <span className="text-[10px] text-slate-500 block mt-0.5">Delayed upstream ingestion</span>
              </div>
              <div className="p-3 rounded-lg bg-slate-950/60 border border-slate-800/80">
                <span className="text-slate-400 block text-[10px] uppercase font-semibold">Unavailable (&gt;24h)</span>
                <span className="font-mono text-xl font-bold text-slate-400">
                  {trustOverview?.unavailable_stations_count ?? 0}
                </span>
                <span className="text-[10px] text-slate-500 block mt-0.5">Offline or missing telemetry</span>
              </div>
              <div className="p-3 rounded-lg bg-slate-950/60 border border-slate-800/80">
                <span className="text-slate-400 block text-[10px] uppercase font-semibold">Active Model Horizons</span>
                <span className="font-mono text-xl font-bold text-violet-400">
                  {trustOverview?.active_model_horizons?.length ? `+${trustOverview.active_model_horizons.join('h, +')}h` : 'None'}
                </span>
                <span className="text-[10px] text-slate-500 block mt-0.5">
                  {trustOverview?.available_models_count ?? 0} trained models registered
                </span>
              </div>
            </div>
          </div>

          {/* Phase 18 Continuous Monitoring & Automation Control Panel */}
          <div className="p-5 rounded-xl bg-slate-900/70 border border-slate-800 space-y-4">
            <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-3">
              <div className="flex items-center gap-2.5">
                <Radio className="w-5 h-5 text-cyan-400" />
                <div>
                  <h3 className="text-sm font-bold text-white flex items-center gap-2">
                    Continuous Monitoring & Automation
                    <span className="text-[10px] font-mono px-1.5 py-0.5 rounded bg-cyan-950/80 border border-cyan-800/60 text-cyan-300">
                      Phase 18
                    </span>
                  </h3>
                  <p className="text-xs text-slate-400">
                    Autonomous scheduled polling of active OpenAQ stations, incremental ingestion, AQI recalculation, ML prediction & alert evaluation.
                  </p>
                </div>
              </div>

              <div className="flex items-center gap-2 flex-wrap">
                <span
                  className={`px-2.5 py-1 rounded-full text-xs font-semibold border flex items-center gap-1.5 ${
                    automationStatus?.status === 'RUNNING'
                      ? 'bg-amber-500/10 text-amber-400 border-amber-500/30 animate-pulse'
                      : automationStatus?.paused
                      ? 'bg-orange-500/10 text-orange-400 border-orange-500/30'
                      : automationStatus?.status === 'BACKOFF'
                      ? 'bg-rose-500/10 text-rose-400 border-rose-500/30'
                      : automationStatus?.enabled
                      ? 'bg-emerald-500/10 text-emerald-400 border-emerald-500/30'
                      : 'bg-slate-800 text-slate-400 border-slate-700'
                  }`}
                >
                  <span
                    className={`w-1.5 h-1.5 rounded-full ${
                      automationStatus?.status === 'RUNNING'
                        ? 'bg-amber-400 animate-ping'
                        : automationStatus?.paused
                        ? 'bg-orange-400'
                        : automationStatus?.status === 'BACKOFF'
                        ? 'bg-rose-400'
                        : automationStatus?.enabled
                        ? 'bg-emerald-400'
                        : 'bg-slate-400'
                    }`}
                  />
                  {automationStatus?.status === 'RUNNING'
                    ? 'CYCLE RUNNING'
                    : automationStatus?.paused
                    ? 'SCHEDULER PAUSED'
                    : automationStatus?.status === 'BACKOFF'
                    ? 'RATE-LIMIT BACKOFF'
                    : automationStatus?.enabled
                    ? 'AUTONOMOUS ACTIVE'
                    : 'SCHEDULER DISABLED'}
                </span>

                <button
                  onClick={handleTriggerSync}
                  disabled={triggeringSync || automationStatus?.status === 'RUNNING'}
                  className="px-3 py-1.5 rounded-lg bg-cyan-600 hover:bg-cyan-500 disabled:opacity-50 text-white text-xs font-semibold flex items-center gap-1.5 transition shadow-sm"
                  title="Run an immediate manual synchronization cycle"
                >
                  <Play className={`w-3.5 h-3.5 ${triggeringSync ? 'animate-spin' : ''}`} />
                  {triggeringSync ? 'Syncing...' : 'Trigger Sync'}
                </button>

                <button
                  onClick={handleTogglePause}
                  disabled={!automationStatus || !automationStatus.enabled}
                  className="px-3 py-1.5 rounded-lg bg-slate-800 hover:bg-slate-700 border border-slate-700 text-slate-200 text-xs font-semibold flex items-center gap-1.5 transition"
                  title={automationStatus?.paused ? 'Resume autonomous polling schedule' : 'Pause autonomous polling schedule'}
                >
                  {automationStatus?.paused ? (
                    <>
                      <Play className="w-3.5 h-3.5 text-emerald-400" />
                      Resume
                    </>
                  ) : (
                    <>
                      <Pause className="w-3.5 h-3.5 text-amber-400" />
                      Pause
                    </>
                  )}
                </button>

                <button
                  onClick={fetchAutomation}
                  disabled={loadingAutomation}
                  className="p-1.5 rounded-lg bg-slate-800/80 hover:bg-slate-700 border border-slate-700 text-slate-300 transition"
                  title="Refresh automation state"
                >
                  <RefreshCw className={`w-3.5 h-3.5 ${loadingAutomation ? 'animate-spin' : ''}`} />
                </button>
              </div>
            </div>

            {/* Metrics Grid */}
            <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 text-xs">
              <div className="p-3 rounded-lg bg-slate-950/60 border border-slate-800/80">
                <span className="text-slate-400 block text-[10px] uppercase font-semibold">Schedule Interval</span>
                <span className="font-mono text-cyan-300">
                  {automationStatus ? `Every ${automationStatus.poll_interval_minutes}m` : '--'}
                </span>
              </div>
              <div className="p-3 rounded-lg bg-slate-950/60 border border-slate-800/80">
                <span className="text-slate-400 block text-[10px] uppercase font-semibold">Station Pool</span>
                <span className="font-mono text-slate-200">
                  {automationStatus ? `${automationStatus.active_stations_count} active stations` : '--'}
                </span>
              </div>
              <div className="p-3 rounded-lg bg-slate-950/60 border border-slate-800/80">
                <span className="text-slate-400 block text-[10px] uppercase font-semibold">Last Completed Run</span>
                <span className="font-mono text-slate-300">
                  {automationStatus?.last_run ? new Date(automationStatus.last_run).toLocaleTimeString() : 'Never'}
                </span>
              </div>
              <div className="p-3 rounded-lg bg-slate-950/60 border border-slate-800/80">
                <span className="text-slate-400 block text-[10px] uppercase font-semibold">Next Scheduled Poll</span>
                <span className="font-mono text-indigo-300">
                  {automationStatus?.paused
                    ? 'Paused'
                    : automationStatus?.next_run
                    ? new Date(automationStatus.next_run).toLocaleTimeString()
                    : '--'}
                </span>
              </div>
            </div>

            {/* Recent Cycles Log */}
            <div className="space-y-2">
              <div className="flex items-center justify-between">
                <span className="text-xs font-semibold text-slate-300">Recent Automation Execution History</span>
                <span className="text-[11px] text-slate-500 font-mono">
                  {automationStatus?.recent_cycles?.length || 0} cycles in memory
                </span>
              </div>

              {automationStatus && automationStatus.recent_cycles && automationStatus.recent_cycles.length > 0 ? (
                <div className="overflow-x-auto rounded-lg border border-slate-800/80">
                  <table className="w-full text-left text-xs">
                    <thead className="bg-slate-950/80 text-slate-400 font-semibold border-b border-slate-800">
                      <tr>
                        <th className="p-2.5">Time</th>
                        <th className="p-2.5">Stations</th>
                        <th className="p-2.5">Readings</th>
                        <th className="p-2.5">Predictions</th>
                        <th className="p-2.5">Retrained</th>
                        <th className="p-2.5">Duration</th>
                        <th className="p-2.5">Status</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-slate-800/50">
                      {automationStatus.recent_cycles.map((c) => (
                        <tr key={c.cycle_id} className="hover:bg-slate-800/30 transition text-slate-300 font-mono text-[11px]">
                          <td className="p-2.5 text-slate-400">
                            {new Date(c.started_at).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' })}
                          </td>
                          <td className="p-2.5">
                            <span className="text-emerald-400 font-semibold">{c.stations_processed - c.stations_failed}</span>
                            <span className="text-slate-500">/{c.stations_processed}</span>
                            {c.stations_failed > 0 && <span className="text-rose-400 ml-1">({c.stations_failed} err)</span>}
                          </td>
                          <td className="p-2.5 text-slate-200">+{c.observations_ingested}</td>
                          <td className="p-2.5 text-indigo-300">{c.predictions_generated}</td>
                          <td className="p-2.5">
                            {c.models_retrained ? (
                              <span className="text-emerald-400 font-semibold">Yes</span>
                            ) : (
                              <span className="text-slate-500">No</span>
                            )}
                          </td>
                          <td className="p-2.5 text-slate-400">
                            {c.duration_seconds !== undefined ? `${c.duration_seconds.toFixed(2)}s` : '--'}
                          </td>
                          <td className="p-2.5">
                            <span
                              className={`px-2 py-0.5 rounded-full text-[10px] font-semibold border ${
                                c.status === 'success'
                                  ? 'bg-emerald-500/10 text-emerald-400 border-emerald-500/20'
                                  : c.status === 'partial_success'
                                  ? 'bg-amber-500/10 text-amber-400 border-amber-500/20'
                                  : c.status === 'backoff'
                                  ? 'bg-orange-500/10 text-orange-400 border-orange-500/20'
                                  : c.status === 'skipped'
                                  ? 'bg-slate-700 text-slate-300 border-slate-600'
                                  : 'bg-rose-500/10 text-rose-400 border-rose-500/20'
                              }`}
                            >
                              {c.status.toUpperCase()}
                            </span>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              ) : (
                <div className="p-3 text-center rounded-lg bg-slate-950/40 border border-slate-800/60 text-slate-500 text-xs">
                  No automated cycles recorded in current supervisor session yet.
                </div>
              )}
            </div>
          </div>

          {/* Recent Audit Activities */}
          <div className="p-5 rounded-xl bg-slate-900/70 border border-slate-800 space-y-4">
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-2.5">
                <FileText className="w-5 h-5 text-purple-400" />
                <h3 className="text-sm font-bold text-white">Recent System Audit Events</h3>
              </div>
              <button
                onClick={() => setActiveTab('audit')}
                className="text-xs text-purple-400 hover:text-purple-300 font-medium"
              >
                View Full Audit Trail &rarr;
              </button>
            </div>

            <div className="overflow-x-auto">
              <table className="w-full text-left text-xs">
                <thead className="bg-slate-950/60 text-slate-400 font-semibold border-b border-slate-800">
                  <tr>
                    <th className="p-3">Timestamp</th>
                    <th className="p-3">Actor</th>
                    <th className="p-3">Action</th>
                    <th className="p-3">Target</th>
                    <th className="p-3">Description</th>
                    <th className="p-3">Status</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-800/60">
                  {overview?.recent_audit_logs?.slice(0, 5).map((log) => (
                    <tr key={log.id} className="hover:bg-slate-800/30 transition">
                      <td className="p-3 font-mono text-slate-400">
                        {new Date(log.timestamp).toLocaleString()}
                      </td>
                      <td className="p-3 font-semibold text-slate-200">
                        {log.username_snapshot}
                      </td>
                      <td className="p-3">
                        <span className="px-2 py-0.5 rounded font-mono text-[10px] font-semibold bg-slate-800 text-slate-300">
                          {log.action}
                        </span>
                      </td>
                      <td className="p-3 font-mono text-slate-400">
                        {log.resource_type} {log.resource_id ? `#${log.resource_id}` : ''}
                      </td>
                      <td className="p-3 text-slate-300 max-w-xs truncate">
                        {log.description}
                      </td>
                      <td className="p-3">
                        {log.success ? (
                          <span className="px-2 py-0.5 rounded-full text-[10px] font-semibold bg-emerald-500/10 text-emerald-400 border border-emerald-500/20">
                            SUCCESS
                          </span>
                        ) : (
                          <span className="px-2 py-0.5 rounded-full text-[10px] font-semibold bg-rose-500/10 text-rose-400 border border-rose-500/20">
                            FAILED
                          </span>
                        )}
                      </td>
                    </tr>
                  ))}
                  {(!overview?.recent_audit_logs || overview.recent_audit_logs.length === 0) && (
                    <tr>
                      <td colSpan={6} className="p-4 text-center text-slate-500">
                        No audit events recorded yet.
                      </td>
                    </tr>
                  )}
                </tbody>
              </table>
            </div>
          </div>
        </div>
      )}

      {/* ===================================================================== */}
      {/* TAB 2: USER DIRECTORY */}
      {/* ===================================================================== */}
      {activeTab === 'users' && (
        <div className="space-y-4">
          <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3">
            <div className="flex items-center gap-2 flex-1 max-w-md">
              <div className="relative flex-1">
                <Search className="w-3.5 h-3.5 text-slate-400 absolute left-3 top-1/2 -translate-y-1/2" />
                <input
                  type="text"
                  placeholder="Search by username or email..."
                  value={usersSearch}
                  onChange={(e) => setUsersSearch(e.target.value)}
                  className="w-full pl-9 pr-3 py-2 rounded-lg bg-slate-900 border border-slate-800 text-xs text-slate-200 placeholder-slate-500 focus:outline-none focus:border-purple-500/50"
                />
              </div>
              <select
                value={usersRoleFilter}
                onChange={(e) => setUsersRoleFilter(e.target.value)}
                className="px-3 py-2 rounded-lg bg-slate-900 border border-slate-800 text-xs text-slate-300 focus:outline-none focus:border-purple-500/50"
              >
                <option value="">All Roles</option>
                <option value="admin">Admin</option>
                <option value="analyst">Analyst</option>
                <option value="viewer">Viewer</option>
              </select>
            </div>

            <button
              onClick={() => setShowAddUserModal(true)}
              className="flex items-center gap-2 px-4 py-2 rounded-lg bg-purple-600 hover:bg-purple-500 text-white text-xs font-semibold transition"
            >
              <Plus className="w-4 h-4" />
              <span>Create User</span>
            </button>
          </div>

          {/* User Table */}
          <div className="rounded-xl border border-slate-800 bg-slate-900/60 overflow-hidden">
            <table className="w-full text-left text-xs">
              <thead className="bg-slate-950/60 text-slate-400 font-semibold border-b border-slate-800">
                <tr>
                  <th className="p-3">ID</th>
                  <th className="p-3">Username</th>
                  <th className="p-3">Email</th>
                  <th className="p-3">Role</th>
                  <th className="p-3">Status</th>
                  <th className="p-3">Created</th>
                  <th className="p-3 text-right">Actions</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-800/60">
                {users.map((u) => (
                  <tr key={u.id} className="hover:bg-slate-800/30 transition">
                    <td className="p-3 font-mono text-slate-400">{u.id}</td>
                    <td className="p-3 font-semibold text-slate-200">
                      {u.username}
                      {u.id === currentUser.id && (
                        <span className="ml-2 text-[10px] text-teal-400 font-mono">(You)</span>
                      )}
                    </td>
                    <td className="p-3 text-slate-300">{u.email}</td>
                    <td className="p-3">
                      <span
                        className={`px-2 py-0.5 rounded text-[10px] font-bold uppercase font-mono ${
                          u.role === 'admin'
                            ? 'bg-purple-500/20 text-purple-300 border border-purple-500/30'
                            : u.role === 'analyst'
                            ? 'bg-blue-500/20 text-blue-300 border border-blue-500/30'
                            : 'bg-slate-800 text-slate-300'
                        }`}
                      >
                        {u.role}
                      </span>
                    </td>
                    <td className="p-3">
                      {u.is_active ? (
                        <span className="px-2 py-0.5 rounded-full text-[10px] font-semibold bg-emerald-500/10 text-emerald-400 border border-emerald-500/20">
                          Active
                        </span>
                      ) : (
                        <span className="px-2 py-0.5 rounded-full text-[10px] font-semibold bg-rose-500/10 text-rose-400 border border-rose-500/20">
                          Inactive
                        </span>
                      )}
                    </td>
                    <td className="p-3 font-mono text-slate-400">
                      {new Date(u.created_at).toLocaleDateString()}
                    </td>
                    <td className="p-3 text-right">
                      <button
                        onClick={() => {
                          setSelectedUser(u);
                          setEditRole(u.role);
                          setEditIsActive(u.is_active);
                          setShowEditUserModal(true);
                        }}
                        className="px-2.5 py-1 rounded bg-slate-800 hover:bg-slate-700 text-slate-300 text-[11px] font-medium transition"
                      >
                        Edit
                      </button>
                    </td>
                  </tr>
                ))}
                {users.length === 0 && (
                  <tr>
                    <td colSpan={7} className="p-6 text-center text-slate-500">
                      No users matched the criteria.
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>

          {/* User Pagination */}
          <div className="flex items-center justify-between pt-2">
            <button
              onClick={() => setUsersPage((p) => Math.max(1, p - 1))}
              disabled={usersPage <= 1}
              className="px-3 py-1.5 rounded-lg bg-slate-800 hover:bg-slate-700 disabled:opacity-40 text-xs text-slate-300 transition flex items-center gap-1"
            >
              <ChevronLeft className="w-3.5 h-3.5" />
              <span>Previous</span>
            </button>
            <span className="text-xs text-slate-400 font-mono">
              Page {usersPage} • Total: {usersTotal}
            </span>
            <button
              onClick={() => setUsersPage((p) => p + 1)}
              disabled={users.length < 10}
              className="px-3 py-1.5 rounded-lg bg-slate-800 hover:bg-slate-700 disabled:opacity-40 text-xs text-slate-300 transition flex items-center gap-1"
            >
              <span>Next</span>
              <ChevronRight className="w-3.5 h-3.5" />
            </button>
          </div>

          {/* User Safeguards Notice */}
          <div className="p-4 rounded-xl bg-slate-900/40 border border-slate-800/80 text-xs text-slate-400 flex items-start gap-2.5">
            <Lock className="w-4 h-4 text-purple-400 shrink-0 mt-0.5" />
            <div>
              <span className="font-semibold text-slate-200">Administrative Safeguards: </span>
              Last-Admin protection strictly prohibits deactivating or demoting the last remaining active administrator. Self-deactivation and self-demotion are blocked by server-side policy to prevent accidental lockout.
            </div>
          </div>
        </div>
      )}

      {/* ===================================================================== */}
      {/* TAB 3: STATIONS & LOCATIONS */}
      {/* ===================================================================== */}
      {activeTab === 'locations' && (
        <div className="space-y-4">
          <div className="flex items-center justify-between">
            <div>
              <h3 className="text-sm font-bold text-white">Monitoring Stations Directory</h3>
              <p className="text-xs text-slate-400">
                Authoritative spatial stations used across telemetry ingestion, CPCB AQI scoring, and ML forecasting.
              </p>
            </div>
            <button
              onClick={() => setShowAddLocationModal(true)}
              className="flex items-center gap-2 px-4 py-2 rounded-lg bg-teal-600 hover:bg-teal-500 text-white text-xs font-semibold transition"
            >
              <Plus className="w-4 h-4" />
              <span>Add Station</span>
            </button>
          </div>

          <div className="rounded-xl border border-slate-800 bg-slate-900/60 overflow-hidden">
            <table className="w-full text-left text-xs">
              <thead className="bg-slate-950/60 text-slate-400 font-semibold border-b border-slate-800">
                <tr>
                  <th className="p-3">ID</th>
                  <th className="p-3">Station Name</th>
                  <th className="p-3">City & State</th>
                  <th className="p-3">Coordinates (Lat / Lon)</th>
                  <th className="p-3">Status</th>
                  <th className="p-3 text-right">Actions</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-800/60">
                {locations.map((loc) => (
                  <tr key={loc.id} className="hover:bg-slate-800/30 transition">
                    <td className="p-3 font-mono text-slate-400">{loc.id}</td>
                    <td className="p-3 font-semibold text-slate-200">{loc.name}</td>
                    <td className="p-3 text-slate-300">
                      {loc.city}, {loc.state}
                    </td>
                    <td className="p-3 font-mono text-slate-400">
                      {loc.latitude.toFixed(4)}, {loc.longitude.toFixed(4)}
                    </td>
                    <td className="p-3">
                      {loc.is_active ? (
                        <span className="px-2 py-0.5 rounded-full text-[10px] font-semibold bg-emerald-500/10 text-emerald-400 border border-emerald-500/20">
                          Active
                        </span>
                      ) : (
                        <span className="px-2 py-0.5 rounded-full text-[10px] font-semibold bg-rose-500/10 text-rose-400 border border-rose-500/20">
                          Decommissioned
                        </span>
                      )}
                    </td>
                    <td className="p-3 text-right">
                      <button
                        onClick={() => handleToggleLocationStatus(loc)}
                        className={`px-2.5 py-1 rounded text-[11px] font-medium transition ${
                          loc.is_active
                            ? 'bg-rose-500/10 text-rose-400 hover:bg-rose-500/20'
                            : 'bg-emerald-500/10 text-emerald-400 hover:bg-emerald-500/20'
                        }`}
                      >
                        {loc.is_active ? 'Deactivate' : 'Activate'}
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* ===================================================================== */}
      {/* TAB 4: DATA SOURCES & PROVENANCE */}
      {/* ===================================================================== */}
      {activeTab === 'data-sources' && (
        <div className="space-y-4">
          <div className="p-4 rounded-xl bg-amber-500/10 border border-amber-500/20 flex items-start gap-3 text-xs text-amber-200/90">
            <ShieldAlert className="w-5 h-5 text-amber-400 shrink-0 mt-0.5" />
            <div>
              <span className="font-semibold text-amber-300">Data Source Provenance Integrity: </span>
              The <code className="font-mono bg-amber-950/40 px-1 py-0.5 rounded">source_type</code> attribute (API, UPLOADED, SIMULATED, DEMO) is immutable once created to ensure compliance with scientific integrity and audit provenance standards. Physical sensors are never simulated as measured telemetry.
            </div>
          </div>

          <div className="flex items-center justify-between">
            <div>
              <h3 className="text-sm font-bold text-white">Registered Data Ingestion Streams</h3>
              <p className="text-xs text-slate-400">
                Manage active pipelines, data providers, and operational status.
              </p>
            </div>
            <button
              onClick={() => setShowAddSourceModal(true)}
              className="flex items-center gap-2 px-4 py-2 rounded-lg bg-blue-600 hover:bg-blue-500 text-white text-xs font-semibold transition"
            >
              <Plus className="w-4 h-4" />
              <span>Register Source</span>
            </button>
          </div>

          <div className="rounded-xl border border-slate-800 bg-slate-900/60 overflow-hidden">
            <table className="w-full text-left text-xs">
              <thead className="bg-slate-950/60 text-slate-400 font-semibold border-b border-slate-800">
                <tr>
                  <th className="p-3">ID</th>
                  <th className="p-3">Source Name</th>
                  <th className="p-3">Provenance Type</th>
                  <th className="p-3">Provider</th>
                  <th className="p-3">Description</th>
                  <th className="p-3">Status</th>
                  <th className="p-3 text-right">Actions</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-800/60">
                {dataSources.map((ds) => (
                  <tr key={ds.id} className="hover:bg-slate-800/30 transition">
                    <td className="p-3 font-mono text-slate-400">{ds.id}</td>
                    <td className="p-3 font-semibold text-slate-200">{ds.name}</td>
                    <td className="p-3">
                      <span
                        className={`px-2 py-0.5 rounded text-[10px] font-bold uppercase font-mono ${
                          ds.source_type === 'API'
                            ? 'bg-blue-500/20 text-blue-300 border border-blue-500/30'
                            : ds.source_type === 'SIMULATED'
                            ? 'bg-purple-500/20 text-purple-300 border border-purple-500/30'
                            : ds.source_type === 'DEMO'
                            ? 'bg-amber-500/20 text-amber-300 border border-amber-500/30'
                            : 'bg-emerald-500/20 text-emerald-300 border border-emerald-500/30'
                        }`}
                      >
                        {ds.source_type}
                      </span>
                    </td>
                    <td className="p-3 text-slate-300">{ds.provider || '—'}</td>
                    <td className="p-3 text-slate-400 max-w-xs truncate">
                      {ds.description || '—'}
                    </td>
                    <td className="p-3">
                      {ds.is_active ? (
                        <span className="px-2 py-0.5 rounded-full text-[10px] font-semibold bg-emerald-500/10 text-emerald-400 border border-emerald-500/20">
                          Active
                        </span>
                      ) : (
                        <span className="px-2 py-0.5 rounded-full text-[10px] font-semibold bg-rose-500/10 text-rose-400 border border-rose-500/20">
                          Suspended
                        </span>
                      )}
                    </td>
                    <td className="p-3 text-right">
                      <button
                        onClick={() => handleToggleDataSourceStatus(ds)}
                        className={`px-2.5 py-1 rounded text-[11px] font-medium transition ${
                          ds.is_active
                            ? 'bg-rose-500/10 text-rose-400 hover:bg-rose-500/20'
                            : 'bg-emerald-500/10 text-emerald-400 hover:bg-emerald-500/20'
                        }`}
                      >
                        {ds.is_active ? 'Suspend' : 'Resume'}
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* ===================================================================== */}
      {/* TAB 5: ALERT RULES */}
      {/* ===================================================================== */}
      {activeTab === 'alert-rules' && (
        <div className="space-y-4">
          <div className="flex items-center justify-between">
            <div>
              <h3 className="text-sm font-bold text-white">Automated Alert Rules Management</h3>
              <p className="text-xs text-slate-400">
                Phase 10 threshold policies. Any modification or deletion is automatically recorded in the audit log.
              </p>
            </div>
            <button
              onClick={() => onNavigateToTab?.('alerts')}
              className="px-3.5 py-2 rounded-lg bg-slate-800 hover:bg-slate-700 text-slate-300 text-xs font-medium border border-slate-700 transition"
            >
              Open Full Alert Center &rarr;
            </button>
          </div>

          <div className="rounded-xl border border-slate-800 bg-slate-900/60 overflow-hidden">
            <table className="w-full text-left text-xs">
              <thead className="bg-slate-950/60 text-slate-400 font-semibold border-b border-slate-800">
                <tr>
                  <th className="p-3">ID</th>
                  <th className="p-3">Rule Name</th>
                  <th className="p-3">Alert Type</th>
                  <th className="p-3">Threshold</th>
                  <th className="p-3">Severity</th>
                  <th className="p-3">Status</th>
                  <th className="p-3 text-right">Actions</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-800/60">
                {alertRules.map((rule) => (
                  <tr key={rule.id} className="hover:bg-slate-800/30 transition">
                    <td className="p-3 font-mono text-slate-400">{rule.id}</td>
                    <td className="p-3 font-semibold text-slate-200">{rule.name}</td>
                    <td className="p-3 font-mono text-teal-300 uppercase">{rule.alert_type}</td>
                    <td className="p-3 font-mono text-slate-300">
                      &gt; {rule.threshold} {rule.duration_hours ? `(${rule.duration_hours}h)` : ''}
                    </td>
                    <td className="p-3">
                      <span
                        className={`px-2 py-0.5 rounded text-[10px] font-bold uppercase ${
                          rule.severity === 'CRITICAL'
                            ? 'bg-rose-500/20 text-rose-300'
                            : rule.severity === 'HIGH'
                            ? 'bg-amber-500/20 text-amber-300'
                            : 'bg-yellow-500/20 text-yellow-300'
                        }`}
                      >
                        {rule.severity}
                      </span>
                    </td>
                    <td className="p-3">
                      {rule.enabled ? (
                        <span className="px-2 py-0.5 rounded-full text-[10px] font-semibold bg-emerald-500/10 text-emerald-400 border border-emerald-500/20">
                          Active
                        </span>
                      ) : (
                        <span className="px-2 py-0.5 rounded-full text-[10px] font-semibold bg-slate-800 text-slate-400">
                          Disabled
                        </span>
                      )}
                    </td>
                    <td className="p-3 text-right space-x-2">
                      <button
                        onClick={() => handleToggleAlertRule(rule)}
                        className="px-2.5 py-1 rounded bg-slate-800 hover:bg-slate-700 text-slate-300 text-[11px] font-medium transition"
                      >
                        {rule.enabled ? 'Disable' : 'Enable'}
                      </button>
                      <button
                        onClick={() => handleDeleteAlertRule(rule.id, rule.name)}
                        className="px-2.5 py-1 rounded bg-rose-950/40 hover:bg-rose-900/60 text-rose-400 text-[11px] font-medium transition"
                      >
                        Delete
                      </button>
                    </td>
                  </tr>
                ))}
                {alertRules.length === 0 && (
                  <tr>
                    <td colSpan={7} className="p-6 text-center text-slate-500">
                      No alert rules configured.
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* ===================================================================== */}
      {/* TAB 6: SYSTEM SETTINGS */}
      {/* ===================================================================== */}
      {activeTab === 'settings' && (
        <div className="space-y-4">
          <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3">
            <div>
              <h3 className="text-sm font-bold text-white">System Runtime Configurations</h3>
              <p className="text-xs text-slate-400">
                Manage operational thresholds, forecasting horizons, and UI refresh policies.
              </p>
            </div>
            <select
              value={settingCategoryFilter}
              onChange={(e) => setSettingCategoryFilter(e.target.value)}
              className="px-3 py-2 rounded-lg bg-slate-900 border border-slate-800 text-xs text-slate-300 focus:outline-none focus:border-purple-500/50"
            >
              <option value="">All Categories</option>
              <option value="GENERAL">General</option>
              <option value="AQI_STANDARDS">AQI Standards</option>
              <option value="ANALYTICS">Analytics</option>
              <option value="PREDICTION">Prediction</option>
              <option value="REPORTING">Reporting</option>
            </select>
          </div>

          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            {settings.map((s) => (
              <div
                key={s.id}
                className="p-4 rounded-xl bg-slate-900/70 border border-slate-800 space-y-3 flex flex-col justify-between"
              >
                <div className="space-y-1.5">
                  <div className="flex items-center justify-between">
                    <span className="font-mono text-xs font-bold text-purple-300">{s.key}</span>
                    <span className="px-2 py-0.5 rounded text-[10px] font-mono bg-slate-800 text-slate-400">
                      {s.category}
                    </span>
                  </div>
                  <p className="text-xs text-slate-400 leading-relaxed">
                    {s.description || 'System runtime parameter.'}
                  </p>
                </div>

                <div className="pt-2 border-t border-slate-800/80 space-y-2">
                  <div className="flex items-center justify-between text-xs">
                    <span className="text-slate-500">Current Value:</span>
                    <span className="font-mono font-bold text-teal-300 bg-slate-950 px-2 py-1 rounded border border-slate-800">
                      {s.value}
                    </span>
                  </div>

                  <div className="flex items-center justify-between text-[10px] text-slate-500">
                    <span>Type: {s.value_type}</span>
                    <span>Updated by: {s.updated_by || 'system'}</span>
                  </div>

                  <button
                    onClick={() => {
                      setEditingSetting(s);
                      setSettingValueInput(s.value);
                    }}
                    className="w-full mt-2 py-1.5 rounded-lg bg-slate-800 hover:bg-slate-700 text-slate-200 text-xs font-medium transition flex items-center justify-center gap-1.5"
                  >
                    <Edit2 className="w-3 h-3" />
                    <span>Configure</span>
                  </button>
                </div>
              </div>
            ))}
          </div>

          {/* Special notice for ML Prediction Horizons */}
          <div className="p-4 rounded-xl bg-indigo-500/10 border border-indigo-500/20 text-xs text-indigo-300 space-y-1">
            <div className="font-semibold text-indigo-200">
              Note on Prediction Forecasting Horizons:
            </div>
            <p className="text-slate-400 text-[11px] leading-relaxed">
              In accordance with Phase 9 specifications, Random Forest ML multi-output forecasting strictly supports horizons: <code className="font-mono text-indigo-300">[1, 3, 6, 12, 24]</code> hours. Arbitrary unsupported horizons cannot be specified.
            </p>
          </div>
        </div>
      )}

      {/* ===================================================================== */}
      {/* TAB 7: AUDIT TRAIL */}
      {/* ===================================================================== */}
      {activeTab === 'audit' && (
        <div className="space-y-4">
          <div className="p-4 rounded-xl bg-slate-900/40 border border-slate-800 text-xs text-slate-400 flex items-start gap-2.5">
            <ShieldCheck className="w-4 h-4 text-purple-400 shrink-0 mt-0.5" />
            <div>
              <span className="font-semibold text-slate-200">Immutable Audit Record Guarantee: </span>
              All administrative actions, configuration adjustments, and domain mutations are written to append-only storage with sanitized state snapshots. Redaction masks prevent sensitive data leaks. Records cannot be edited or deleted.
            </div>
          </div>

          {/* Audit Filters */}
          <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3">
            <div className="flex items-center gap-2 flex-1 max-w-lg">
              <select
                value={auditActionFilter}
                onChange={(e) => setAuditActionFilter(e.target.value)}
                className="px-3 py-2 rounded-lg bg-slate-900 border border-slate-800 text-xs text-slate-300 focus:outline-none focus:border-purple-500/50"
              >
                <option value="">All Actions</option>
                <option value="USER_CREATED">USER_CREATED</option>
                <option value="USER_UPDATED">USER_UPDATED</option>
                <option value="LOCATION_CREATED">LOCATION_CREATED</option>
                <option value="LOCATION_UPDATED">LOCATION_UPDATED</option>
                <option value="DATA_SOURCE_CREATED">DATA_SOURCE_CREATED</option>
                <option value="DATA_SOURCE_UPDATED">DATA_SOURCE_UPDATED</option>
                <option value="ALERT_RULE_CREATED">ALERT_RULE_CREATED</option>
                <option value="ALERT_RULE_UPDATED">ALERT_RULE_UPDATED</option>
                <option value="ALERT_RULE_DELETED">ALERT_RULE_DELETED</option>
                <option value="SYSTEM_SETTING_UPDATED">SYSTEM_SETTING_UPDATED</option>
              </select>

              <select
                value={auditResourceFilter}
                onChange={(e) => setAuditResourceFilter(e.target.value)}
                className="px-3 py-2 rounded-lg bg-slate-900 border border-slate-800 text-xs text-slate-300 focus:outline-none focus:border-purple-500/50"
              >
                <option value="">All Resource Types</option>
                <option value="USER">USER</option>
                <option value="LOCATION">LOCATION</option>
                <option value="DATA_SOURCE">DATA_SOURCE</option>
                <option value="ALERT_RULE">ALERT_RULE</option>
                <option value="SYSTEM_SETTING">SYSTEM_SETTING</option>
              </select>
            </div>

            <div className="text-xs text-slate-400">
              Total Log Entries: <span className="font-mono text-purple-300 font-bold">{auditTotal}</span>
            </div>
          </div>

          {/* Audit Table */}
          <div className="rounded-xl border border-slate-800 bg-slate-900/60 overflow-hidden">
            <table className="w-full text-left text-xs">
              <thead className="bg-slate-950/60 text-slate-400 font-semibold border-b border-slate-800">
                <tr>
                  <th className="p-3">ID</th>
                  <th className="p-3">Timestamp</th>
                  <th className="p-3">Actor</th>
                  <th className="p-3">Action</th>
                  <th className="p-3">Resource</th>
                  <th className="p-3">Status</th>
                  <th className="p-3">Client IP</th>
                  <th className="p-3 text-right">Details</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-800/60">
                {auditLogs.map((log) => (
                  <tr key={log.id} className="hover:bg-slate-800/30 transition">
                    <td className="p-3 font-mono text-slate-400">{log.id}</td>
                    <td className="p-3 font-mono text-slate-400">
                      {new Date(log.timestamp).toLocaleString()}
                    </td>
                    <td className="p-3 font-semibold text-slate-200">
                      {log.username_snapshot}
                    </td>
                    <td className="p-3">
                      <span className="px-2 py-0.5 rounded font-mono text-[10px] font-semibold bg-slate-800 text-slate-300">
                        {log.action}
                      </span>
                    </td>
                    <td className="p-3 font-mono text-slate-400">
                      {log.resource_type} {log.resource_id ? `#${log.resource_id}` : ''}
                    </td>
                    <td className="p-3">
                      {log.success ? (
                        <span className="px-2 py-0.5 rounded-full text-[10px] font-semibold bg-emerald-500/10 text-emerald-400 border border-emerald-500/20">
                          SUCCESS
                        </span>
                      ) : (
                        <span className="px-2 py-0.5 rounded-full text-[10px] font-semibold bg-rose-500/10 text-rose-400 border border-rose-500/20">
                          FAILED
                        </span>
                      )}
                    </td>
                    <td className="p-3 font-mono text-slate-400">
                      {log.ip_address || '—'}
                    </td>
                    <td className="p-3 text-right">
                      <button
                        onClick={() => setSelectedAuditLog(log)}
                        className="px-2 py-1 rounded bg-slate-800 hover:bg-slate-700 text-slate-300 text-[11px] font-medium transition inline-flex items-center gap-1"
                      >
                        <Eye className="w-3 h-3" />
                        <span>Inspect</span>
                      </button>
                    </td>
                  </tr>
                ))}
                {auditLogs.length === 0 && (
                  <tr>
                    <td colSpan={8} className="p-6 text-center text-slate-500">
                      No audit events found.
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>

          {/* Audit Pagination */}
          <div className="flex items-center justify-between pt-2">
            <button
              onClick={() => setAuditPage((p) => Math.max(1, p - 1))}
              disabled={auditPage <= 1}
              className="px-3 py-1.5 rounded-lg bg-slate-800 hover:bg-slate-700 disabled:opacity-40 text-xs text-slate-300 transition flex items-center gap-1"
            >
              <ChevronLeft className="w-3.5 h-3.5" />
              <span>Previous</span>
            </button>
            <span className="text-xs text-slate-400 font-mono">Page {auditPage}</span>
            <button
              onClick={() => setAuditPage((p) => p + 1)}
              disabled={auditLogs.length < 15}
              className="px-3 py-1.5 rounded-lg bg-slate-800 hover:bg-slate-700 disabled:opacity-40 text-xs text-slate-300 transition flex items-center gap-1"
            >
              <span>Next</span>
              <ChevronRight className="w-3.5 h-3.5" />
            </button>
          </div>
        </div>
      )}

      {/* ===================================================================== */}
      {/* MODAL: ADD USER */}
      {/* ===================================================================== */}
      {showAddUserModal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 backdrop-blur-sm p-4">
          <div className="w-full max-w-md bg-slate-900 border border-slate-800 rounded-2xl p-6 space-y-4 shadow-2xl">
            <h3 className="text-base font-bold text-white">Create New User Account</h3>
            <form onSubmit={handleCreateUser} className="space-y-3 text-xs">
              <div>
                <label className="block text-slate-400 mb-1">Username</label>
                <input
                  type="text"
                  required
                  value={newUsername}
                  onChange={(e) => setNewUsername(e.target.value)}
                  className="w-full px-3 py-2 rounded-lg bg-slate-950 border border-slate-800 text-slate-200"
                  placeholder="e.g. analyst_john"
                />
              </div>

              <div>
                <label className="block text-slate-400 mb-1">Email Address</label>
                <input
                  type="email"
                  required
                  value={newEmail}
                  onChange={(e) => setNewEmail(e.target.value)}
                  className="w-full px-3 py-2 rounded-lg bg-slate-950 border border-slate-800 text-slate-200"
                  placeholder="e.g. john@aeropulse.org"
                />
              </div>

              <div>
                <label className="block text-slate-400 mb-1">Password</label>
                <input
                  type="password"
                  required
                  minLength={8}
                  value={newPassword}
                  onChange={(e) => setNewPassword(e.target.value)}
                  className="w-full px-3 py-2 rounded-lg bg-slate-950 border border-slate-800 text-slate-200"
                  placeholder="Minimum 8 characters"
                />
              </div>

              <div>
                <label className="block text-slate-400 mb-1">Assigned Role</label>
                <select
                  value={newRole}
                  onChange={(e) => setNewRole(e.target.value as UserRole)}
                  className="w-full px-3 py-2 rounded-lg bg-slate-950 border border-slate-800 text-slate-200"
                >
                  <option value="viewer">Viewer (Read-only monitoring)</option>
                  <option value="analyst">Analyst (Analytics, ML & Reports)</option>
                  <option value="admin">Admin (Full system governance)</option>
                </select>
              </div>

              <div className="pt-3 flex items-center justify-end gap-2">
                <button
                  type="button"
                  onClick={() => setShowAddUserModal(false)}
                  className="px-4 py-2 rounded-lg bg-slate-800 hover:bg-slate-700 text-slate-300 font-medium"
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  className="px-4 py-2 rounded-lg bg-purple-600 hover:bg-purple-500 text-white font-semibold"
                >
                  Create User
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* ===================================================================== */}
      {/* MODAL: EDIT USER */}
      {/* ===================================================================== */}
      {showEditUserModal && selectedUser && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 backdrop-blur-sm p-4">
          <div className="w-full max-w-md bg-slate-900 border border-slate-800 rounded-2xl p-6 space-y-4 shadow-2xl">
            <h3 className="text-base font-bold text-white">
              Edit User: <span className="text-purple-400">{selectedUser.username}</span>
            </h3>

            {selectedUser.id === currentUser.id && (
              <div className="p-3 rounded-lg bg-amber-500/10 border border-amber-500/20 text-[11px] text-amber-300">
                Notice: You are editing your currently logged-in account. Self-deactivation and self-demotion are blocked.
              </div>
            )}

            <form onSubmit={handleUpdateUser} className="space-y-3 text-xs">
              <div>
                <label className="block text-slate-400 mb-1">User Role</label>
                <select
                  value={editRole}
                  onChange={(e) => setEditRole(e.target.value as UserRole)}
                  className="w-full px-3 py-2 rounded-lg bg-slate-950 border border-slate-800 text-slate-200"
                >
                  <option value="viewer">Viewer</option>
                  <option value="analyst">Analyst</option>
                  <option value="admin">Admin</option>
                </select>
              </div>

              <div className="flex items-center gap-2 pt-2">
                <input
                  type="checkbox"
                  id="editIsActive"
                  checked={editIsActive}
                  onChange={(e) => setEditIsActive(e.target.checked)}
                  className="rounded border-slate-800 bg-slate-950 text-purple-600 focus:ring-0"
                />
                <label htmlFor="editIsActive" className="text-slate-300">
                  Account Active Status
                </label>
              </div>

              <div className="pt-3 flex items-center justify-end gap-2">
                <button
                  type="button"
                  onClick={() => setShowEditUserModal(false)}
                  className="px-4 py-2 rounded-lg bg-slate-800 hover:bg-slate-700 text-slate-300 font-medium"
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  className="px-4 py-2 rounded-lg bg-purple-600 hover:bg-purple-500 text-white font-semibold"
                >
                  Save Changes
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* ===================================================================== */}
      {/* MODAL: ADD LOCATION */}
      {/* ===================================================================== */}
      {showAddLocationModal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 backdrop-blur-sm p-4">
          <div className="w-full max-w-md bg-slate-900 border border-slate-800 rounded-2xl p-6 space-y-4 shadow-2xl">
            <h3 className="text-base font-bold text-white">Add Monitoring Station</h3>
            <form onSubmit={handleCreateLocation} className="space-y-3 text-xs">
              <div>
                <label className="block text-slate-400 mb-1">Station Name</label>
                <input
                  type="text"
                  required
                  value={locName}
                  onChange={(e) => setLocName(e.target.value)}
                  className="w-full px-3 py-2 rounded-lg bg-slate-950 border border-slate-800 text-slate-200"
                  placeholder="e.g. Connaught Place"
                />
              </div>

              <div className="grid grid-cols-2 gap-2">
                <div>
                  <label className="block text-slate-400 mb-1">City</label>
                  <input
                    type="text"
                    required
                    value={locCity}
                    onChange={(e) => setLocCity(e.target.value)}
                    className="w-full px-3 py-2 rounded-lg bg-slate-950 border border-slate-800 text-slate-200"
                    placeholder="e.g. Delhi"
                  />
                </div>
                <div>
                  <label className="block text-slate-400 mb-1">State</label>
                  <input
                    type="text"
                    required
                    value={locState}
                    onChange={(e) => setLocState(e.target.value)}
                    className="w-full px-3 py-2 rounded-lg bg-slate-950 border border-slate-800 text-slate-200"
                    placeholder="e.g. Delhi"
                  />
                </div>
              </div>

              <div className="grid grid-cols-2 gap-2">
                <div>
                  <label className="block text-slate-400 mb-1">Latitude (-90 to 90)</label>
                  <input
                    type="number"
                    step="any"
                    required
                    value={locLat}
                    onChange={(e) => setLocLat(e.target.value)}
                    className="w-full px-3 py-2 rounded-lg bg-slate-950 border border-slate-800 text-slate-200"
                  />
                </div>
                <div>
                  <label className="block text-slate-400 mb-1">Longitude (-180 to 180)</label>
                  <input
                    type="number"
                    step="any"
                    required
                    value={locLon}
                    onChange={(e) => setLocLon(e.target.value)}
                    className="w-full px-3 py-2 rounded-lg bg-slate-950 border border-slate-800 text-slate-200"
                  />
                </div>
              </div>

              <div>
                <label className="block text-slate-400 mb-1">Description (Optional)</label>
                <input
                  type="text"
                  value={locDesc}
                  onChange={(e) => setLocDesc(e.target.value)}
                  className="w-full px-3 py-2 rounded-lg bg-slate-950 border border-slate-800 text-slate-200"
                  placeholder="Urban commercial zone monitoring"
                />
              </div>

              <div className="pt-3 flex items-center justify-end gap-2">
                <button
                  type="button"
                  onClick={() => setShowAddLocationModal(false)}
                  className="px-4 py-2 rounded-lg bg-slate-800 hover:bg-slate-700 text-slate-300 font-medium"
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  className="px-4 py-2 rounded-lg bg-teal-600 hover:bg-teal-500 text-white font-semibold"
                >
                  Create Station
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* ===================================================================== */}
      {/* MODAL: ADD DATA SOURCE */}
      {/* ===================================================================== */}
      {showAddSourceModal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 backdrop-blur-sm p-4">
          <div className="w-full max-w-md bg-slate-900 border border-slate-800 rounded-2xl p-6 space-y-4 shadow-2xl">
            <h3 className="text-base font-bold text-white">Register Telemetry Data Source</h3>
            <form onSubmit={handleCreateDataSource} className="space-y-3 text-xs">
              <div>
                <label className="block text-slate-400 mb-1">Source Name</label>
                <input
                  type="text"
                  required
                  value={dsName}
                  onChange={(e) => setDsName(e.target.value)}
                  className="w-full px-3 py-2 rounded-lg bg-slate-950 border border-slate-800 text-slate-200"
                  placeholder="e.g. CPCB Central Open Data API"
                />
              </div>

              <div>
                <label className="block text-slate-400 mb-1">Provenance Type (Permanent)</label>
                <select
                  value={dsType}
                  onChange={(e) => setDsType(e.target.value as SourceType)}
                  className="w-full px-3 py-2 rounded-lg bg-slate-950 border border-slate-800 text-slate-200"
                >
                  <option value="API">API (Public / Official Telemetry)</option>
                  <option value="UPLOADED">UPLOADED (Batch CSV / JSON)</option>
                  <option value="SIMULATED">SIMULATED (Mathematical Model)</option>
                  <option value="DEMO">DEMO (Demonstration Feed)</option>
                </select>
                <p className="text-[10px] text-amber-400 mt-1">
                  Provenance type cannot be modified once created.
                </p>
              </div>

              <div>
                <label className="block text-slate-400 mb-1">Provider Agency (Optional)</label>
                <input
                  type="text"
                  value={dsProvider}
                  onChange={(e) => setDsProvider(e.target.value)}
                  className="w-full px-3 py-2 rounded-lg bg-slate-950 border border-slate-800 text-slate-200"
                  placeholder="e.g. CPCB / DPCC"
                />
              </div>

              <div>
                <label className="block text-slate-400 mb-1">Description (Optional)</label>
                <input
                  type="text"
                  value={dsDesc}
                  onChange={(e) => setDsDesc(e.target.value)}
                  className="w-full px-3 py-2 rounded-lg bg-slate-950 border border-slate-800 text-slate-200"
                />
              </div>

              <div className="pt-3 flex items-center justify-end gap-2">
                <button
                  type="button"
                  onClick={() => setShowAddSourceModal(false)}
                  className="px-4 py-2 rounded-lg bg-slate-800 hover:bg-slate-700 text-slate-300 font-medium"
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  className="px-4 py-2 rounded-lg bg-blue-600 hover:bg-blue-500 text-white font-semibold"
                >
                  Register Source
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* ===================================================================== */}
      {/* MODAL: EDIT SYSTEM SETTING */}
      {/* ===================================================================== */}
      {editingSetting && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 backdrop-blur-sm p-4">
          <div className="w-full max-w-md bg-slate-900 border border-slate-800 rounded-2xl p-6 space-y-4 shadow-2xl">
            <h3 className="text-base font-bold text-white">
              Configure Setting: <span className="font-mono text-purple-400">{editingSetting.key}</span>
            </h3>

            <p className="text-xs text-slate-400">{editingSetting.description}</p>

            <form onSubmit={handleSaveSetting} className="space-y-3 text-xs">
              <div>
                <label className="block text-slate-400 mb-1">
                  Parameter Value ({editingSetting.value_type})
                </label>
                <input
                  type="text"
                  required
                  value={settingValueInput}
                  onChange={(e) => setSettingValueInput(e.target.value)}
                  className="w-full px-3 py-2 rounded-lg bg-slate-950 border border-slate-800 text-slate-200 font-mono"
                />
              </div>

              {editingSetting.key === 'prediction_forecast_horizons_hours' && (
                <div className="p-2.5 rounded-lg bg-indigo-500/10 border border-indigo-500/20 text-[11px] text-indigo-300">
                  Allowed subset: [1, 3, 6, 12, 24]. E.g. <code className="font-mono">[1, 3, 6, 12, 24]</code>
                </div>
              )}

              <div className="pt-3 flex items-center justify-end gap-2">
                <button
                  type="button"
                  onClick={() => setEditingSetting(null)}
                  className="px-4 py-2 rounded-lg bg-slate-800 hover:bg-slate-700 text-slate-300 font-medium"
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  className="px-4 py-2 rounded-lg bg-purple-600 hover:bg-purple-500 text-white font-semibold"
                >
                  Update Setting
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* ===================================================================== */}
      {/* MODAL: INSPECT AUDIT LOG */}
      {/* ===================================================================== */}
      {selectedAuditLog && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 backdrop-blur-sm p-4">
          <div className="w-full max-w-2xl bg-slate-900 border border-slate-800 rounded-2xl p-6 space-y-4 shadow-2xl max-h-[85vh] overflow-y-auto">
            <div className="flex items-center justify-between pb-3 border-b border-slate-800">
              <div className="flex items-center gap-2">
                <FileText className="w-5 h-5 text-purple-400" />
                <h3 className="text-base font-bold text-white">
                  Audit Record #{selectedAuditLog.id}
                </h3>
              </div>
              <button
                onClick={() => setSelectedAuditLog(null)}
                className="text-slate-400 hover:text-white text-xs"
              >
                Close
              </button>
            </div>

            <div className="grid grid-cols-2 gap-3 text-xs">
              <div className="p-3 rounded-lg bg-slate-950 border border-slate-800">
                <span className="text-[10px] text-slate-500 uppercase font-semibold block">Timestamp</span>
                <span className="font-mono text-slate-200">
                  {new Date(selectedAuditLog.timestamp).toLocaleString()}
                </span>
              </div>
              <div className="p-3 rounded-lg bg-slate-950 border border-slate-800">
                <span className="text-[10px] text-slate-500 uppercase font-semibold block">Actor</span>
                <span className="font-semibold text-slate-200">
                  {selectedAuditLog.username_snapshot} (ID: {selectedAuditLog.user_id ?? 'None'})
                </span>
              </div>
              <div className="p-3 rounded-lg bg-slate-950 border border-slate-800">
                <span className="text-[10px] text-slate-500 uppercase font-semibold block">Action</span>
                <span className="font-mono text-purple-300">{selectedAuditLog.action}</span>
              </div>
              <div className="p-3 rounded-lg bg-slate-950 border border-slate-800">
                <span className="text-[10px] text-slate-500 uppercase font-semibold block">Target</span>
                <span className="font-mono text-teal-300">
                  {selectedAuditLog.resource_type} {selectedAuditLog.resource_id ? `#${selectedAuditLog.resource_id}` : ''}
                </span>
              </div>
              <div className="p-3 rounded-lg bg-slate-950 border border-slate-800">
                <span className="text-[10px] text-slate-500 uppercase font-semibold block">Client IP</span>
                <span className="font-mono text-slate-300">{selectedAuditLog.ip_address || 'None'}</span>
              </div>
              <div className="p-3 rounded-lg bg-slate-950 border border-slate-800">
                <span className="text-[10px] text-slate-500 uppercase font-semibold block">User Agent</span>
                <span className="font-mono text-slate-400 truncate block">
                  {selectedAuditLog.user_agent || 'None'}
                </span>
              </div>
            </div>

            <div className="space-y-1">
              <span className="text-xs text-slate-400 font-semibold">Description</span>
              <p className="text-xs text-slate-300 p-2.5 rounded-lg bg-slate-950 border border-slate-800">
                {selectedAuditLog.description}
              </p>
            </div>

            {/* Before / After Snapshots */}
            <div className="grid grid-cols-1 md:grid-cols-2 gap-3 text-xs">
              <div>
                <span className="text-[11px] text-slate-400 font-semibold mb-1 block">Old State Snapshot</span>
                <pre className="p-3 rounded-lg bg-slate-950 border border-slate-800 font-mono text-[11px] text-slate-300 overflow-x-auto max-h-48">
                  {selectedAuditLog.old_value
                    ? JSON.stringify(selectedAuditLog.old_value, null, 2)
                    : 'None (Created / Initial)'}
                </pre>
              </div>
              <div>
                <span className="text-[11px] text-slate-400 font-semibold mb-1 block">New State Snapshot</span>
                <pre className="p-3 rounded-lg bg-slate-950 border border-slate-800 font-mono text-[11px] text-slate-300 overflow-x-auto max-h-48">
                  {selectedAuditLog.new_value
                    ? JSON.stringify(selectedAuditLog.new_value, null, 2)
                    : 'None (Deleted)'}
                </pre>
              </div>
            </div>

            {selectedAuditLog.metadata_json && (
              <div>
                <span className="text-[11px] text-slate-400 font-semibold mb-1 block">Metadata</span>
                <pre className="p-3 rounded-lg bg-slate-950 border border-slate-800 font-mono text-[11px] text-slate-300 overflow-x-auto">
                  {JSON.stringify(selectedAuditLog.metadata_json, null, 2)}
                </pre>
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
};
