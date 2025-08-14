"use client";

import { useState, useEffect } from "react";
import { Navigation, Zap, Clock, Star } from "lucide-react";
import dynamic from "next/dynamic";

import { Button } from "@/components/ui/button";
import { useStations } from "@/lib/queries/stations";

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

interface Station {
  id: number;
  name: string;
  address: string;
  latitude: number;
  longitude: number;
  distance?: number;
  availableChargers?: number;
  totalChargers?: number;
  rating?: number;
  pricePerKwh?: number;
}

export default function StationsPage() {
  const [userLocation, setUserLocation] = useState<{lat: number; lng: number} | null>(null);
  const [selectedStation, setSelectedStation] = useState<Station | null>(null);

  // Fetch stations data
  const { data: stationsData, isLoading } = useStations({ limit: 50 });
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

  // Process stations with distance and mock data
  const processedStations = stations
    .map(station => ({
      ...station,
      distance: userLocation 
        ? calculateDistance(userLocation.lat, userLocation.lng, station.latitude, station.longitude)
        : undefined,
      availableChargers: Math.floor(Math.random() * 8) + 1,
      totalChargers: Math.floor(Math.random() * 4) + 8,
      rating: Number((Math.random() * 2 + 3).toFixed(1)),
      pricePerKwh: Number((Math.random() * 0.20 + 0.25).toFixed(2))
    }))
    .sort((a, b) => (a.distance || 0) - (b.distance || 0));

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
      {/* Full screen map */}
      <div className="w-full h-screen">
        <Map 
          stations={processedStations} 
          userLocation={userLocation}
          onStationSelect={setSelectedStation}
          selectedStation={selectedStation}
        />
      </div>

      {/* Station Detail Modal */}
      {selectedStation && (
        <div className="fixed inset-0 bg-black bg-opacity-50 z-50 flex items-end sm:items-center sm:justify-center">
          <div className="bg-white w-full sm:max-w-md sm:rounded-lg sm:m-4 rounded-t-lg overflow-hidden">
            <div className="p-4 border-b">
              <div className="flex justify-between items-start">
                <div>
                  <h3 className="text-lg font-semibold">{selectedStation.name}</h3>
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
              <div className="grid grid-cols-2 gap-4">
                <div className="text-center p-3 bg-green-50 rounded-lg">
                  <Zap className="h-6 w-6 text-green-600 mx-auto mb-1" />
                  <div className="text-sm font-medium">{selectedStation.availableChargers}/{selectedStation.totalChargers}</div>
                  <div className="text-xs text-gray-600">Available</div>
                </div>
                <div className="text-center p-3 bg-yellow-50 rounded-lg">
                  <Star className="h-6 w-6 text-yellow-500 mx-auto mb-1" />
                  <div className="text-sm font-medium">{selectedStation.rating}</div>
                  <div className="text-xs text-gray-600">Rating</div>
                </div>
              </div>
              
              <div className="space-y-2">
                <div className="flex justify-between">
                  <span className="text-gray-600">Price per kWh:</span>
                  <span className="font-medium">${selectedStation.pricePerKwh}</span>
                </div>
                <div className="flex justify-between">
                  <span className="text-gray-600">Distance:</span>
                  <span className="font-medium">{selectedStation.distance?.toFixed(1)} km</span>
                </div>
                <div className="flex justify-between">
                  <span className="text-gray-600">Connector Types:</span>
                  <span className="font-medium">Type 2, CCS</span>
                </div>
              </div>

              <div className="flex gap-2 pt-2">
                <Button
                  className="flex-1"
                  onClick={() => {
                    const url = `https://www.google.com/maps/dir/?api=1&destination=${selectedStation.latitude},${selectedStation.longitude}`;
                    window.open(url, '_blank');
                  }}
                >
                  <Navigation className="h-4 w-4 mr-2" />
                  Get Directions
                </Button>
                <Button variant="outline" className="flex-1">
                  <Clock className="h-4 w-4 mr-2" />
                  Reserve
                </Button>
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}