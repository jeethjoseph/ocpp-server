"use client";

import { useEffect } from 'react';
import { MapContainer, TileLayer, Marker, Popup, useMap } from 'react-leaflet';
import L from 'leaflet';
import 'leaflet/dist/leaflet.css';
import type { PublicStationResponse } from "@/lib/api-services";

interface StationWithDistance extends PublicStationResponse {
  distance?: number;
}

// Fix for default markers in React Leaflet
// Fix for default markers in React Leaflet
delete (L.Icon.Default.prototype as { _getIconUrl?: unknown })._getIconUrl;
L.Icon.Default.mergeOptions({
  iconRetinaUrl: 'https://cdnjs.cloudflare.com/ajax/libs/leaflet/1.7.1/images/marker-icon-2x.png',
  iconUrl: 'https://cdnjs.cloudflare.com/ajax/libs/leaflet/1.7.1/images/marker-icon.png',
  shadowUrl: 'https://cdnjs.cloudflare.com/ajax/libs/leaflet/1.7.1/images/marker-shadow.png',
});

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
  
  useEffect(() => {
    if (onMapReady) {
      onMapReady(map);
    }
  }, [map, onMapReady]);
  
  useEffect(() => {
    if (userLocation && stations.length > 0) {
      // Create bounds that include user location and all stations
      const bounds = L.latLngBounds([
        [userLocation.lat, userLocation.lng],
        ...stations.map(station => [station.latitude, station.longitude] as [number, number])
      ]);
      
      map.fitBounds(bounds, { 
        padding: [20, 20],
        maxZoom: 15
      });
    } else if (stations.length > 0) {
      // Just fit stations if no user location
      const bounds = L.latLngBounds(
        stations.map(station => [station.latitude, station.longitude] as [number, number])
      );
      map.fitBounds(bounds, { 
        padding: [20, 20],
        maxZoom: 15
      });
    } else if (userLocation) {
      // Just center on user if no stations
      map.setView([userLocation.lat, userLocation.lng], 13);
    }
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
                    <span className="font-medium">₹{station.price_per_kwh || 'N/A'}/kWh</span>
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