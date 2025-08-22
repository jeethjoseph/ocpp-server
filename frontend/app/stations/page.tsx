"use client";

import { useState, useEffect } from "react";
import { Navigation, Zap } from "lucide-react";
import dynamic from "next/dynamic";

import { Button } from "@/components/ui/button";
import { usePublicStations } from "@/lib/queries/public-stations";
import type { PublicStationResponse } from "@/lib/api-services";

// Dynamic import for Leaflet to avoid SSR issues
const Map = dynamic(() => import("./StationMap"), {
  ssr: false,
  loading: () => (
    <div className="w-full h-64 bg-gray-100 rounded-lg flex items-center justify-center">
      <div className="text-center">
        <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-primary mx-auto"></div>
        <p className="text-sm text-gray-600 mt-2">Loading map...</p>
      </div>
    </div>
  ),
});

interface StationWithDistance extends PublicStationResponse {
  distance?: number;
}

export default function StationsPage() {
  const [userLocation, setUserLocation] = useState<{lat: number; lng: number} | null>(null);
  const [selectedStation, setSelectedStation] = useState<StationWithDistance | null>(null);
  const [mapRef, setMapRef] = useState<L.Map | null>(null);

  // Fetch stations data from new public API
  const { data: stationsData, isLoading } = usePublicStations();
  const stations = stationsData?.data || [];

  // Get user location
  useEffect(() => {
    if (navigator.geolocation) {
      navigator.geolocation.getCurrentPosition(
        (position) => {
          setUserLocation({
            lat: position.coords.latitude,
            lng: position.coords.longitude
          });
        },
        () => {
          // Default to a sample location if denied
          setUserLocation({ lat: 37.7749, lng: -122.4194 });
        }
      );
    } else {
      // Default location if geolocation not supported
      setUserLocation({ lat: 37.7749, lng: -122.4194 });
    }
  }, []);

  // Calculate distance between two coordinates
  const calculateDistance = (lat1: number, lon1: number, lat2: number, lon2: number) => {
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

  // Process stations with distance
  const processedStations = stations
    .map(station => ({
      ...station,
      distance: userLocation 
        ? calculateDistance(userLocation.lat, userLocation.lng, station.latitude, station.longitude)
        : undefined,
    }))
    .sort((a, b) => (a.distance || 0) - (b.distance || 0));

  // Function to center map on station
  const centerOnStation = (station: StationWithDistance) => {
    if (mapRef) {
      mapRef.setView([station.latitude, station.longitude], 15);
    }
  };

  if (isLoading) {
    return (
      <div className="flex items-center justify-center py-8">
        <div className="text-center">
          <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-primary mx-auto"></div>
          <p className="text-muted-foreground mt-2">Finding charging stations...</p>
        </div>
      </div>
    );
  }


  return (
    <div className="min-h-screen">
      {/* Map container - fixed height */}
      <div className="w-full h-[60vh]">
        <Map 
          stations={processedStations} 
          userLocation={userLocation}
          onStationSelect={setSelectedStation}
          selectedStation={selectedStation}
          onStationCenter={centerOnStation}
          onMapReady={setMapRef}
        />
      </div>

      {/* Stations List */}
      <div className="bg-white border-t border-gray-200 h-[40vh] overflow-y-auto">
        <div className="p-4">
          <h2 className="text-lg font-semibold text-gray-900 mb-3">Available Charging Stations</h2>
          {processedStations.length === 0 ? (
            <p className="text-gray-600 text-center py-8">No charging stations found</p>
          ) : (
            <div className="space-y-3">
              {processedStations.map((station) => {
                const isAvailable = station.available_chargers > 0;
                const isBusy = station.available_chargers === 0 && station.total_chargers > 0;
                
                return (
                  <div
                    key={station.id}
                    className="border border-gray-200 rounded-lg p-4 hover:shadow-md transition-shadow cursor-pointer"
                    onClick={() => {
                      setSelectedStation(station);
                      centerOnStation(station);
                    }}
                  >
                    <div className="flex justify-between items-start">
                      <div className="flex-1">
                        <h3 className="font-medium text-gray-900">{station.name}</h3>
                        <p className="text-sm text-gray-600 mb-2">{station.address}</p>
                        
                        <div className="flex items-center space-x-4 text-sm">
                          <div className="flex items-center space-x-1">
                            <div className={`w-2 h-2 rounded-full ${
                              isAvailable ? 'bg-green-500' : isBusy ? 'bg-yellow-500' : 'bg-red-500'
                            }`}></div>
                            <span className={`font-medium ${
                              isAvailable ? 'text-green-600' : isBusy ? 'text-yellow-600' : 'text-red-600'
                            }`}>
                              {station.available_chargers}/{station.total_chargers} available
                            </span>
                          </div>
                          
                          {station.distance && (
                            <span className="text-gray-600">{station.distance.toFixed(1)} km away</span>
                          )}
                        </div>
                        
                        <div className="flex items-center justify-between mt-2">
                          <div className="text-sm text-gray-600">
                            <span className="font-medium">Connectors: </span>
                            {station.connector_types.join(', ')}
                          </div>
                          
                          {station.price_per_kwh && (
                            <div className="text-sm font-medium text-gray-900">
                              ₹{station.price_per_kwh}/kWh
                            </div>
                          )}
                        </div>
                      </div>
                      
                      <Button
                        size="sm"
                        className="ml-4 flex-shrink-0"
                        onClick={(e) => {
                          e.stopPropagation();
                          const url = `https://www.google.com/maps/dir/?api=1&destination=${station.latitude},${station.longitude}`;
                          window.open(url, '_blank');
                        }}
                      >
                        <Navigation className="h-4 w-4 mr-1" />
                        Directions
                      </Button>
                    </div>
                  </div>
                );
              })}
            </div>
          )}
        </div>
      </div>

      {/* Station Detail Modal */}
      {selectedStation && (
        <div className="fixed inset-0 bg-black bg-opacity-50 z-50 flex items-end sm:items-center sm:justify-center">
          <div className="bg-white w-full sm:max-w-md sm:rounded-lg sm:m-4 rounded-t-lg overflow-hidden">
            <div className="p-4 border-b">
              <div className="flex justify-between items-start">
                <div>
                  <h3 className="text-lg font-semibold text-gray-900">{selectedStation.name}</h3>
                  <p className="text-gray-600 text-sm">{selectedStation.address}</p>
                </div>
                <button
                  onClick={() => setSelectedStation(null)}
                  className="text-gray-400 hover:text-gray-600"
                >
                  ×
                </button>
              </div>
            </div>
            <div className="p-4 space-y-4">
              <div className="space-y-3">
                <div className="flex justify-center">
                  <div className="text-center p-3 bg-green-50 rounded-lg w-48">
                    <Zap className="h-6 w-6 text-green-600 mx-auto mb-1" />
                    <div className="text-sm font-medium">{selectedStation.available_chargers}/{selectedStation.total_chargers}</div>
                    <div className="text-xs text-gray-600">Available Chargers</div>
                  </div>
                </div>
                
                {/* Individual Charger Details */}
                <div>
                  <h4 className="text-sm font-medium text-gray-900 mb-2">Charger Details</h4>
                  <div className="space-y-2">
                    {selectedStation.connector_details.map((detail, index) => (
                      <div key={index} className="flex items-center justify-between p-2 bg-gray-50 rounded">
                        <div className="flex items-center space-x-2">
                          <div className={`w-2 h-2 rounded-full ${
                            detail.count > 0 ? 'bg-green-500' : 'bg-red-500'
                          }`}></div>
                          <span className="text-sm font-medium text-gray-900">
                            {detail.connector_type}
                          </span>
                          {detail.max_power_kw && (
                            <span className="text-xs text-gray-600">
                              ({detail.max_power_kw}kW)
                            </span>
                          )}
                        </div>
                        <span className="text-xs text-gray-600">
                          {detail.count} available
                        </span>
                      </div>
                    ))}
                  </div>
                </div>
              </div>
              
              <div className="space-y-2">
                <div className="flex justify-between">
                  <span className="text-gray-600">Price per kWh:</span>
                  <span className="font-medium text-gray-900">
                    ₹{selectedStation.price_per_kwh}
                  </span>
                </div>
                <div className="flex justify-between">
                  <span className="text-gray-600">Distance:</span>
                  <span className="font-medium text-gray-900">
                    {selectedStation.distance?.toFixed(1)} km
                  </span>
                </div>
                <div className="flex justify-between items-start">
                  <span className="text-gray-600">Connector Types:</span>
                  <div className="text-right">
                    <span className="font-medium text-sm text-gray-900">
                      {selectedStation.connector_types?.join(', ')}
                    </span>
                  </div>
                </div>
              </div>

              <div className="flex gap-2 pt-2">
                <Button
                  className="w-full"
                  onClick={() => {
                    const url = `https://www.google.com/maps/dir/?api=1&destination=${selectedStation.latitude},${selectedStation.longitude}`;
                    window.open(url, '_blank');
                  }}
                >
                  <Navigation className="h-4 w-4 mr-2" />
                  Get Directions
                </Button>
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}