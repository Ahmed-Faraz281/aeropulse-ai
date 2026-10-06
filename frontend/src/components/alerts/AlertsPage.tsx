import React, { useState, useEffect, useCallback } from 'react';
import type { User } from '../../types/auth';
import type { Location } from '../../types/air_quality';
import type {
  Alert,
  AlertRule,
  AlertRuleCreate,
  AlertSeverity,
  AlertType,
} from '../../types/alert';
import { getLocations } from '../../services/air_quality';
import {
  acknowledgeAlert,
  createAlertRule,
  evaluateLocationAlerts,
  getActiveAlerts,
  getAlertRules,
  getAlerts,
  resolveAlert,
  updateAlertRule,
} from '../../services/alert';
import {
  Bell,
  AlertTriangle,
  CheckCircle2,
  ShieldAlert,
  ShieldCheck,
  RefreshCw,
  Plus,
  Filter,
  Clock,
  Info,
  Sliders,
} from 'lucide-react';

interface AlertsPageProps {
  currentUser: User;
  onNavigateToTab?: (tabId: string) => void;
  onNavigateToDashboard?: (locationId: number) => void;
}

const SEVERITY_COLORS: Record<AlertSeverity, { bg: string; text: string; border: string; dot: string }> = {
  CRITICAL: {
    bg: 'bg-purple-950/40',
    text: 'text-purple-400',
    border: 'border-purple-500/40',
    dot: 'bg-purple-500',
  },
  HIGH: {
    bg: 'bg-rose-950/40',
    text: 'text-rose-400',
    border: 'border-rose-500/40',
    dot: 'bg-rose-500',
  },
  WARNING: {
    bg: 'bg-amber-950/40',
    text: 'text-amber-400',
    border: 'border-amber-500/40',
    dot: 'bg-amber-500',
  },
  INFO: {
    bg: 'bg-indigo-950/40',
    text: 'text-indigo-400',
    border: 'border-indigo-500/40',
    dot: 'bg-indigo-500',
  },
};

const ALERT_TYPE_LABELS: Record<AlertType, string> = {
  AQI_THRESHOLD: 'AQI Threshold Exceedance',
  SUSTAINED_HIGH_AQI: 'Sustained Elevated Pollution',
  RAPID_INCREASE: 'Rapid AQI Surge',
  PREDICTED_THRESHOLD: 'Predicted AQI Forecast Alert',
  CATEGORY_CHANGE: 'Category Deterioration',
};

export const AlertsPage: React.FC<AlertsPageProps> = ({
  currentUser,
}) => {
  const [locations, setLocations] = useState<Location[]>([]);
  const [selectedLocationId, setSelectedLocationId] = useState<number | null>(null);
  const [severityFilter, setSeverityFilter] = useState<string>('ALL');
  const [activeAlerts, setActiveAlerts] = useState<Alert[]>([]);
  const [alertHistory, setAlertHistory] = useState<Alert[]>([]);
  const [rules, setRules] = useState<AlertRule[]>([]);

  const [loading, setLoading] = useState<boolean>(true);
  const [evaluating, setEvaluating] = useState<boolean>(false);
  const [message, setMessage] = useState<string | null>(null);
  const [errorMsg, setErrorMsg] = useState<string | null>(null);

  // Admin rule form
  const [showRuleModal, setShowRuleModal] = useState<boolean>(false);
  const [newRule, setNewRule] = useState<AlertRuleCreate>({
    name: '',
    alert_type: 'AQI_THRESHOLD',
    threshold: 201,
    duration_hours: 2.0,
    window_hours: 2.0,
    severity: 'HIGH',
    enabled: true,
  });

  const isAdmin = currentUser.role === 'admin';
  const canOperate = currentUser.role === 'admin' || currentUser.role === 'analyst';

  const refreshAlerts = useCallback(async () => {
    try {
      setErrorMsg(null);
      const [active, history] = await Promise.all([
        getActiveAlerts(selectedLocationId || undefined),
        getAlerts({
          location_id: selectedLocationId || undefined,
          limit: 30,
        }),
      ]);
      setActiveAlerts(active);
      setAlertHistory(history.filter((a) => a.status === 'RESOLVED' || a.status === 'DISMISSED'));
    } catch (err: unknown) {
      console.warn('Could not refresh alerts:', err);
    }
  }, [selectedLocationId]);

  const loadInitialData = useCallback(async () => {
    try {
      setLoading(true);
      const [locs, rList] = await Promise.all([getLocations(), getAlertRules()]);
      setLocations(locs);
      setRules(rList);
      await refreshAlerts();
    } catch (err: unknown) {
      const errorObj = err as { response?: { data?: { detail?: string } } };
      setErrorMsg(errorObj?.response?.data?.detail || 'Failed to load alert system.');
    } finally {
      setLoading(false);
    }
  }, [refreshAlerts]);

  useEffect(() => {
    let ignore = false;
    Promise.resolve().then(() => {
      if (!ignore) {
        loadInitialData();
      }
    });
    return () => {
      ignore = true;
    };
  }, [loadInitialData]);

  useEffect(() => {
    let ignore = false;
    Promise.resolve().then(() => {
      if (!ignore) {
        refreshAlerts();
      }
    });
    return () => {
      ignore = true;
    };
  }, [refreshAlerts]);

  const handleEvaluate = async () => {
    if (!selectedLocationId || !canOperate) return;
    try {
      setEvaluating(true);
      setErrorMsg(null);
      setMessage(null);
      const res = await evaluateLocationAlerts(selectedLocationId);
      setMessage(
        `Evaluation complete: ${res.alerts_created} alerts processed (${res.alerts_active} active).`
      );
      await refreshAlerts();
    } catch (err: any) {
      setErrorMsg(err?.response?.data?.detail || 'Evaluation failed.');
    } finally {
      setEvaluating(false);
    }
  };

  const handleAcknowledge = async (alertId: number) => {
    if (!canOperate) return;
    try {
      await acknowledgeAlert(alertId);
      await refreshAlerts();
    } catch (err: any) {
      setErrorMsg(err?.response?.data?.detail || 'Failed to acknowledge alert.');
    }
  };

  const handleResolve = async (alertId: number) => {
    if (!canOperate) return;
    try {
      await resolveAlert(alertId);
      await refreshAlerts();
    } catch (err: any) {
      setErrorMsg(err?.response?.data?.detail || 'Failed to resolve alert.');
    }
  };

  const handleToggleRule = async (rule: AlertRule) => {
    if (!isAdmin) return;
    try {
      await updateAlertRule(rule.id, { enabled: !rule.enabled });
      const updated = await getAlertRules();
      setRules(updated);
    } catch (err: any) {
      setErrorMsg(err?.response?.data?.detail || 'Failed to update rule status.');
    }
  };

  const handleCreateRule = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!isAdmin) return;
    try {
      await createAlertRule(newRule);
      setShowRuleModal(false);
      const updated = await getAlertRules();
      setRules(updated);
      setNewRule({
        name: '',
        alert_type: 'AQI_THRESHOLD',
        threshold: 201,
        severity: 'HIGH',
        enabled: true,
      });
    } catch (err: any) {
      setErrorMsg(err?.response?.data?.detail || 'Failed to create rule.');
    }
  };

  const filteredActiveAlerts = activeAlerts.filter((a) => {
    if (severityFilter !== 'ALL' && a.severity !== severityFilter) return false;
    return true;
  });

  const hasSimulatedAlert = activeAlerts.some((a) => a.source_type === 'SIMULATED');

  return (
    <div className="space-y-6 pb-12">
      {/* Top Header */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 border-b border-slate-800 pb-4">
        <div>
          <div className="flex items-center gap-2">
            <Bell className="w-6 h-6 text-rose-400" />
            <h1 className="text-2xl font-bold text-white tracking-tight">
              AeroPulse AI — Automated Alert & Threshold Engine
            </h1>
          </div>
          <p className="text-sm text-slate-400 mt-1">
            Real-time threshold surveillance, rapid-rise alerts, sustained episode tracking, and predictive warnings
          </p>
        </div>

        {/* Station Filter & Evaluation Trigger */}
        <div className="flex items-center gap-3">
          <label className="text-xs font-medium text-slate-400 uppercase tracking-wider">
            Station:
          </label>
          <select
            className="bg-slate-900 border border-slate-700 text-slate-200 text-sm rounded-lg px-3 py-2 focus:ring-2 focus:ring-rose-500 focus:outline-none"
            value={selectedLocationId || ''}
            onChange={(e) => setSelectedLocationId(e.target.value ? Number(e.target.value) : null)}
            disabled={loading}
          >
            <option value="">All Monitored Stations</option>
            {locations.map((loc) => (
              <option key={loc.id} value={loc.id}>
                {loc.name} ({loc.city})
              </option>
            ))}
          </select>

          <button
            onClick={handleEvaluate}
            disabled={!canOperate || evaluating || !selectedLocationId}
            className={`px-3 py-2 rounded-lg text-xs font-semibold flex items-center gap-1.5 transition ${
              canOperate && selectedLocationId
                ? 'bg-rose-600 hover:bg-rose-500 text-white shadow-md shadow-rose-600/20'
                : 'bg-slate-800 text-slate-500 border border-slate-700 cursor-not-allowed'
            }`}
            title={selectedLocationId ? 'Evaluate rules for selected station' : 'Select a station to evaluate'}
          >
            <RefreshCw className={`w-3.5 h-3.5 ${evaluating ? 'animate-spin' : ''}`} />
            <span>Evaluate Station</span>
          </button>
        </div>
      </div>

      {/* Mandatory Provenance & Factual Transparency Notice */}
      <div className="bg-slate-900/70 border border-slate-800 rounded-xl p-4 flex items-start gap-3">
        <Info className="w-5 h-5 text-indigo-400 shrink-0 mt-0.5" />
        <div className="text-xs text-slate-300 space-y-1">
          <p className="font-semibold text-indigo-300">
            Automated Alert Rule & Provenance Policy
          </p>
          <p className="text-slate-400">
            Alert notifications are triggered strictly by objective, deterministic thresholds configured
            against observed telemetry or forecast models. Forecast alerts are explicitly labeled as statistical
            projections and never presented as physical measurements.
          </p>
        </div>
      </div>

      {/* Simulated Data Alert Warning */}
      {hasSimulatedAlert && (
        <div className="bg-amber-950/40 border border-amber-500/40 rounded-xl p-4 flex items-start gap-3">
          <AlertTriangle className="w-5 h-5 text-amber-400 shrink-0 mt-0.5" />
          <div className="text-xs text-amber-200">
            <p className="font-semibold text-amber-300">
              One or more active alerts originated from SIMULATED data
            </p>
            <p className="text-amber-300/80 mt-0.5">
              These alerts reflect simulated scenario inputs rather than physical atmospheric measurements.
            </p>
          </div>
        </div>
      )}

      {/* Status or Error Alerts */}
      {message && (
        <div className="bg-emerald-950/40 border border-emerald-500/40 rounded-xl p-4 flex items-start gap-3">
          <CheckCircle2 className="w-5 h-5 text-emerald-400 shrink-0 mt-0.5" />
          <div className="text-xs text-emerald-300">{message}</div>
        </div>
      )}
      {errorMsg && (
        <div className="bg-rose-950/40 border border-rose-500/40 rounded-xl p-4 flex items-start gap-3">
          <AlertTriangle className="w-5 h-5 text-rose-400 shrink-0 mt-0.5" />
          <div className="text-xs text-rose-300">{errorMsg}</div>
        </div>
      )}

      {/* Active Alerts Section */}
      <div className="space-y-4">
        <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3">
          <div className="flex items-center gap-2">
            <ShieldAlert className="w-5 h-5 text-rose-400" />
            <h2 className="text-base font-bold text-white">
              Active Alerts ({filteredActiveAlerts.length})
            </h2>
          </div>

          {/* Severity Filter Pills */}
          <div className="flex items-center gap-1.5 flex-wrap">
            <Filter className="w-3.5 h-3.5 text-slate-500 mr-1" />
            {['ALL', 'CRITICAL', 'HIGH', 'WARNING', 'INFO'].map((sev) => (
              <button
                key={sev}
                onClick={() => setSeverityFilter(sev)}
                className={`px-2.5 py-1 rounded text-xs font-semibold transition ${
                  severityFilter === sev
                    ? 'bg-slate-700 text-white border border-slate-600'
                    : 'bg-slate-900 text-slate-400 border border-slate-800 hover:text-slate-200'
                }`}
              >
                {sev}
              </button>
            ))}
          </div>
        </div>

        {filteredActiveAlerts.length > 0 ? (
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            {filteredActiveAlerts.map((alt) => {
              const sev = SEVERITY_COLORS[alt.severity] || SEVERITY_COLORS.INFO;
              return (
                <div
                  key={alt.id}
                  className={`p-5 rounded-xl border ${sev.bg} ${sev.border} flex flex-col justify-between space-y-4 transition-all hover:border-slate-600`}
                >
                  <div className="space-y-2">
                    <div className="flex items-start justify-between gap-2">
                      <div className="flex items-center gap-2">
                        <span className={`w-2.5 h-2.5 rounded-full ${sev.dot}`} />
                        <span className={`text-xs font-bold uppercase tracking-wider ${sev.text}`}>
                          {alt.severity}
                        </span>
                        <span className="text-[11px] text-slate-500 font-mono">
                          • {ALERT_TYPE_LABELS[alt.alert_type]}
                        </span>
                      </div>

                      <div className="flex items-center gap-1.5">
                        {alt.is_prediction && (
                          <span className="px-2 py-0.5 rounded text-[10px] font-mono bg-purple-900/50 text-purple-300 border border-purple-700/50">
                            FORECAST
                          </span>
                        )}
                        <span
                          className={`px-2 py-0.5 rounded text-[10px] font-mono border ${
                            alt.source_type === 'SIMULATED'
                              ? 'bg-amber-950 text-amber-300 border-amber-800'
                              : 'bg-slate-800 text-slate-300 border-slate-700'
                          }`}
                        >
                          {alt.source_type}
                        </span>
                        <span className="px-2 py-0.5 rounded text-[10px] font-semibold bg-slate-800 text-slate-300 border border-slate-700">
                          {alt.status}
                        </span>
                      </div>
                    </div>

                    <h3 className="text-sm font-bold text-white">{alt.title}</h3>
                    <p className="text-xs text-slate-300 leading-relaxed">{alt.message}</p>
                  </div>

                  <div className="pt-3 border-t border-slate-800/80 flex flex-col sm:flex-row sm:items-center justify-between gap-3 text-xs text-slate-400">
                    <div>
                      <span>Observed: </span>
                      <span className="font-mono text-white font-semibold">
                        {alt.observed_value != null ? Math.round(alt.observed_value) : '--'}
                      </span>{' '}
                      <span className="text-slate-500">
                        (Cutoff: {Math.round(alt.threshold_value)})
                      </span>
                    </div>

                    <div className="flex items-center gap-2">
                      <span className="text-[11px] text-slate-500 font-mono">
                        {new Date(alt.detected_at).toLocaleTimeString([], {
                          hour: '2-digit',
                          minute: '2-digit',
                        })}
                      </span>

                      {canOperate && (
                        <div className="flex items-center gap-1.5 ml-2">
                          {alt.status === 'ACTIVE' && (
                            <button
                              onClick={() => handleAcknowledge(alt.id)}
                              className="px-2.5 py-1 rounded bg-slate-800 hover:bg-slate-700 text-slate-300 border border-slate-700 text-[11px] font-semibold transition"
                            >
                              Acknowledge
                            </button>
                          )}
                          <button
                            onClick={() => handleResolve(alt.id)}
                            className="px-2.5 py-1 rounded bg-emerald-950 hover:bg-emerald-900 text-emerald-300 border border-emerald-800 text-[11px] font-semibold transition"
                          >
                            Resolve
                          </button>
                        </div>
                      )}
                    </div>
                  </div>
                </div>
              );
            })}
          </div>
        ) : (
          <div className="p-8 rounded-xl border border-dashed border-slate-800 bg-slate-900/30 text-center text-slate-500 text-xs">
            <ShieldCheck className="w-8 h-8 text-emerald-500 mx-auto mb-2 opacity-80" />
            <p className="font-semibold text-slate-300">All Clear — No Active Threshold Alerts</p>
            <p className="text-[11px] text-slate-500 mt-1">
              Monitored atmospheric readings are currently within configured bounds.
            </p>
          </div>
        )}
      </div>

      {/* Configurable Alert Rules Panel (Admin Only / Viewable) */}
      <div className="bg-slate-900 border border-slate-800 rounded-xl p-5 space-y-4">
        <div className="flex items-center justify-between border-b border-slate-800 pb-3">
          <div className="flex items-center gap-2">
            <Sliders className="w-4 h-4 text-indigo-400" />
            <h3 className="text-sm font-semibold text-white">
              Surveillance Rules & Threshold Configuration
            </h3>
          </div>

          {isAdmin && (
            <button
              onClick={() => setShowRuleModal(true)}
              className="px-3 py-1.5 rounded-lg bg-indigo-600 hover:bg-indigo-500 text-white text-xs font-semibold flex items-center gap-1 transition"
            >
              <Plus className="w-3.5 h-3.5" />
              <span>Create Rule</span>
            </button>
          )}
        </div>

        <div className="overflow-x-auto">
          <table className="w-full text-left text-xs text-slate-300">
            <thead className="bg-slate-950/60 text-slate-400 uppercase tracking-wider text-[10px] border-b border-slate-800">
              <tr>
                <th className="px-4 py-2.5">Rule Name</th>
                <th className="px-4 py-2.5">Type</th>
                <th className="px-4 py-2.5">Threshold</th>
                <th className="px-4 py-2.5">Duration / Window</th>
                <th className="px-4 py-2.5">Severity</th>
                <th className="px-4 py-2.5">Status</th>
                {isAdmin && <th className="px-4 py-2.5 text-right">Action</th>}
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-800/60 font-mono text-[11px]">
              {rules.map((r) => (
                <tr key={r.id} className="hover:bg-slate-800/30 transition">
                  <td className="px-4 py-2.5 font-sans font-semibold text-white">
                    {r.name}
                  </td>
                  <td className="px-4 py-2.5 text-slate-400">{r.alert_type}</td>
                  <td className="px-4 py-2.5 text-indigo-400">{r.threshold}</td>
                  <td className="px-4 py-2.5 text-slate-400">
                    {r.duration_hours ? `${r.duration_hours}h duration` : r.window_hours ? `${r.window_hours}h window` : '--'}
                  </td>
                  <td className="px-4 py-2.5">
                    <span
                      className={`px-1.5 py-0.5 rounded text-[10px] font-bold ${
                        SEVERITY_COLORS[r.severity]?.text || 'text-slate-300'
                      }`}
                    >
                      {r.severity}
                    </span>
                  </td>
                  <td className="px-4 py-2.5">
                    <span
                      className={`px-2 py-0.5 rounded text-[10px] font-semibold ${
                        r.enabled
                          ? 'bg-emerald-500/10 text-emerald-400 border border-emerald-500/30'
                          : 'bg-slate-800 text-slate-500'
                      }`}
                    >
                      {r.enabled ? 'ENABLED' : 'DISABLED'}
                    </span>
                  </td>
                  {isAdmin && (
                    <td className="px-4 py-2.5 text-right">
                      <button
                        onClick={() => handleToggleRule(r)}
                        className="text-[11px] font-sans font-medium text-slate-400 hover:text-white transition underline"
                      >
                        {r.enabled ? 'Disable' : 'Enable'}
                      </button>
                    </td>
                  )}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      {/* Create Rule Modal */}
      {showRuleModal && (
        <div className="fixed inset-0 bg-slate-950/80 backdrop-blur-sm z-50 flex items-center justify-center p-4">
          <div className="bg-slate-900 border border-slate-800 rounded-2xl max-w-md w-full p-6 space-y-4 shadow-2xl">
            <div className="flex items-center justify-between border-b border-slate-800 pb-3">
              <h3 className="text-base font-bold text-white">Create Surveillance Rule</h3>
              <button
                onClick={() => setShowRuleModal(false)}
                className="text-slate-400 hover:text-white text-sm"
              >
                ✕
              </button>
            </div>

            <form onSubmit={handleCreateRule} className="space-y-3 text-xs">
              <div>
                <label className="block text-slate-400 mb-1">Rule Name</label>
                <input
                  type="text"
                  required
                  value={newRule.name}
                  onChange={(e) => setNewRule({ ...newRule, name: e.target.value })}
                  placeholder="e.g. Severe Stagnation Alert"
                  className="w-full bg-slate-950 border border-slate-700 rounded-lg px-3 py-2 text-white focus:outline-none focus:ring-2 focus:ring-indigo-500"
                />
              </div>

              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="block text-slate-400 mb-1">Alert Type</label>
                  <select
                    value={newRule.alert_type}
                    onChange={(e) =>
                      setNewRule({ ...newRule, alert_type: e.target.value as AlertType })
                    }
                    className="w-full bg-slate-950 border border-slate-700 rounded-lg px-2 py-2 text-white"
                  >
                    <option value="AQI_THRESHOLD">AQI Threshold</option>
                    <option value="SUSTAINED_HIGH_AQI">Sustained AQI</option>
                    <option value="RAPID_INCREASE">Rapid Rise</option>
                    <option value="PREDICTED_THRESHOLD">Forecast Alert</option>
                    <option value="CATEGORY_CHANGE">Category Change</option>
                  </select>
                </div>

                <div>
                  <label className="block text-slate-400 mb-1">Cutoff Threshold</label>
                  <input
                    type="number"
                    required
                    value={newRule.threshold}
                    onChange={(e) =>
                      setNewRule({ ...newRule, threshold: Number(e.target.value) })
                    }
                    className="w-full bg-slate-950 border border-slate-700 rounded-lg px-3 py-2 text-white"
                  />
                </div>
              </div>

              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="block text-slate-400 mb-1">Severity</label>
                  <select
                    value={newRule.severity}
                    onChange={(e) =>
                      setNewRule({ ...newRule, severity: e.target.value as AlertSeverity })
                    }
                    className="w-full bg-slate-950 border border-slate-700 rounded-lg px-2 py-2 text-white"
                  >
                    <option value="INFO">INFO</option>
                    <option value="WARNING">WARNING</option>
                    <option value="HIGH">HIGH</option>
                    <option value="CRITICAL">CRITICAL</option>
                  </select>
                </div>

                <div>
                  <label className="block text-slate-400 mb-1">Duration / Window (h)</label>
                  <input
                    type="number"
                    step="0.5"
                    value={newRule.duration_hours || 2.0}
                    onChange={(e) =>
                      setNewRule({
                        ...newRule,
                        duration_hours: Number(e.target.value),
                        window_hours: Number(e.target.value),
                      })
                    }
                    className="w-full bg-slate-950 border border-slate-700 rounded-lg px-3 py-2 text-white"
                  />
                </div>
              </div>

              <div className="flex justify-end gap-2 pt-3 border-t border-slate-800">
                <button
                  type="button"
                  onClick={() => setShowRuleModal(false)}
                  className="px-4 py-2 rounded-lg bg-slate-800 text-slate-300 hover:bg-slate-700"
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  className="px-4 py-2 rounded-lg bg-indigo-600 text-white hover:bg-indigo-500 font-semibold"
                >
                  Save Rule
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* Historical Alerts Log Table */}
      <div className="bg-slate-900 border border-slate-800 rounded-xl overflow-hidden">
        <div className="p-4 border-b border-slate-800 flex items-center justify-between">
          <div className="flex items-center gap-2">
            <Clock className="w-4 h-4 text-slate-400" />
            <h3 className="text-sm font-semibold text-white">
              Alert Audit Log (Resolved & Historical)
            </h3>
          </div>
          <span className="text-xs text-slate-500">Last 30 alerts</span>
        </div>

        <div className="overflow-x-auto">
          <table className="w-full text-left text-xs text-slate-300">
            <thead className="bg-slate-950/60 text-slate-400 uppercase tracking-wider text-[10px] border-b border-slate-800">
              <tr>
                <th className="px-4 py-3">Detected At</th>
                <th className="px-4 py-3">Severity</th>
                <th className="px-4 py-3">Type</th>
                <th className="px-4 py-3">Title</th>
                <th className="px-4 py-3">Observed / Cutoff</th>
                <th className="px-4 py-3">Resolved At</th>
                <th className="px-4 py-3">Source</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-800/60">
              {alertHistory.length > 0 ? (
                alertHistory.map((alt) => (
                  <tr key={alt.id} className="hover:bg-slate-800/30 transition">
                    <td className="px-4 py-3 font-mono text-slate-400">
                      {new Date(alt.detected_at).toLocaleString([], {
                        month: 'short',
                        day: 'numeric',
                        hour: '2-digit',
                        minute: '2-digit',
                      })}
                    </td>
                    <td className="px-4 py-3 font-bold">
                      <span className={SEVERITY_COLORS[alt.severity]?.text}>
                        {alt.severity}
                      </span>
                    </td>
                    <td className="px-4 py-3 text-slate-400 text-[11px]">
                      {ALERT_TYPE_LABELS[alt.alert_type]}
                    </td>
                    <td className="px-4 py-3 text-white font-medium">{alt.title}</td>
                    <td className="px-4 py-3 font-mono text-slate-300">
                      {alt.observed_value != null ? Math.round(alt.observed_value) : '--'} /{' '}
                      {Math.round(alt.threshold_value)}
                    </td>
                    <td className="px-4 py-3 font-mono text-slate-400">
                      {alt.resolved_at
                        ? new Date(alt.resolved_at).toLocaleTimeString([], {
                            hour: '2-digit',
                            minute: '2-digit',
                          })
                        : '--'}
                    </td>
                    <td className="px-4 py-3">
                      <span
                        className={`text-[9px] font-mono px-1.5 py-0.5 rounded border ${
                          alt.source_type === 'SIMULATED'
                            ? 'bg-amber-950 text-amber-300 border-amber-800'
                            : 'bg-slate-800 text-slate-400 border-slate-700'
                        }`}
                      >
                        {alt.source_type}
                      </span>
                    </td>
                  </tr>
                ))
              ) : (
                <tr>
                  <td colSpan={7} className="px-4 py-8 text-center text-slate-500 text-xs">
                    No resolved alert history available.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
};
