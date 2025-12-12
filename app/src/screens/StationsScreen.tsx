import { useQuery } from '@tanstack/react-query';
import { useApi } from '../lib/api-client';
import { publicStationService } from '../lib/api-services';
import { MapPin, Navigation, Zap, Loader2, Info, AlertCircle } from 'lucide-react';
import { useEffect, useState, useRef, useMemo } from 'react';
import { Geolocation } from '@capacitor/geolocation';
import { MapContainer, TileLayer, Marker, Popup, useMap } from 'react-leaflet';
import L from 'leaflet';
import 'leaflet/dist/leaflet.css';
import type { PublicStationResponse } from '../types/api';
import { PullToRefresh } from '../components/PullToRefresh';
import { StationsSkeleton } from '../components/StationsSkeleton';

// Fix for default marker icons in Leaflet with bundlers
delete (L.Icon.Default.prototype as any)._getIconUrl;
L.Icon.Default.mergeOptions({
  iconRetinaUrl: 'https://cdnjs.cloudflare.com/ajax/libs/leaflet/1.7.1/images/marker-icon-2x.png',
  iconUrl: 'https://cdnjs.cloudflare.com/ajax/libs/leaflet/1.7.1/images/marker-icon.png',
  shadowUrl: 'https://cdnjs.cloudflare.com/ajax/libs/leaflet/1.7.1/images/marker-shadow.png',
});

// Custom green icon for available chargers
const greenIcon = new L.Icon({
  iconUrl: 'https://raw.githubusercontent.com/pointhi/leaflet-color-markers/master/img/marker-icon-2x-green.png',
  shadowUrl: 'https://cdnjs.cloudflare.com/ajax/libs/leaflet/1.7.1/images/marker-shadow.png',
  iconSize: [25, 41],
  iconAnchor: [12, 41],
  popupAnchor: [1, -34],
  shadowSize: [41, 41],
});

// Custom red icon for unavailable chargers
const redIcon = new L.Icon({
  iconUrl: 'https://raw.githubusercontent.com/pointhi/leaflet-color-markers/master/img/marker-icon-2x-red.png',
  shadowUrl: 'https://cdnjs.cloudflare.com/ajax/libs/leaflet/1.7.1/images/marker-shadow.png',
  iconSize: [25, 41],
  iconAnchor: [12, 41],
  popupAnchor: [1, -34],
  shadowSize: [41, 41],
});

// Custom blue dot icon for user location (Google Maps style)
const blueDotIcon = new L.DivIcon({
  className: 'user-location-marker',
  html: `
    <div style="position: relative;">
      <div style="
        width: 20px;
        height: 20px;
        background: #4285F4;
        border: 3px solid white;
        border-radius: 50%;
        box-shadow: 0 2px 6px rgba(0,0,0,0.3);
      "></div>
      <div style="
        position: absolute;
        top: 50%;
        left: 50%;
        transform: translate(-50%, -50%);
        width: 40px;
        height: 40px;
        background: rgba(66, 133, 244, 0.2);
        border-radius: 50%;
        animation: pulse 2s ease-out infinite;
      "></div>
    </div>
  `,
  iconSize: [20, 20],
  iconAnchor: [10, 10],
  popupAnchor: [0, -10],
});

// Component to handle map centering
function MapController({ center }: { center: [number, number] }) {
  const map = useMap();

  useEffect(() => {
    map.setView(center, map.getZoom());
  }, [center, map]);

  return null;
}

// Station with distance
type StationWithDistance = PublicStationResponse & { distance: number | null };

export const StationsScreen = () => {
  const api = useApi();
  const [selectedStation, setSelectedStation] = useState<StationWithDistance | null>(null);
  const mapRef = useRef<L.Map | null>(null);

  // Fetch and cache user location with React Query
  const { data: userLocation, isLoading: isLoadingLocation, refetch: refetchLocation } = useQuery({
    queryKey: ['user-location'],
    queryFn: async () => {
      // First, check current permission status
      const permissionStatus = await Geolocation.checkPermissions();
      console.log('Location permission status:', permissionStatus);

      // If permission is not granted, request it
      if (permissionStatus.location !== 'granted') {
        console.log('Requesting location permission...');
        const requestResult = await Geolocation.requestPermissions();
        console.log('Permission request result:', requestResult);

        // If still not granted after request, return null
        if (requestResult.location !== 'granted') {
          return null;
        }
      }

      // Permission granted, get location
      console.log('Permission granted, attempting to get position...');

      try {
        const position = await Geolocation.getCurrentPosition({
          enableHighAccuracy: true,
          timeout: 15000,
          maximumAge: 0,
        });

        console.log('Position obtained:', position);

        return {
          lat: position.coords.latitude,
          lng: position.coords.longitude,
        };
      } catch (positionError) {
        console.error('Error getting position (high accuracy):', positionError);

        // Try again with lower accuracy
        console.log('Retrying with lower accuracy...');
        const position = await Geolocation.getCurrentPosition({
          enableHighAccuracy: false,
          timeout: 10000,
          maximumAge: 10000,
        });

        console.log('Position obtained (low accuracy):', position);

        return {
          lat: position.coords.latitude,
          lng: position.coords.longitude,
        };
      }
    },
    staleTime: 5 * 60 * 1000, // 5 minutes - location doesn't change that often
    gcTime: 30 * 60 * 1000, // 30 minutes - keep in cache
    retry: false, // Don't retry if permission denied
    refetchOnMount: false, // Don't refetch on mount if data is fresh
  });

  const [mapCenter, setMapCenter] = useState<[number, number]>(
    userLocation ? [userLocation.lat, userLocation.lng] : [28.6139, 77.2090]
  );

  // Fetch all public stations
  const { data: stationsData, isLoading, error, refetch } = useQuery({
    queryKey: ['public-stations'],
    queryFn: () => publicStationService(api).getAll(),
    staleTime: 2 * 60 * 1000, // 2 minutes - data stays fresh
    gcTime: 10 * 60 * 1000, // 10 minutes - keep in cache
    refetchInterval: false,
    refetchOnMount: false, // Don't refetch on mount if data is fresh
    placeholderData: (previousData) => previousData, // Keep showing old data while refetching
  });

  // Update map center when location is obtained
  useEffect(() => {
    if (userLocation) {
      setMapCenter([userLocation.lat, userLocation.lng]);
    }
  }, [userLocation]);

  // Calculate distance between two coordinates (Haversine formula)
  const calculateDistance = (lat1: number, lon1: number, lat2: number, lon2: number): number => {
    const R = 6371; // Earth's radius in km
    const dLat = (lat2 - lat1) * Math.PI / 180;
    const dLon = (lon2 - lon1) * Math.PI / 180;
    const a =
      Math.sin(dLat/2) * Math.sin(dLat/2) +
      Math.cos(lat1 * Math.PI / 180) * Math.cos(lat2 * Math.PI / 180) *
      Math.sin(dLon/2) * Math.sin(dLon/2);
    const c = 2 * Math.atan2(Math.sqrt(a), Math.sqrt(1-a));
    return R * c;
  };

  // Get stations with distance from user (memoized to avoid recalculating on every render)
  const stationsWithDistance = useMemo(() => {
    if (!stationsData?.data) return [];

    return stationsData.data.map(station => ({
      ...station,
      distance: userLocation
        ? calculateDistance(userLocation.lat, userLocation.lng, station.latitude, station.longitude)
        : null,
    })).sort((a, b) => {
      if (a.distance === null) return 1;
      if (b.distance === null) return -1;
      return a.distance - b.distance;
    });
  }, [stationsData, userLocation]);

  // Show skeleton on initial load, not on refetch
  if (isLoading && !stationsData) {
    return <StationsSkeleton />;
  }

  if (error) {
    return (
      <div className="flex items-center justify-center h-full p-4">
        <div className="bg-red-50 border border-red-200 rounded-lg p-6 max-w-md w-full">
          <div className="flex items-center space-x-3 mb-4">
            <div className="bg-red-100 p-3 rounded-full">
              <AlertCircle className="w-6 h-6 text-red-600" />
            </div>
            <h3 className="text-lg font-semibold text-red-900">Failed to load stations</h3>
          </div>
          <p className="text-sm text-red-700 mb-4">
            {(error as any)?.message || 'Unable to fetch charging stations. Please check your connection.'}
          </p>
          <button
            onClick={() => refetch()}
            className="w-full bg-red-600 text-white py-3 rounded-lg font-semibold hover:bg-red-700 transition-colors"
          >
            Try Again
          </button>
        </div>
      </div>
    );
  }

  return (
    <PullToRefresh onRefresh={async () => { await refetch(); }}>
      <div className="flex flex-col" style={{ height: 'calc(100vh - 140px)' }}>
        {/* Header */}
        <div className="p-4 bg-white border-b flex-shrink-0">
        <div className="flex items-center justify-between mb-3">
          <div>
            <h2 className="text-2xl font-bold text-gray-900">Charging Stations</h2>
            <p className="text-sm text-gray-600">
              {stationsData?.total || 0} stations nearby
            </p>
          </div>
          <button
            onClick={() => refetchLocation()}
            disabled={isLoadingLocation}
            className="p-3 bg-blue-600 text-white rounded-full hover:bg-blue-700 transition-colors disabled:opacity-50"
          >
            {isLoadingLocation ? (
              <Loader2 className="w-5 h-5 animate-spin" />
            ) : (
              <Navigation className="w-5 h-5" />
            )}
          </button>
        </div>
      </div>

      {/* Map */}
      <div className="flex-1 relative" style={{ minHeight: '500px' }}>
        <MapContainer
          center={mapCenter}
          zoom={13}
          style={{ height: '100%', width: '100%', minHeight: '500px' }}
          ref={mapRef}
        >
          <TileLayer
            attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'
            url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
          />

          <MapController center={mapCenter} />

          {/* User location marker - blue dot like Google Maps */}
          {userLocation && (
            <Marker position={[userLocation.lat, userLocation.lng]} icon={blueDotIcon}>
              <Popup>
                <div className="text-center">
                  <strong>Your Location</strong>
                </div>
              </Popup>
            </Marker>
          )}

          {/* Station markers */}
          {stationsWithDistance?.map((station) => (
            <Marker
              key={station.id}
              position={[station.latitude, station.longitude]}
              icon={station.available_chargers > 0 ? greenIcon : redIcon}
              eventHandlers={{
                click: () => setSelectedStation(station),
              }}
            >
              <Popup>
                <div className="min-w-[200px]">
                  <h3 className="font-bold text-gray-900 mb-2">{station.name}</h3>

                  <div className="space-y-1 text-sm">
                    <div className="flex items-center justify-between">
                      <span className="text-gray-600">Available:</span>
                      <span className="font-semibold text-green-600">
                        {station.available_chargers}/{station.total_chargers}
                      </span>
                    </div>

                    {station.distance !== null && (
                      <div className="flex items-center justify-between">
                        <span className="text-gray-600">Distance:</span>
                        <span className="font-semibold">
                          {station.distance < 1
                            ? `${Math.round(station.distance * 1000)}m`
                            : `${station.distance.toFixed(1)}km`}
                        </span>
                      </div>
                    )}

                    {station.price_per_kwh && (
                      <div className="flex items-center justify-between">
                        <span className="text-gray-600">Price:</span>
                        <span className="font-semibold">₹{station.price_per_kwh}/kWh</span>
                      </div>
                    )}
                  </div>

                  <p className="text-xs text-gray-600 mt-2">{station.address}</p>

                  <button
                    onClick={() => setSelectedStation(station)}
                    className="w-full mt-3 py-2 bg-blue-600 text-white rounded-lg text-sm font-medium hover:bg-blue-700"
                  >
                    View Details
                  </button>
                </div>
              </Popup>
            </Marker>
          ))}
        </MapContainer>
      </div>

      {/* Station Details Bottom Sheet */}
      {selectedStation && (
        <div className="fixed inset-0 bg-black bg-opacity-50 flex items-end z-[1000]">
          <div className="bg-white rounded-t-2xl w-full max-h-[70vh] overflow-y-auto">
            <div className="p-6 space-y-4">
              {/* Header */}
              <div className="flex items-start justify-between">
                <div className="flex-1">
                  <h3 className="text-xl font-bold text-gray-900 mb-1">
                    {selectedStation.name}
                  </h3>
                  <p className="text-sm text-gray-600">{selectedStation.address}</p>
                </div>
                <button
                  onClick={() => setSelectedStation(null)}
                  className="text-gray-500 hover:text-gray-700 text-2xl leading-none"
                >
                  ✕
                </button>
              </div>

              {/* Stats */}
              <div className="grid grid-cols-2 gap-4">
                <div className="bg-green-50 rounded-lg p-4">
                  <div className="flex items-center space-x-2 mb-1">
                    <Zap className="w-5 h-5 text-green-600" />
                    <span className="text-sm font-medium text-gray-600">Available</span>
                  </div>
                  <p className="text-2xl font-bold text-green-600">
                    {selectedStation.available_chargers}/{selectedStation.total_chargers}
                  </p>
                </div>

                {selectedStation.distance !== null && (
                  <div className="bg-blue-50 rounded-lg p-4">
                    <div className="flex items-center space-x-2 mb-1">
                      <MapPin className="w-5 h-5 text-blue-600" />
                      <span className="text-sm font-medium text-gray-600">Distance</span>
                    </div>
                    <p className="text-2xl font-bold text-blue-600">
                      {selectedStation.distance < 1
                        ? `${Math.round(selectedStation.distance * 1000)}m`
                        : `${selectedStation.distance.toFixed(1)}km`}
                    </p>
                  </div>
                )}
              </div>

              {/* Connector Types */}
              {selectedStation.connector_details.length > 0 && (
                <div>
                  <h4 className="font-semibold text-gray-900 mb-3 flex items-center space-x-2">
                    <Info className="w-4 h-4" />
                    <span>Connector Types</span>
                  </h4>
                  <div className="space-y-2">
                    {selectedStation.connector_details.map((connector, idx) => (
                      <div
                        key={idx}
                        className="flex items-center justify-between bg-gray-50 rounded-lg p-3"
                      >
                        <div>
                          <p className="font-medium text-gray-900">
                            {connector.connector_type}
                          </p>
                          {connector.max_power_kw && (
                            <p className="text-sm text-gray-600">
                              Max {connector.max_power_kw} kW
                            </p>
                          )}
                        </div>
                        <span className="text-sm font-semibold text-gray-700">
                          {connector.available_count}/{connector.total_count} available
                        </span>
                      </div>
                    ))}
                  </div>
                </div>
              )}

              {/* Pricing */}
              {selectedStation.price_per_kwh && (
                <div className="bg-yellow-50 rounded-lg p-4">
                  <p className="text-sm text-gray-600 mb-1">Price per kWh</p>
                  <p className="text-2xl font-bold text-yellow-700">
                    ₹{selectedStation.price_per_kwh}
                  </p>
                </div>
              )}

              {/* Directions Button */}
              <button
                onClick={() => {
                  const url = `https://www.google.com/maps/dir/?api=1&destination=${selectedStation.latitude},${selectedStation.longitude}`;
                  window.open(url, '_blank');
                }}
                className="w-full py-4 bg-blue-600 text-white rounded-lg font-semibold hover:bg-blue-700 transition-colors flex items-center justify-center space-x-2"
              >
                <Navigation className="w-5 h-5" />
                <span>Get Directions</span>
              </button>
            </div>
          </div>
        </div>
      )}
      </div>
    </PullToRefresh>
  );
};
