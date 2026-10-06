import React, { useEffect, useRef, useCallback } from 'react';
import L from 'leaflet';
import 'leaflet/dist/leaflet.css';
import type { Location } from '../../types/air_quality';
import type { AQIResponse } from '../../types/aqi';
import { getAQICategoryStyle } from '../../utils/aqiFormatters';
import { Maximize2, RotateCcw } from 'lucide-react';

export interface StationMapItem {
  location: Location;
  aqiData: AQIResponse | null;
  sourceType: string;
}

interface StationMapProps {
  stations: StationMapItem[];
  selectedStationId: number | null;
  userLocation?: { latitude: number; longitude: number } | null;
  resolvedStationDistanceKm?: number | null;
  onSelectStation: (stationId: number) => void;
  onNavigateToDashboard: (stationId: number) => void;
}

const INDIA_CENTER: [number, number] = [20.5937, 78.9629];
const DEFAULT_ZOOM = 5;

export const StationMap: React.FC<StationMapProps> = ({
  stations,
  selectedStationId,
  userLocation,
  resolvedStationDistanceKm,
  onSelectStation,
  onNavigateToDashboard,
}) => {
  const mapContainerRef = useRef<HTMLDivElement>(null);
  const mapInstanceRef = useRef<L.Map | null>(null);
  const markersRef = useRef<Map<number, L.Marker>>(new Map());
  const userMarkerRef = useRef<L.Marker | null>(null);
  const userRayRef = useRef<L.Polyline | null>(null);

  // Filter valid coordinates strictly
  const validStations = stations.filter(
    (s) =>
      s.location.latitude !== null &&
      s.location.latitude !== undefined &&
      !isNaN(s.location.latitude) &&
      s.location.longitude !== null &&
      s.location.longitude !== undefined &&
      !isNaN(s.location.longitude)
  );

  // Initialize Leaflet Map once
  useEffect(() => {
    if (!mapContainerRef.current || mapInstanceRef.current) return;

    const map = L.map(mapContainerRef.current, {
      center: INDIA_CENTER,
      zoom: DEFAULT_ZOOM,
      zoomControl: true,
      attributionControl: true,
    });

    L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
      attribution:
        '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors',
      maxZoom: 18,
    }).addTo(map);

    mapInstanceRef.current = map;

    return () => {
      map.remove();
      mapInstanceRef.current = null;
    };
  }, []);

  // Fit bounds helper
  const fitAllStations = useCallback((animate = true) => {
    const map = mapInstanceRef.current;
    if (!map) return;

    if (validStations.length === 0) {
      map.setView(INDIA_CENTER, DEFAULT_ZOOM, { animate });
    } else if (validStations.length === 1) {
      const s = validStations[0];
      map.setView([s.location.latitude, s.location.longitude], 12, { animate });
    } else {
      const bounds = L.latLngBounds(
        validStations.map((s) => [s.location.latitude, s.location.longitude] as [number, number])
      );
      map.fitBounds(bounds, { padding: [60, 60], maxZoom: 13, animate });
    }
  }, [validStations]);

  // Render / Update Markers when stations change
  useEffect(() => {
    const map = mapInstanceRef.current;
    if (!map) return;

    // Clear existing markers
    markersRef.current.forEach((marker) => marker.remove());
    markersRef.current.clear();

    validStations.forEach((station) => {
      const { location, aqiData, sourceType } = station;
      const isCalculated = aqiData && aqiData.status === 'CALCULATED' && aqiData.aqi !== null;
      const categoryStyle = getAQICategoryStyle(aqiData?.category);
      const isSelected = selectedStationId === location.id;

      const aqiText = isCalculated ? `${aqiData.aqi}` : 'N/A';

      // Create custom HTML icon with CPCB styling
      const iconHtml = `
        <div class="relative flex items-center justify-center cursor-pointer transition-transform transform ${
          isSelected ? 'scale-125 z-50' : 'hover:scale-110 z-10'
        }">
          <div class="absolute -inset-1 rounded-full opacity-40 blur-sm" style="background-color: ${
            categoryStyle.hex
          };"></div>
          <div class="relative px-2 py-1 rounded-full border-2 font-mono font-bold text-xs text-white shadow-xl flex items-center gap-1"
               style="background-color: #0f172a; border-color: ${categoryStyle.hex}; ${
        isSelected ? 'box-shadow: 0 0 15px ' + categoryStyle.hex + ';' : ''
      }">
            <span class="w-2 h-2 rounded-full" style="background-color: ${categoryStyle.hex};"></span>
            <span>${aqiText}</span>
          </div>
        </div>
      `;

      const customIcon = L.divIcon({
        html: iconHtml,
        className: 'custom-station-pin',
        iconSize: [40, 24],
        iconAnchor: [20, 12],
      });

      const marker = L.marker([location.latitude, location.longitude], {
        icon: customIcon,
      }).addTo(map);

      // Construct Popup Content with detailed station metadata
      const popupDiv = document.createElement('div');
      popupDiv.className = 'p-3 text-slate-100 font-sans min-w-[220px] space-y-2';

      const timeStr = aqiData?.timestamp
        ? new Date(aqiData.timestamp).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
        : 'Recent';

      let freshnessHtml = '<span class="px-1.5 py-0.5 rounded text-[9px] font-mono font-bold bg-slate-700 text-slate-400 border border-slate-600">NO TELEMETRY</span>';
      if (aqiData?.timestamp) {
        const obsDate = new Date(aqiData.timestamp).getTime();
        const now = Date.now();
        const ageHours = (now - obsDate) / (1000 * 60 * 60);
        if (ageHours <= 3.0) {
          freshnessHtml = '<span class="px-1.5 py-0.5 rounded text-[9px] font-mono font-bold bg-emerald-500/20 text-emerald-300 border border-emerald-500/40">FRESH</span>';
        } else if (ageHours <= 24.0) {
          freshnessHtml = `<span class="px-1.5 py-0.5 rounded text-[9px] font-mono font-bold bg-amber-500/20 text-amber-300 border border-amber-500/40">STALE (${Math.round(ageHours)}h)</span>`;
        } else {
          freshnessHtml = '<span class="px-1.5 py-0.5 rounded text-[9px] font-mono font-bold bg-slate-800 text-slate-400 border border-slate-700">UNAVAILABLE</span>';
        }
      }

      popupDiv.innerHTML = `
        <div class="border-b border-slate-700 pb-2">
          <div class="flex items-center justify-between gap-2">
            <h4 class="font-bold text-sm text-white">${location.name}</h4>
            <span class="px-2 py-0.5 rounded text-[9px] font-mono font-bold uppercase"
                  style="background-color: ${categoryStyle.hex}25; color: ${categoryStyle.hex}; border: 1px solid ${categoryStyle.hex}60;">
              ${categoryStyle.label}
            </span>
          </div>
          <div class="text-[11px] text-slate-400">${location.city}, ${location.state}</div>
        </div>

        <div class="space-y-1 text-xs font-mono">
          <div class="flex justify-between">
            <span class="text-slate-400">AQI:</span>
            <span class="font-bold text-white">${isCalculated ? aqiData.aqi : '<em class="text-slate-400 font-sans font-normal">AQI unavailable</em>'}</span>
          </div>
          <div class="flex justify-between items-center">
            <span class="text-slate-400">Freshness:</span>
            ${freshnessHtml}
          </div>
          <div class="flex justify-between">
            <span class="text-slate-400">Dominant:</span>
            <span class="text-teal-300 font-semibold">${aqiData?.dominant_pollutant || '<em class="text-slate-400 font-sans font-normal">Not available</em>'}</span>
          </div>
          <div class="flex justify-between">
            <span class="text-slate-400">Source:</span>
            <span class="text-slate-300 font-semibold">${sourceType}</span>
          </div>
          <div class="flex justify-between">
            <span class="text-slate-400">Updated:</span>
            <span class="text-slate-300">${timeStr}</span>
          </div>
        </div>

        <div class="pt-2 border-t border-slate-700">
          <button id="view-dashboard-btn-${location.id}"
                  class="w-full py-1.5 px-3 rounded-lg text-xs font-semibold bg-teal-500 hover:bg-teal-400 text-slate-950 transition flex items-center justify-center gap-1 shadow">
            <span>View in Dashboard</span>
          </button>
        </div>
      `;

      // Attach Click event to button inside popup
      const btn = popupDiv.querySelector(`#view-dashboard-btn-${location.id}`);
      if (btn) {
        btn.addEventListener('click', (e) => {
          e.stopPropagation();
          onNavigateToDashboard(location.id);
        });
      }

      marker.bindPopup(popupDiv, {
        className: 'station-dark-popup',
        maxWidth: 280,
      });

      marker.on('click', () => {
        onSelectStation(location.id);
      });

      markersRef.current.set(location.id, marker);
    });

    // Auto-fit on initial station data load
    fitAllStations(false);
  }, [
    validStations,
    selectedStationId,
    onNavigateToDashboard,
    onSelectStation,
    fitAllStations,
  ]);

  // Handle selectedStationId focus/open popup
  useEffect(() => {
    if (!selectedStationId || !mapInstanceRef.current) return;
    const marker = markersRef.current.get(selectedStationId);
    const station = validStations.find((s) => s.location.id === selectedStationId);

    if (marker && station) {
      mapInstanceRef.current.flyTo(
        [station.location.latitude, station.location.longitude],
        13,
        { animate: true, duration: 0.8 }
      );
      marker.openPopup();
    }
  }, [selectedStationId, validStations]);

  // Render User Location Pin and Connector Ray
  useEffect(() => {
    const map = mapInstanceRef.current;
    if (!map) return;

    if (userMarkerRef.current) {
      userMarkerRef.current.remove();
      userMarkerRef.current = null;
    }
    if (userRayRef.current) {
      userRayRef.current.remove();
      userRayRef.current = null;
    }

    if (!userLocation) return;

    // Create Pulsating Blue User Marker
    const userIcon = L.divIcon({
      className: 'user-geo-pin',
      html: `
        <div style="position: relative; display: flex; align-items: center; justify-content: center; width: 28px; height: 28px;">
          <div style="position: absolute; width: 28px; height: 28px; border-radius: 9999px; background-color: rgba(59, 130, 246, 0.35); animation: ping 1.5s cubic-bezier(0, 0, 0.2, 1) infinite;"></div>
          <div style="width: 14px; height: 14px; border-radius: 9999px; background-color: #2563eb; border: 2.5px solid white; box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.4);"></div>
        </div>
      `,
      iconSize: [28, 28],
      iconAnchor: [14, 14],
    });

    const userMarker = L.marker([userLocation.latitude, userLocation.longitude], {
      icon: userIcon,
      zIndexOffset: 1000,
    }).addTo(map);

    userMarker.bindPopup(`
      <div style="font-family: inherit; font-size: 12px; color: #0f172a; padding: 2px;">
        <div style="font-weight: 700; color: #2563eb; margin-bottom: 2px;">Your Location</div>
        <div style="font-size: 11px; color: #64748b;">[${userLocation.latitude.toFixed(3)}, ${userLocation.longitude.toFixed(3)}]</div>
      </div>
    `);

    userMarkerRef.current = userMarker;

    // If selected station exists and is within valid stations, draw dashed connector ray
    const activeSt = validStations.find((s) => s.location.id === selectedStationId);
    if (activeSt && activeSt.location.latitude && activeSt.location.longitude) {
      const ray = L.polyline(
        [
          [userLocation.latitude, userLocation.longitude],
          [activeSt.location.latitude, activeSt.location.longitude],
        ],
        {
          color: '#06b6d4',
          weight: 2,
          dashArray: '6, 6',
          opacity: 0.85,
        }
      ).addTo(map);

      const distLabel =
        resolvedStationDistanceKm != null
          ? `${resolvedStationDistanceKm.toFixed(1)} km to station`
          : 'Connecting to station';
      ray.bindTooltip(distLabel, { permanent: true, direction: 'center', className: 'ray-tooltip' });
      userRayRef.current = ray;

      // Fit bounds to show both user and station
      const bounds = L.latLngBounds([
        [userLocation.latitude, userLocation.longitude],
        [activeSt.location.latitude, activeSt.location.longitude],
      ]);
      map.fitBounds(bounds, { padding: [80, 80], maxZoom: 14, animate: true });
    }
  }, [userLocation, selectedStationId, validStations, resolvedStationDistanceKm]);

  return (
    <div className="relative w-full h-[520px] rounded-2xl overflow-hidden border border-slate-800 shadow-2xl bg-slate-950">
      {/* Map Container */}
      <div ref={mapContainerRef} className="w-full h-full z-0" />

      {/* Map Action Floating Controls */}
      <div className="absolute top-4 right-4 z-[400] flex flex-col gap-2">
        <button
          type="button"
          onClick={() => fitAllStations(true)}
          title="Fit All Monitored Stations"
          className="p-2.5 rounded-xl bg-slate-900/90 hover:bg-slate-800 text-slate-200 border border-slate-700 shadow-xl transition backdrop-blur flex items-center gap-1.5 text-xs font-medium"
        >
          <Maximize2 className="w-4 h-4 text-teal-400" />
          <span className="hidden sm:inline">Fit All Stations</span>
        </button>

        <button
          type="button"
          onClick={() => {
            if (mapInstanceRef.current) {
              mapInstanceRef.current.setView(INDIA_CENTER, DEFAULT_ZOOM, { animate: true });
            }
          }}
          title="Reset Map View"
          className="p-2.5 rounded-xl bg-slate-900/90 hover:bg-slate-800 text-slate-200 border border-slate-700 shadow-xl transition backdrop-blur flex items-center gap-1.5 text-xs font-medium"
        >
          <RotateCcw className="w-4 h-4 text-slate-400" />
          <span className="hidden sm:inline">Reset View</span>
        </button>
      </div>

      {/* Station Count Pill */}
      <div className="absolute bottom-4 left-4 z-[400] px-3 py-1.5 rounded-xl bg-slate-900/90 border border-slate-800 text-xs font-mono text-slate-300 shadow-xl backdrop-blur flex items-center gap-2">
        <span className="w-2 h-2 rounded-full bg-teal-400 animate-pulse" />
        <span>
          {validStations.length} of {stations.length} Stations Mapped
        </span>
      </div>

      <style>{`
        .station-dark-popup .leaflet-popup-content-wrapper {
          background-color: #090d16 !important;
          border: 1px solid #334155 !important;
          border-radius: 12px !important;
          box-shadow: 0 20px 25px -5px rgba(0, 0, 0, 0.5), 0 8px 10px -6px rgba(0, 0, 0, 0.5) !important;
          padding: 0 !important;
        }
        .station-dark-popup .leaflet-popup-tip {
          background-color: #090d16 !important;
          border: 1px solid #334155 !important;
        }
        .station-dark-popup .leaflet-popup-close-button {
          color: #94a3b8 !important;
          padding: 4px !important;
        }
        .station-dark-popup .leaflet-popup-close-button:hover {
          color: #ffffff !important;
        }
        .ray-tooltip {
          background-color: #0f172a !important;
          color: #38bdf8 !important;
          border: 1px solid #0284c7 !important;
          border-radius: 8px !important;
          font-family: monospace !important;
          font-size: 11px !important;
          font-weight: 600 !important;
          box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.4) !important;
          padding: 3px 8px !important;
        }
        .ray-tooltip::before {
          border-top-color: #0284c7 !important;
        }
      `}</style>
    </div>
  );
};
