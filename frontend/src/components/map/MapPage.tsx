import React, { useState, useEffect, useCallback } from 'react';
import type { Location } from '../../types/air_quality';
import type { AQIResponse } from '../../types/aqi';
import { getLocations, getCurrentReading } from '../../services/air_quality';
import { getLatestAQI } from '../../services/aqi';
import { StationMap, type StationMapItem } from './StationMap';
import { StationList } from './StationList';
import { MapLegend } from './MapLegend';
import {
  resolveLocationWorkflow,
  type LocationWorkflowResponse,
} from '../../services/locationWorkflow';
import {
  MapPin,
  RefreshCw,
  Search,
  Filter,
  AlertTriangle,
  Layers,
  ShieldCheck,
  ShieldAlert,
  Info,
  LocateFixed,
  Loader2,
  CheckCircle2,
  XCircle,
  X,
} from 'lucide-react';

interface MapPageProps {
  onNavigateToDashboard: (locationId: number) => void;
}

const CATEGORY_FILTERS = [
  'All',
  'Good',
  'Satisfactory',
  'Moderate',
  'Poor',
  'Very Poor',
  'Severe',
] as const;

const SOURCE_FILTERS = ['All', 'API', 'UPLOADED', 'SIMULATED', 'DEMO'] as const;

export const MapPage: React.FC<MapPageProps> = ({ onNavigateToDashboard }) => {
  const [stations, setStations] = useState<StationMapItem[]>([]);
  const [selectedStationId, setSelectedStationId] = useState<number | null>(null);
  const [loading, setLoading] = useState<boolean>(true);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [lastUpdated, setLastUpdated] = useState<string>('');

  // Filters State
  const [searchQuery, setSearchQuery] = useState<string>('');
  const [categoryFilter, setCategoryFilter] = useState<string>('All');
  const [sourceFilter, setSourceFilter] = useState<string>('All');

  // Location Workflow State
  const [userLocation, setUserLocation] = useState<{ latitude: number; longitude: number } | null>(
    null
  );
  const [resolvedDistanceKm, setResolvedDistanceKm] = useState<number | null>(null);
  const [workflowState, setWorkflowState] = useState<
    'IDLE' | 'DETECTING_LOCATION' | 'FINDING_STATION' | 'SUCCESS' | 'NO_STATION' | 'ERROR'
  >('IDLE');
  const [workflowResult, setWorkflowResult] = useState<LocationWorkflowResponse | null>(null);
  const [workflowError, setWorkflowError] = useState<string | null>(null);
  const [showWorkflowNotice, setShowWorkflowNotice] = useState<boolean>(true);

  // Fetch all stations with latest AQI and reading
  const loadMapData = useCallback(async () => {
    setLoading(true);
    setErrorMessage(null);

    try {
      const locList: Location[] = await getLocations();

      if (locList.length === 0) {
        setStations([]);
        setLoading(false);
        return;
      }

      // Fetch AQI and Current Reading for each station in parallel
      const stationResults = await Promise.all(
        locList.map(async (loc) => {
          let aqiData: AQIResponse | null = null;
          let sourceType = 'SIMULATED';

          try {
            const aqiRes = await getLatestAQI(loc.id);
            aqiData = aqiRes;
          } catch {
            aqiData = null;
          }

          try {
            const readingRes = await getCurrentReading(loc.id);
            if (readingRes?.reading?.source_type) {
              sourceType = readingRes.reading.source_type;
            }
          } catch {
            // fallback
          }

          return {
            location: loc,
            aqiData,
            sourceType,
          };
        })
      );

      setStations(stationResults);
      setLastUpdated(new Date().toLocaleTimeString());
    } catch {
      setErrorMessage('Unable to load monitoring locations. Please check backend connection.');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    let ignore = false;
    Promise.resolve().then(() => {
      if (!ignore) {
        loadMapData();
      }
    });
    return () => {
      ignore = true;
    };
  }, [loadMapData]);

  // Handle "Use My Location" in Map View
  const handleUseMyLocation = useCallback(() => {
    if (!navigator.geolocation) {
      setWorkflowState('ERROR');
      setWorkflowError('Geolocation is not supported by your browser.');
      setShowWorkflowNotice(true);
      return;
    }

    setWorkflowState('DETECTING_LOCATION');
    setWorkflowError(null);
    setShowWorkflowNotice(true);

    navigator.geolocation.getCurrentPosition(
      async (position) => {
        setWorkflowState('FINDING_STATION');
        const { latitude, longitude, accuracy } = position.coords;
        setUserLocation({ latitude, longitude });

        try {
          const res = await resolveLocationWorkflow({
            latitude,
            longitude,
            accuracy_meters: accuracy || null,
            radius_meters: 25000,
          });

          setWorkflowResult(res);

          if (res.status === 'SUCCESS' || res.status === 'PARTIAL_SUCCESS') {
            setWorkflowState('SUCCESS');
            if (res.resolved_station) {
              const stationId = res.resolved_station.location_id ?? res.resolved_station.id ?? null;
              setSelectedStationId(stationId);
              setResolvedDistanceKm(res.resolved_station.distance_km);
              loadMapData();
            }
          } else if (res.status === 'NO_STATIONS_FOUND') {
            setWorkflowState('NO_STATION');
            setResolvedDistanceKm(null);
          } else {
            setWorkflowState('ERROR');
            setWorkflowError(res.message || 'Unable to resolve nearby monitoring station.');
          }
        } catch (err: any) {
          setWorkflowState('ERROR');
          setWorkflowError(
            err.response?.data?.detail?.message ||
              err.message ||
              'Failed to communicate with location workflow service. Please try again.'
          );
        }
      },
      (geoError) => {
        setWorkflowState('ERROR');
        if (geoError.code === geoError.PERMISSION_DENIED) {
          setWorkflowError(
            'Location access was denied. Please allow browser location access to discover nearby stations.'
          );
        } else if (geoError.code === geoError.POSITION_UNAVAILABLE) {
          setWorkflowError('Location information is currently unavailable from your device.');
        } else if (geoError.code === geoError.TIMEOUT) {
          setWorkflowError('Location request timed out. Please try again.');
        } else {
          setWorkflowError('An unknown error occurred while detecting your location.');
        }
      },
      {
        enableHighAccuracy: true,
        timeout: 10000,
        maximumAge: 60000,
      }
    );
  }, [loadMapData]);

  // Client-side filtering
  const filteredStations = stations.filter((item) => {
    // Search query matching station name or city
    const matchesSearch =
      searchQuery.trim() === '' ||
      item.location.name.toLowerCase().includes(searchQuery.toLowerCase()) ||
      item.location.city.toLowerCase().includes(searchQuery.toLowerCase());

    // Category filter
    const matchesCategory =
      categoryFilter === 'All' ||
      (item.aqiData?.category && item.aqiData.category.toLowerCase() === categoryFilter.toLowerCase());

    // Source filter
    const matchesSource =
      sourceFilter === 'All' ||
      item.sourceType.toUpperCase() === sourceFilter.toUpperCase();

    return matchesSearch && matchesCategory && matchesSource;
  });

  const unmappedStations = stations.filter(
    (s) =>
      s.location.latitude === null ||
      s.location.latitude === undefined ||
      isNaN(s.location.latitude) ||
      s.location.longitude === null ||
      s.location.longitude === undefined ||
      isNaN(s.location.longitude)
  );

  return (
    <div className="space-y-6">
      {/* SECTION 1: Header, Search & Filter Bar */}
      <div className="p-4 rounded-xl bg-slate-900/90 border border-slate-800/80 shadow-lg flex flex-col lg:flex-row lg:items-center justify-between gap-4">
        {/* Title & Coordinates stats */}
        <div className="flex items-center gap-3">
          <div className="p-2.5 rounded-lg bg-emerald-500/10 text-emerald-400 border border-emerald-500/20">
            <MapPin className="w-5 h-5" />
          </div>
          <div>
            <h2 className="text-base font-bold text-slate-100 tracking-tight">
              Pollution Map & Spatial Intelligence
            </h2>
            <p className="text-xs text-slate-400">
              Interactive geographical distribution of CPCB air quality telemetry
            </p>
          </div>
        </div>

        {/* Filters and Refresh */}
        <div className="flex flex-wrap items-center gap-3">
          {/* Search Box */}
          <div className="relative">
            <Search className="w-3.5 h-3.5 text-slate-400 absolute left-3 top-1/2 -translate-y-1/2 pointer-events-none" />
            <input
              type="text"
              placeholder="Search station or city..."
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              className="pl-8 pr-3 py-1.5 rounded-xl bg-slate-950/60 border border-slate-800 text-xs text-slate-200 placeholder-slate-500 outline-none focus:border-teal-500/60 w-48 transition"
            />
          </div>

          {/* AQI Category Dropdown */}
          <div className="flex items-center gap-1.5 bg-slate-950/60 px-3 py-1.5 rounded-xl border border-slate-800 text-xs">
            <Filter className="w-3.5 h-3.5 text-slate-400" />
            <span className="text-slate-400">Category:</span>
            <select
              aria-label="Filter by AQI Category"
              value={categoryFilter}
              onChange={(e) => setCategoryFilter(e.target.value)}
              className="bg-transparent text-xs font-semibold text-slate-200 outline-none cursor-pointer"
            >
              {CATEGORY_FILTERS.map((cat) => (
                <option key={cat} value={cat} className="bg-slate-900 text-slate-200">
                  {cat}
                </option>
              ))}
            </select>
          </div>

          {/* Source Type Dropdown */}
          <div className="flex items-center gap-1.5 bg-slate-950/60 px-3 py-1.5 rounded-xl border border-slate-800 text-xs">
            <Layers className="w-3.5 h-3.5 text-slate-400" />
            <span className="text-slate-400">Source:</span>
            <select
              aria-label="Filter by Data Source"
              value={sourceFilter}
              onChange={(e) => setSourceFilter(e.target.value)}
              className="bg-transparent text-xs font-semibold text-slate-200 outline-none cursor-pointer"
            >
              {SOURCE_FILTERS.map((src) => (
                <option key={src} value={src} className="bg-slate-900 text-slate-200">
                  {src}
                </option>
              ))}
            </select>
          </div>

          {/* Manual Refresh Button */}
          <button
            type="button"
            onClick={loadMapData}
            disabled={loading}
            className="inline-flex items-center gap-2 px-3.5 py-1.5 rounded-xl bg-slate-800 hover:bg-slate-700 text-slate-200 text-xs font-medium border border-slate-700 transition disabled:opacity-50"
          >
            <RefreshCw className={`w-3.5 h-3.5 ${loading ? 'animate-spin' : ''}`} />
            <span>Refresh</span>
          </button>

          {/* Automatic Location Workflow: Use My Location */}
          <button
            type="button"
            onClick={handleUseMyLocation}
            disabled={workflowState === 'DETECTING_LOCATION' || workflowState === 'FINDING_STATION'}
            className="inline-flex items-center gap-1.5 px-3.5 py-1.5 rounded-xl bg-teal-500/10 hover:bg-teal-500/20 text-teal-300 border border-teal-500/30 text-xs font-semibold transition disabled:opacity-50"
            title="Automatically locate nearest monitoring station and show on map"
          >
            {workflowState === 'DETECTING_LOCATION' || workflowState === 'FINDING_STATION' ? (
              <>
                <Loader2 className="w-3.5 h-3.5 animate-spin text-teal-400" />
                <span>Locating...</span>
              </>
            ) : (
              <>
                <LocateFixed className="w-3.5 h-3.5 text-teal-400" />
                <span>Use My Location</span>
              </>
            )}
          </button>
        </div>
      </div>

      {/* Location Workflow Resolution Banner */}
      {showWorkflowNotice && workflowState !== 'IDLE' && (
        <div
          className={`p-4 rounded-2xl border flex flex-col sm:flex-row sm:items-center justify-between gap-3 shadow-lg transition-all ${
            workflowState === 'DETECTING_LOCATION' || workflowState === 'FINDING_STATION'
              ? 'bg-blue-500/10 border-blue-500/30 text-blue-300'
              : workflowState === 'SUCCESS'
              ? 'bg-teal-500/10 border-teal-500/30 text-teal-300'
              : workflowState === 'NO_STATION'
              ? 'bg-amber-500/10 border-amber-500/30 text-amber-300'
              : 'bg-rose-500/10 border-rose-500/30 text-rose-300'
          }`}
        >
          <div className="flex items-start sm:items-center gap-3">
            <div className="p-2 rounded-xl shrink-0 mt-0.5 sm:mt-0 bg-slate-950/40">
              {workflowState === 'DETECTING_LOCATION' || workflowState === 'FINDING_STATION' ? (
                <Loader2 className="w-5 h-5 animate-spin text-teal-400" />
              ) : workflowState === 'SUCCESS' ? (
                <CheckCircle2 className="w-5 h-5 text-emerald-400" />
              ) : workflowState === 'NO_STATION' ? (
                <AlertTriangle className="w-5 h-5 text-amber-400" />
              ) : (
                <XCircle className="w-5 h-5 text-rose-400" />
              )}
            </div>

            <div className="space-y-1">
              <div className="flex flex-wrap items-center gap-2">
                <span className="text-xs font-bold uppercase tracking-wider text-slate-200">
                  {workflowState === 'DETECTING_LOCATION'
                    ? 'Detecting Device Location'
                    : workflowState === 'FINDING_STATION'
                    ? 'Discovering Nearest Monitoring Station'
                    : workflowState === 'SUCCESS'
                    ? 'Station Plotted On Map'
                    : workflowState === 'NO_STATION'
                    ? 'No Station Found Within 25 km'
                    : 'Location Resolution Notice'}
                </span>

                {workflowState === 'SUCCESS' && workflowResult?.resolved_station && (
                  <>
                    <span className="px-2 py-0.5 rounded text-[10px] font-bold uppercase bg-teal-500/20 text-teal-300 border border-teal-500/30 font-mono">
                      {workflowResult.resolved_station.distance_km.toFixed(1)} km away
                    </span>
                    <span
                      className={`px-2 py-0.5 rounded text-[10px] font-bold uppercase font-mono ${
                        workflowResult.resolved_station.data_freshness === 'FRESH'
                          ? 'bg-emerald-500/20 text-emerald-300 border border-emerald-500/30'
                          : workflowResult.resolved_station.data_freshness === 'STALE'
                          ? 'bg-amber-500/20 text-amber-300 border border-amber-500/30'
                          : 'bg-rose-500/20 text-rose-300 border border-rose-500/30'
                      }`}
                    >
                      {workflowResult.resolved_station.data_freshness} Telemetry
                    </span>
                  </>
                )}
              </div>

              <p className="text-xs text-slate-300 leading-relaxed">
                {workflowState === 'DETECTING_LOCATION'
                  ? 'Requesting browser GPS coordinates with high accuracy...'
                  : workflowState === 'FINDING_STATION'
                  ? 'Searching OpenAQ monitoring network within 25 km and evaluating real observations...'
                  : workflowState === 'SUCCESS' && workflowResult?.resolved_station
                  ? `Plotted user location and connector to ${workflowResult.resolved_station.name} (${workflowResult.resolved_station.distance_km.toFixed(1)} km away).`
                  : workflowState === 'NO_STATION'
                  ? workflowResult?.nearest_distant_station
                    ? `${workflowResult.message} ${workflowResult.nearest_distant_station.notice}`
                    : workflowResult?.message || 'No official monitoring station was found within 25 km of your location.'
                  : workflowError || 'Failed to resolve location.'}
              </p>
            </div>
          </div>

          <div className="flex items-center gap-2 self-end sm:self-auto shrink-0">
            {workflowState === 'ERROR' && (
              <button
                type="button"
                onClick={handleUseMyLocation}
                className="px-3 py-1.5 rounded-lg bg-slate-800 hover:bg-slate-700 text-xs text-white font-medium transition"
              >
                Retry
              </button>
            )}
            <button
              type="button"
              onClick={() => setShowWorkflowNotice(false)}
              className="p-1 rounded-lg hover:bg-slate-800 text-slate-400 hover:text-white transition"
              aria-label="Dismiss banner"
            >
              <X className="w-4 h-4" />
            </button>
          </div>
        </div>
      )}

      {/* Error Banner */}
      {errorMessage && (
        <div className="p-4 rounded-xl bg-rose-500/10 border border-rose-500/20 text-rose-300 text-xs flex items-center justify-between">
          <div className="flex items-center gap-2">
            <AlertTriangle className="w-4 h-4 shrink-0 text-rose-400" />
            <span>{errorMessage}</span>
          </div>
          <button onClick={loadMapData} className="underline hover:text-white text-xs">
            Retry
          </button>
        </div>
      )}

      {/* Unmapped Stations Alert (if any) */}
      {unmappedStations.length > 0 && (
        <div className="p-3 rounded-xl bg-amber-500/10 border border-amber-500/20 text-amber-300 text-xs flex items-center gap-2">
          <Info className="w-4 h-4 shrink-0 text-amber-400" />
          <span>
            {unmappedStations.length} station(s) do not have valid latitude/longitude coordinates and are listed in the station directory without being plotted on the map.
          </span>
        </div>
      )}

      {/* SECTION 2: Interactive Map Viewport */}
      {loading ? (
        <div className="h-[520px] rounded-2xl bg-slate-900/60 border border-slate-800 animate-pulse flex flex-col items-center justify-center space-y-3">
          <RefreshCw className="w-8 h-8 text-teal-400 animate-spin" />
          <p className="text-xs font-mono text-slate-400">
            Loading geographical telemetry and station coordinates...
          </p>
        </div>
      ) : stations.length === 0 ? (
        <div className="h-[520px] rounded-2xl border border-dashed border-slate-800 bg-slate-950/40 flex flex-col items-center justify-center p-6 text-center space-y-3">
          <MapPin className="w-10 h-10 text-slate-600" />
          <h4 className="text-sm font-semibold text-slate-300">
            No monitoring locations available.
          </h4>
          <p className="text-xs text-slate-500 max-w-sm">
            Seed monitoring stations or configure data source ingestion to visualize spatial air quality.
          </p>
        </div>
      ) : (
        <StationMap
          stations={filteredStations}
          selectedStationId={selectedStationId}
          userLocation={userLocation}
          resolvedStationDistanceKm={resolvedDistanceKm}
          onSelectStation={(id) => setSelectedStationId(id)}
          onNavigateToDashboard={onNavigateToDashboard}
        />
      )}

      {/* SECTION 3: Station List & CPCB Legend Grid */}
      <div className="grid grid-cols-1 lg:grid-cols-12 gap-6">
        <div className="lg:col-span-8">
          <StationList
            stations={filteredStations}
            selectedStationId={selectedStationId}
            onSelectStation={(id) => setSelectedStationId(id)}
            onNavigateToDashboard={onNavigateToDashboard}
          />
        </div>
        <div className="lg:col-span-4 space-y-4">
          <MapLegend />

          {/* Software-Only Architecture Guarantee */}
          <div className="p-4 rounded-xl bg-slate-900/40 border border-slate-800 text-xs text-slate-400 space-y-2">
            <div className="flex items-center gap-2 text-slate-300 font-semibold text-xs">
              <ShieldAlert className="w-4 h-4 text-amber-400 shrink-0" />
              <span>Software-Only Spatial Telemetry</span>
            </div>
            <p className="text-[11px] leading-relaxed text-slate-400">
              Station coordinates are registered from official public monitoring station records.
              Physical GPS trackers, Arduino, or IoT sensor hardware are not utilized.
            </p>
            {lastUpdated && (
              <div className="pt-1 text-[10px] text-slate-500 font-mono flex items-center gap-1">
                <ShieldCheck className="w-3.5 h-3.5 text-emerald-400" />
                <span>Synchronized: {lastUpdated}</span>
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
};
