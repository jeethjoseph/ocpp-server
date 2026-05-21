"use client";

import { useState, useEffect } from "react";
import dynamic from "next/dynamic";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  Search,
  Zap,
  ChevronLeft,
  ChevronRight,
  AlertCircle,
  Navigation,
} from "lucide-react";
import { usePublicQRTransactions } from "@/lib/queries/public-qr-transactions";
import { usePublicQRActiveSessions } from "@/lib/queries/public-qr-active-sessions";
import { usePublicStationMap } from "@/lib/queries/public-station-map";
import type { StationWithDistance } from "@/components/StationMap";
import { ChargerRow } from "./_components/ChargerRow";
import { TransactionCard } from "./_components/TransactionCard";
import {
  ActiveSessionCard,
  ActiveSessionSkeleton,
} from "./_components/ActiveSessionCard";
import { ActiveSessionsError } from "./_components/ActiveSessionsError";

const Map = dynamic(() => import("@/components/StationMap"), {
  ssr: false,
  loading: () => (
    <div className="w-full h-full bg-muted flex items-center justify-center">
      <div className="text-center">
        <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-primary mx-auto"></div>
        <p className="text-sm text-muted-foreground mt-2">Loading map...</p>
      </div>
    </div>
  ),
});

const STATUS_OPTIONS = [
  { value: "ALL", label: "All Statuses" },
  { value: "COMPLETED", label: "Completed" },
  { value: "REFUNDED", label: "Refunded" },
  { value: "CHARGING", label: "Charging" },
  { value: "PAID", label: "Paid" },
  { value: "FAILED", label: "Failed" },
  { value: "REFUND_FAILED", label: "Refund Failed" },
  { value: "EXPIRED", label: "Expired" },
];

function getErrorMessage(error: Error): string {
  const msg = error.message;
  if (msg.includes("429")) return "Too many requests. Please wait a moment and try again.";
  if (msg.includes("404")) return "No transactions found for this UPI ID.";
  if (msg.includes("400")) return "Please enter a valid UPI ID (e.g. name@bank)";
  if (msg.includes("500")) return "Server error. Please try again later.";
  return "Something went wrong. Please try again.";
}

// localStorage key namespacing — page-scoped so future surfaces don't collide.
// Old unnamespaced key is migrated on first read.
const VPA_STORAGE_KEY = "voltlync.myCharges.lastVpa";
const VPA_LEGACY_KEY = "voltlync.lastVpa";
const VPA_INPUT_PATTERN = /^[a-zA-Z0-9][a-zA-Z0-9.\-_]{0,253}@[a-zA-Z][a-zA-Z0-9]{1,}$/;
// MUST stay in sync with VPA_PATTERN in backend/core/validators.py.

function readStoredVpa(): string {
  if (typeof window === "undefined") return "";
  try {
    let v = window.localStorage.getItem(VPA_STORAGE_KEY);
    if (!v) {
      // One-time migration from the pre-namespacing key.
      const legacy = window.localStorage.getItem(VPA_LEGACY_KEY);
      if (legacy && VPA_INPUT_PATTERN.test(legacy)) {
        window.localStorage.setItem(VPA_STORAGE_KEY, legacy);
        window.localStorage.removeItem(VPA_LEGACY_KEY);
        v = legacy;
      }
    }
    if (v && VPA_INPUT_PATTERN.test(v)) return v;
  } catch {
    // localStorage can throw in private mode / quota cases — ignore.
  }
  return "";
}

function persistVpa(v: string) {
  if (typeof window === "undefined") return;
  try {
    window.localStorage.setItem(VPA_STORAGE_KEY, v);
  } catch {
    // ignore
  }
}

function clearStoredVpa() {
  if (typeof window === "undefined") return;
  try {
    window.localStorage.removeItem(VPA_STORAGE_KEY);
    window.localStorage.removeItem(VPA_LEGACY_KEY);
  } catch {
    // ignore
  }
}

function calculateDistance(lat1: number, lon1: number, lat2: number, lon2: number) {
  const R = 6371;
  const dLat = ((lat2 - lat1) * Math.PI) / 180;
  const dLon = ((lon2 - lon1) * Math.PI) / 180;
  const a =
    Math.sin(dLat / 2) * Math.sin(dLat / 2) +
    Math.cos((lat1 * Math.PI) / 180) *
      Math.cos((lat2 * Math.PI) / 180) *
      Math.sin(dLon / 2) *
      Math.sin(dLon / 2);
  const c = 2 * Math.atan2(Math.sqrt(a), Math.sqrt(1 - a));
  return R * c;
}

export default function MyChargesPage() {
  const [vpaInput, setVpaInput] = useState("");
  const [searchedVpa, setSearchedVpa] = useState("");
  const [statusFilter, setStatusFilter] = useState("ALL");
  const [currentPage, setCurrentPage] = useState(1);
  const limit = 10;

  // Map state
  const [userLocation, setUserLocation] = useState<{ lat: number; lng: number } | null>(null);
  const [selectedStation, setSelectedStation] = useState<StationWithDistance | null>(null);
  const [mapRef, setMapRef] = useState<L.Map | null>(null);

  const { data: stationsData, isLoading: isLoadingStations } = usePublicStationMap();
  const stations = stationsData?.data || [];

  const { data, isLoading, error } = usePublicQRTransactions({
    vpa: searchedVpa,
    page: currentPage,
    limit,
    status: statusFilter !== "ALL" ? statusFilter : undefined,
  });

  const activeSessionsQuery = usePublicQRActiveSessions(searchedVpa);
  const activeSessions = activeSessionsQuery.data?.data ?? [];

  const totalPages = data ? Math.ceil(data.total / limit) : 1;

  // Pre-fill VPA from localStorage (but don't auto-search; the user taps to commit)
  useEffect(() => {
    const stored = readStoredVpa();
    if (stored) setVpaInput(stored);
  }, []);

  // Get user location
  useEffect(() => {
    if (navigator.geolocation) {
      navigator.geolocation.getCurrentPosition(
        (position) => {
          setUserLocation({
            lat: position.coords.latitude,
            lng: position.coords.longitude,
          });
        },
        () => {
          // No default fallback — map will fit to station bounds
        }
      );
    }
  }, []);

  const processedStations: StationWithDistance[] = stations
    .map((station) => ({
      ...station,
      distance: userLocation
        ? calculateDistance(userLocation.lat, userLocation.lng, station.latitude, station.longitude)
        : undefined,
    }))
    .sort((a, b) => (a.distance || 0) - (b.distance || 0));

  const centerOnStation = (station: StationWithDistance) => {
    if (mapRef) {
      mapRef.setView([station.latitude, station.longitude], 15);
    }
  };

  const handleSearch = (e: React.FormEvent<HTMLFormElement>) => {
    e.preventDefault();
    const trimmed = vpaInput.trim().toLowerCase();
    if (!trimmed) return;
    setSearchedVpa(trimmed);
    setCurrentPage(1);
    setStatusFilter("ALL");
    if (VPA_INPUT_PATTERN.test(trimmed)) persistVpa(trimmed);
  };

  const handleReset = () => {
    setVpaInput("");
    setSearchedVpa("");
    setStatusFilter("ALL");
    setCurrentPage(1);
    clearStoredVpa();
  };

  // First-load skeleton: only when we have a VPA, no prior data, and the query
  // is fetching. Subsequent polls update silently.
  const showActiveSkeleton =
    !!searchedVpa &&
    activeSessionsQuery.isLoading &&
    !activeSessionsQuery.data;

  // Error banner: shown when the query failed at least once and we have no
  // last-good response to display. If a poll fails but a prior poll succeeded,
  // we keep showing the stale data silently rather than flashing red.
  const showActiveError =
    !!searchedVpa &&
    !!activeSessionsQuery.error &&
    !activeSessionsQuery.data;

  return (
    <div className="min-h-screen bg-background">
      {/* Map section */}
      <div className="px-4 py-3 border-b border-border">
        <h2 className="text-lg font-semibold text-foreground">Charging Stations Nearby</h2>
        <p className="text-sm text-muted-foreground">Tap a station to see details and get directions</p>
      </div>
      <div className="w-full h-[40vh]">
        {isLoadingStations ? (
          <div className="w-full h-full bg-muted flex items-center justify-center">
            <div className="text-center">
              <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-primary mx-auto"></div>
              <p className="text-sm text-muted-foreground mt-2">Finding charging stations...</p>
            </div>
          </div>
        ) : (
          <Map
            stations={processedStations}
            userLocation={userLocation}
            onStationSelect={setSelectedStation}
            selectedStation={selectedStation}
            onStationCenter={centerOnStation}
            onMapReady={setMapRef}
          />
        )}
      </div>

      {/* Station detail modal */}
      {selectedStation && (
        <div className="fixed inset-0 bg-black bg-opacity-50 z-50 flex items-end sm:items-center sm:justify-center">
          <div className="bg-background w-full sm:max-w-md sm:rounded-lg sm:m-4 rounded-t-lg overflow-hidden">
            <div className="p-4 border-b border-border">
              <div className="flex justify-between items-start">
                <div>
                  <h3 className="text-lg font-semibold text-foreground">{selectedStation.name}</h3>
                  <p className="text-muted-foreground text-sm">{selectedStation.address}</p>
                </div>
                <button
                  onClick={() => setSelectedStation(null)}
                  className="text-muted-foreground hover:text-foreground"
                >
                  &times;
                </button>
              </div>
            </div>
            <div className="p-4 space-y-4">
              {selectedStation.connector_details.length > 0 && (
                <div>
                  <h4 className="text-sm font-medium text-foreground mb-2">Chargers</h4>
                  <div className="space-y-2">
                    {selectedStation.connector_details.map((detail, index) => (
                      <ChargerRow key={index} detail={detail} />
                    ))}
                  </div>
                  <p className="text-[11px] text-muted-foreground mt-2">
                    * all prices include GST &amp; fees
                  </p>
                </div>
              )}

              {selectedStation.distance != null && (
                <div className="flex justify-between text-sm">
                  <span className="text-muted-foreground">Distance:</span>
                  <span className="font-medium text-foreground">
                    {selectedStation.distance.toFixed(1)} km
                  </span>
                </div>
              )}

              <Button
                className="w-full"
                onClick={() => {
                  const url = `https://www.google.com/maps/dir/?api=1&destination=${selectedStation.latitude},${selectedStation.longitude}`;
                  window.open(url, "_blank");
                }}
              >
                <Navigation className="h-4 w-4 mr-2" />
                Get Directions
              </Button>
            </div>
          </div>
        </div>
      )}

      {/* Transaction History section */}
      <div className="px-4 py-6 space-y-6 max-w-md mx-auto">
        {/* Header */}
        <div>
          <h1 className="text-2xl font-bold text-foreground">
            Transaction History
          </h1>
          <p className="text-sm text-muted-foreground mt-1">
            Enter your UPI ID to view your QR charging transactions
          </p>
        </div>

        {/* Search form */}
        <form onSubmit={handleSearch} className="flex gap-2">
          <Input
            type="text"
            placeholder="your-upi@bank"
            value={vpaInput}
            onChange={(e) => setVpaInput(e.target.value)}
            className="flex-1"
          />
          <Button type="submit" disabled={!vpaInput.trim()}>
            <Search className="h-4 w-4" />
          </Button>
        </form>

        {/* Error display */}
        {error && (
          <div className="bg-red-50 dark:bg-red-900/20 border border-red-200 dark:border-red-700 p-4 rounded-lg text-center">
            <AlertCircle className="h-5 w-5 text-red-600 dark:text-red-400 mx-auto mb-2" />
            <p className="text-sm text-red-800 dark:text-red-300">
              {getErrorMessage(error)}
            </p>
          </div>
        )}

        {/* Results */}
        {searchedVpa && (
          <>
            {/* VPA badge + change */}
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-2 text-sm text-muted-foreground">
                <Zap className="h-4 w-4" />
                <span>{searchedVpa}</span>
              </div>
              <Button variant="ghost" size="sm" onClick={handleReset}>
                Change
              </Button>
            </div>

            {/* Active sessions (live) */}
            {showActiveSkeleton && <ActiveSessionSkeleton />}
            {showActiveError && (
              <ActiveSessionsError onRetry={() => activeSessionsQuery.refetch()} />
            )}
            {activeSessions.length > 0 && (
              <div className="space-y-3">
                {activeSessions.map((s) => (
                  <ActiveSessionCard key={s.qr_payment_id} session={s} />
                ))}
              </div>
            )}

            {/* Status filter */}
            <Select value={statusFilter} onValueChange={(val) => {
              setStatusFilter(val);
              setCurrentPage(1);
            }}>
              <SelectTrigger className="w-full">
                <SelectValue placeholder="Filter by status" />
              </SelectTrigger>
              <SelectContent>
                {STATUS_OPTIONS.map((opt) => (
                  <SelectItem key={opt.value} value={opt.value}>
                    {opt.label}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>

            {/* Loading */}
            {isLoading && (
              <div className="text-center py-12">
                <div className="animate-spin rounded-full h-10 w-10 border-b-2 border-primary mx-auto" />
                <p className="text-muted-foreground mt-4">Loading transactions...</p>
              </div>
            )}

            {/* Results */}
            {data && !isLoading && (
              <>
                <p className="text-sm text-muted-foreground">
                  {data.total === 0
                    ? "No transactions found"
                    : `${data.total} transaction${data.total !== 1 ? "s" : ""} found`}
                </p>

                <div className="space-y-3">
                  {data.data.map((txn) => (
                    <TransactionCard key={txn.id} txn={txn} vpa={searchedVpa} />
                  ))}
                </div>

                {totalPages > 1 && (
                  <div className="flex items-center justify-between pt-2">
                    <Button
                      variant="outline"
                      size="sm"
                      disabled={currentPage <= 1}
                      onClick={() => setCurrentPage((p) => Math.max(1, p - 1))}
                    >
                      <ChevronLeft className="h-4 w-4 mr-1" />
                      Prev
                    </Button>
                    <span className="text-sm text-muted-foreground">
                      Page {currentPage} of {totalPages}
                    </span>
                    <Button
                      variant="outline"
                      size="sm"
                      disabled={currentPage >= totalPages}
                      onClick={() => setCurrentPage((p) => Math.min(totalPages, p + 1))}
                    >
                      Next
                      <ChevronRight className="h-4 w-4 ml-1" />
                    </Button>
                  </div>
                )}
              </>
            )}
          </>
        )}

        {/* Initial state */}
        {!searchedVpa && !error && (
          <div className="text-center py-12">
            <Zap className="h-12 w-12 text-muted-foreground/40 mx-auto mb-4" />
            <p className="text-muted-foreground">
              Enter your UPI ID above to look up your charging history
            </p>
          </div>
        )}

        <div className="h-6" />
      </div>
    </div>
  );
}
