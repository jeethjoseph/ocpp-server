"use client";

import { useEffect, useRef } from 'react';
import { MapContainer, TileLayer, Marker, Popup, useMap } from 'react-leaflet';
import L from 'leaflet';
import 'leaflet/dist/leaflet.css';
import type { PublicStationResponse } from "@/lib/api-services";
import { formatTariffRangeAllIn } from "@/lib/utils";

export interface StationWithDistance extends PublicStationResponse {
  distance?: number;
}

// Fix for default markers in React Leaflet
delete (L.Icon.Default.prototype as { _getIconUrl?: unknown })._getIconUrl;
L.Icon.Default.mergeOptions({
  iconRetinaUrl: 'https://cdnjs.cloudflare.com/ajax/libs/leaflet/1.7.1/images/marker-icon-2x.png',
  iconUrl: 'https://cdnjs.cloudflare.com/ajax/libs/leaflet/1.7.1/images/marker-icon.png',
  shadowUrl: 'https://cdnjs.cloudflare.com/ajax/libs/leaflet/1.7.1/images/marker-shadow.png',
});

// Camera heuristic constants (tunable in one place).
const FIT_PADDING: [number, number] = [20, 20];
const FIT_MAX_ZOOM = 15;          // never over-zoom, even on a lone nearby pin
const NEAREST_COUNT = 4;          // up to N nearest stations framed in phase 2
const NEAREST_RADIUS_KM = 15;     // ignore stations beyond this when framing "nearest"
const ALL_PINS_HOLD_MS = 900;     // how long the all-pins view holds before flying in

// Haversine distance in km. Self-contained so the camera heuristic doesn't
// depend on the parent having pre-sorted/annotated stations.
function distanceKm(lat1: number, lng1: number, lat2: number, lng2: number): number {
  const R = 6371;
  const dLat = ((lat2 - lat1) * Math.PI) / 180;
  const dLng = ((lng2 - lng1) * Math.PI) / 180;
  const a =
    Math.sin(dLat / 2) ** 2 +
    Math.cos((lat1 * Math.PI) / 180) * Math.cos((lat2 * Math.PI) / 180) * Math.sin(dLng / 2) ** 2;
  return R * 2 * Math.atan2(Math.sqrt(a), Math.sqrt(1 - a));
}

// Bounds covering all given stations plus the user (when known).
function allPinsBounds(userLocation: { lat: number; lng: number } | null, stations: StationWithDistance[]) {
  const points = stations.map((s) => [s.latitude, s.longitude] as [number, number]);
  if (userLocation) points.push([userLocation.lat, userLocation.lng]);
  return L.latLngBounds(points);
}

// Up to NEAREST_COUNT stations within NEAREST_RADIUS_KM of the user, nearest first.
function nearestStations(userLocation: { lat: number; lng: number }, stations: StationWithDistance[]) {
  return stations
    .map((s) => ({ s, d: distanceKm(userLocation.lat, userLocation.lng, s.latitude, s.longitude) }))
    .filter(({ d }) => d <= NEAREST_RADIUS_KM)
    .sort((a, b) => a.d - b.d)
    .slice(0, NEAREST_COUNT)
    .map(({ s }) => s);
}

// Create station icon based on availability status
const createStationIcon = (available: number, total: number) => {
  let bgColor = '#ef4444'; // red for offline/error
  if (available > 0) {
    bgColor = '#22c55e'; // green for available
  } else if (total > 0) {
    bgColor = '#eab308'; // yellow for all busy
  }
  
  return L.divIcon({
    html: `
      <div style="
        background-color: ${bgColor};
        width: 32px;
        height: 32px;
        border-radius: 50%;
        border: 3px solid white;
        box-shadow: 0 3px 6px rgba(0,0,0,0.3);
        display: flex;
        align-items: center;
        justify-content: center;
        cursor: pointer;
      ">
        <svg width="16" height="16" viewBox="0 0 24 24" fill="white">
          <path d="M12 2L13.09 8.26L22 9L17 14L18.18 22L12 19L5.82 22L7 14L2 9L10.91 8.26L12 2Z"/>
        </svg>
        <div style="
          position: absolute;
          bottom: -6px;
          right: -6px;
          background-color: white;
          border-radius: 50%;
          width: 14px;
          height: 14px;
          display: flex;
          align-items: center;
          justify-content: center;
          font-size: 10px;
          font-weight: bold;
          color: ${bgColor};
          box-shadow: 0 1px 3px rgba(0,0,0,0.2);
        ">${available}</div>
      </div>
    `,
    className: '',
    iconSize: [32, 32],
    iconAnchor: [16, 16],
  });
};

// User location icon
const userIcon = L.divIcon({
  html: `
    <div style="
      background-color: #3b82f6;
      width: 16px;
      height: 16px;
      border-radius: 50%;
      border: 3px solid white;
      box-shadow: 0 2px 4px rgba(0,0,0,0.2);
      animation: pulse 2s infinite;
    ">
    </div>
    <style>
      @keyframes pulse {
        0% { transform: scale(1); opacity: 1; }
        70% { transform: scale(1.4); opacity: 0.5; }
        100% { transform: scale(1); opacity: 1; }
      }
    </style>
  `,
  className: '',
  iconSize: [16, 16],
  iconAnchor: [8, 8],
});


interface StationMapProps {
  stations: StationWithDistance[];
  userLocation: {lat: number; lng: number} | null;
  onStationSelect: (station: StationWithDistance) => void;
  selectedStation: StationWithDistance | null;
  onStationCenter: (station: StationWithDistance) => void;
  onMapReady?: (map: L.Map) => void;
}

function MapController({ userLocation, stations, onMapReady }: { userLocation: {lat: number; lng: number} | null, stations: StationWithDistance[], onMapReady?: (map: L.Map) => void }) {
  const map = useMap();
  const phase1Ref = useRef(false);  // all-pins fit done
  const phase2Ref = useRef(false);  // nearest-few fly scheduled/decided
  const flyTimerRef = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);

  useEffect(() => {
    if (onMapReady) {
      onMapReady(map);
    }
  }, [map, onMapReady]);

  // Clear any pending fly-in if the component unmounts mid-hold.
  useEffect(() => () => {
    if (flyTimerRef.current) clearTimeout(flyTimerRef.current);
  }, []);

  useEffect(() => {
    if (stations.length === 0) return;

    // Phase 1 (once): show ALL pins immediately, no animation.
    if (!phase1Ref.current) {
      phase1Ref.current = true;
      map.fitBounds(allPinsBounds(userLocation, stations), {
        padding: FIT_PADDING, maxZoom: FIT_MAX_ZOOM, animate: false,
      });
    }

    // Phase 2 (once): after a brief hold, fly in to the nearest few. Needs a
    // user location; only fires when that frame is meaningfully tighter than
    // the all-pins frame (i.e. some stations are left out).
    if (phase2Ref.current || !userLocation) return;
    const nearest = nearestStations(userLocation, stations);
    if (nearest.length === 0 || nearest.length === stations.length) {
      phase2Ref.current = true;  // nothing nearby, or nearest == all → stay fit-all
      return;
    }
    phase2Ref.current = true;

    const nearBounds = allPinsBounds(userLocation, nearest);
    // Phase 1 is settled instantly, so any dragstart/zoomstart during the hold
    // is user-initiated → cancel the pending fly so we never yank the camera.
    const cancel = () => {
      if (flyTimerRef.current) clearTimeout(flyTimerRef.current);
      flyTimerRef.current = undefined;
      map.off('dragstart', cancel);
      map.off('zoomstart', cancel);
    };
    map.on('dragstart', cancel);
    map.on('zoomstart', cancel);
    flyTimerRef.current = setTimeout(() => {
      map.off('dragstart', cancel);
      map.off('zoomstart', cancel);
      flyTimerRef.current = undefined;
      map.flyToBounds(nearBounds, { padding: FIT_PADDING, maxZoom: FIT_MAX_ZOOM });
    }, ALL_PINS_HOLD_MS);
  }, [map, userLocation, stations]);

  return null;
}

export default function StationMap({ stations, userLocation, onStationSelect, onStationCenter, onMapReady }: StationMapProps) {
  // Default center (San Francisco)
  const defaultCenter: [number, number] = [37.7749, -122.4194];
  const center: [number, number] = userLocation 
    ? [userLocation.lat, userLocation.lng] 
    : defaultCenter;

  return (
    <div className="w-full h-full relative">
      <MapContainer
        center={center}
        zoom={13}
        style={{ height: '100%', width: '100%' }}
        className="z-0"
      >
        <TileLayer
          url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
          attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'
        />
        
        <MapController userLocation={userLocation} stations={stations} onMapReady={onMapReady} />
        
        {/* User location marker */}
        {userLocation && (
          <Marker
            position={[userLocation.lat, userLocation.lng]}
            icon={userIcon}
          >
            <Popup>
              <div className="text-center">
                <div className="font-medium">Your Location</div>
              </div>
            </Popup>
          </Marker>
        )}
        
        {/* Station markers */}
        {stations.map((station) => (
          <Marker
            key={station.id}
            position={[station.latitude, station.longitude]}
            icon={createStationIcon(station.available_chargers || 0, station.total_chargers || 0)}
            eventHandlers={{
              click: () => {
                onStationCenter(station);
                onStationSelect(station);
              }
            }}
          >
            <Popup>
              <div className="min-w-[200px]">
                <div className="font-medium text-gray-900 mb-1">{station.name}</div>
                {station.franchisee_name && (
                  <div className="text-xs text-gray-500 mb-1">
                    Operator: <span className="font-medium">{station.franchisee_name}</span>
                  </div>
                )}
                <div className="text-sm text-gray-600 mb-2">{station.address}</div>
                
                <div className="flex justify-center mb-3">
                  <div className="text-center p-2 bg-gray-50 rounded">
                    <div className="text-sm font-bold text-green-600">
                      {station.available_chargers || 0}/{station.total_chargers || 0}
                    </div>
                    <div className="text-xs text-gray-600">Available</div>
                  </div>
                </div>
                
                <div className="space-y-1 text-sm mb-3">
                  <div className="flex justify-between">
                    <span className="text-gray-600">Price:</span>
                    <span className="font-medium text-right">
                      {formatTariffRangeAllIn(
                        station.min_price_per_kwh_all_in,
                        station.max_price_per_kwh_all_in,
                      )}
                    </span>
                  </div>
                  <div className="flex justify-between">
                    <span className="text-gray-600">Connectors:</span>
                    <span className="font-medium text-right">{station.connector_types?.join(', ') || 'N/A'}</span>
                  </div>
                </div>
                
                <button
                  onClick={() => onStationSelect(station)}
                  className="w-full bg-blue-600 text-white text-sm px-3 py-1 rounded hover:bg-blue-700 transition-colors"
                >
                  View Details
                </button>
              </div>
            </Popup>
          </Marker>
        ))}
      </MapContainer>
      
      {/* Map controls overlay - only show if there are stations */}
      {stations.length > 0 && (
        <div className="absolute bottom-4 right-4 bg-white rounded-lg shadow-lg px-3 py-2 z-10">
          <div className="flex items-center gap-3 text-xs">
            <div className="flex items-center gap-1">
              <div 
                className="w-2 h-2 rounded-full"
                style={{ backgroundColor: '#3b82f6' }}
              ></div>
              <span>You</span>
            </div>
            <div className="flex items-center gap-1">
              <div 
                className="w-2 h-2 rounded-full"
                style={{ backgroundColor: '#22c55e' }}
              ></div>
              <span>Stations</span>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}