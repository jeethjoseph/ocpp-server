"use client";

import { useState, useEffect } from "react";
import dynamic from "next/dynamic";
import { Card, CardContent } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
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
  Clock,
  IndianRupee,
  ChevronLeft,
  ChevronRight,
  AlertCircle,
  RefreshCw,
  Navigation,
  Download,
} from "lucide-react";
import { usePublicQRTransactions, viewPublicInvoicePDF } from "@/lib/queries/public-qr-transactions";
import { usePublicStationMap } from "@/lib/queries/public-station-map";
import { QRTransactionItem } from "@/lib/api-services";
import type { StationWithDistance } from "@/components/StationMap";
import { formatTariffRangeAllIn } from "@/lib/utils";

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

function getStatusBadgeClass(status: string) {
  switch (status) {
    case "COMPLETED":
      return "bg-green-100 text-green-800 dark:bg-green-900/20 dark:text-green-400";
    case "CHARGING":
      return "bg-blue-100 text-blue-800 dark:bg-blue-900/20 dark:text-blue-400";
    case "PAID":
      return "bg-amber-100 text-amber-800 dark:bg-amber-900/20 dark:text-amber-400";
    case "REFUNDED":
      return "bg-purple-100 text-purple-800 dark:bg-purple-900/20 dark:text-purple-400";
    case "FAILED":
    case "REFUND_FAILED":
      return "bg-red-100 text-red-800 dark:bg-red-900/20 dark:text-red-400";
    case "EXPIRED":
      return "bg-gray-100 text-gray-800 dark:bg-gray-900/20 dark:text-gray-400";
    default:
      return "bg-muted text-muted-foreground";
  }
}

function formatDuration(minutes: number): string {
  if (minutes < 60) return `${Math.round(minutes)} min`;
  const hours = Math.floor(minutes / 60);
  const mins = Math.round(minutes % 60);
  return mins > 0 ? `${hours}h ${mins}m` : `${hours}h`;
}

function formatDate(isoString: string): string {
  return new Date(isoString).toLocaleDateString("en-IN", {
    day: "numeric",
    month: "short",
    year: "numeric",
  });
}

function formatTime(isoString: string): string {
  return new Date(isoString).toLocaleTimeString("en-IN", {
    hour: "2-digit",
    minute: "2-digit",
  });
}

function formatINR(val: string | null): string | null {
  if (!val) return null;
  const num = parseFloat(val);
  return isNaN(num) ? val : num.toFixed(2);
}

function getErrorMessage(error: Error): string {
  const msg = error.message;
  if (msg.includes("429")) return "Too many requests. Please wait a moment and try again.";
  if (msg.includes("404")) return "No transactions found for this UPI ID.";
  if (msg.includes("400")) return "Please enter a valid UPI ID (e.g. name@bank)";
  if (msg.includes("500")) return "Server error. Please try again later.";
  return "Something went wrong. Please try again.";
}

function TransactionCard({ txn, vpa }: { txn: QRTransactionItem; vpa: string }) {
  return (
    <Card className="border-0 shadow-md bg-card">
      <CardContent className="p-4 space-y-3">
        <div className="flex justify-between items-start">
          <div>
            <p className="text-sm font-medium text-card-foreground">
              {formatDate(txn.created_at)}
            </p>
            <p className="text-xs text-muted-foreground">
              {formatTime(txn.created_at)}
            </p>
          </div>
          <Badge className={`border-0 ${getStatusBadgeClass(txn.status)}`}>
            {txn.status.replace("_", " ")}
          </Badge>
        </div>

        <div className="grid grid-cols-2 gap-3">
          <div className="flex items-center gap-2 p-2 bg-muted/50 rounded-lg">
            <IndianRupee className="h-4 w-4 text-muted-foreground" />
            <div>
              <p className="text-xs text-muted-foreground">Paid</p>
              <p className="font-semibold text-card-foreground">
                {formatINR(txn.amount_paid)}
              </p>
            </div>
          </div>
          <div className="flex items-center gap-2 p-2 bg-muted/50 rounded-lg">
            <Zap className="h-4 w-4 text-muted-foreground" />
            <div>
              <p className="text-xs text-muted-foreground">Energy</p>
              <p className="font-semibold text-card-foreground">
                {txn.energy_consumed_kwh != null
                  ? `${txn.energy_consumed_kwh.toFixed(2)} kWh`
                  : "N/A"}
              </p>
            </div>
          </div>
        </div>

        <div className="grid grid-cols-2 gap-3">
          {txn.duration_minutes != null && (
            <div className="flex items-center gap-2 text-sm text-muted-foreground">
              <Clock className="h-3.5 w-3.5" />
              <span>{formatDuration(txn.duration_minutes)}</span>
            </div>
          )}
          {txn.charger_name && (
            <div className="flex items-center gap-2 text-sm text-muted-foreground truncate">
              <Zap className="h-3.5 w-3.5 flex-shrink-0" />
              <span className="truncate">
                {txn.charger_name}
                {txn.station_name ? ` · ${txn.station_name}` : ""}
              </span>
            </div>
          )}
          {txn.franchisee_name && (
            <div className="text-xs text-muted-foreground truncate pl-5">
              Operator: <span className="font-medium">{txn.franchisee_name}</span>
            </div>
          )}
        </div>

        {txn.energy_cost && (
          <div className="border-t border-border pt-2 space-y-1 text-sm">
            <div className="flex justify-between text-muted-foreground">
              <span>Energy cost</span>
              <span>{formatINR(txn.energy_cost)}</span>
            </div>
            {txn.gst_amount && (
              <div className="flex justify-between text-muted-foreground">
                <span>GST</span>
                <span>{formatINR(txn.gst_amount)}</span>
              </div>
            )}
            {txn.platform_fee && (
              <div className="flex justify-between text-muted-foreground">
                <span>Platform fee{txn.fee_source === 'estimated' ? ' (est.)' : ''}</span>
                <span>{formatINR(txn.platform_fee)}</span>
              </div>
            )}
          </div>
        )}

        {txn.refund_amount && (
          <div className="flex items-center gap-2 p-2 bg-purple-50 dark:bg-purple-900/20 border border-purple-200 dark:border-purple-700 rounded-lg">
            <RefreshCw className="h-4 w-4 text-purple-600 dark:text-purple-400" />
            <span className="text-sm font-medium text-purple-800 dark:text-purple-300">
              Refunded: {formatINR(txn.refund_amount)}
            </span>
          </div>
        )}

        {txn.failure_reason &&
          (txn.status === "FAILED" || txn.status === "REFUND_FAILED") && (
            <div className="flex items-start gap-2 p-2 bg-red-50 dark:bg-red-900/20 border border-red-200 dark:border-red-700 rounded-lg">
              <AlertCircle className="h-4 w-4 text-red-600 dark:text-red-400 mt-0.5 flex-shrink-0" />
              <span className="text-sm text-red-800 dark:text-red-300">
                {txn.failure_reason}
              </span>
            </div>
          )}

        {(txn.status === "COMPLETED" || txn.status === "REFUNDED") && (
          <Button
            variant="outline"
            size="sm"
            className="w-full mt-2"
            onClick={async () => {
              try {
                await viewPublicInvoicePDF(txn.id, vpa);
              } catch (e) {
                alert(`PDF download failed: ${(e as Error).message}`);
              }
            }}
          >
            <Download className="h-4 w-4 mr-2" />
            Download GST Invoice
          </Button>
        )}
      </CardContent>
    </Card>
  );
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

  const totalPages = data ? Math.ceil(data.total / limit) : 1;

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
  };

  const handleReset = () => {
    setVpaInput("");
    setSearchedVpa("");
    setStatusFilter("ALL");
    setCurrentPage(1);
  };

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
              <div className="flex justify-center">
                <div className="text-center p-3 bg-green-50 dark:bg-green-900/20 rounded-lg w-48">
                  <Zap className="h-6 w-6 text-green-600 dark:text-green-400 mx-auto mb-1" />
                  <div className="text-sm font-medium text-foreground">
                    {selectedStation.available_chargers}/{selectedStation.total_chargers}
                  </div>
                  <div className="text-xs text-muted-foreground">Available Chargers</div>
                </div>
              </div>

              {selectedStation.connector_details.length > 0 && (
                <div>
                  <h4 className="text-sm font-medium text-foreground mb-2">Connectors</h4>
                  <div className="space-y-2">
                    {selectedStation.connector_details.map((detail, index) => (
                      <div key={index} className="flex items-center justify-between p-2 bg-muted/50 rounded">
                        <div className="flex items-center space-x-2">
                          <div className={`w-2 h-2 rounded-full ${
                            detail.available_count > 0 ? "bg-green-500" : "bg-red-500"
                          }`}></div>
                          <span className="text-sm font-medium text-foreground">
                            {detail.connector_type}
                          </span>
                          {detail.max_power_kw && (
                            <span className="text-xs text-muted-foreground">
                              ({detail.max_power_kw}kW)
                            </span>
                          )}
                        </div>
                        <span className="text-xs text-muted-foreground">
                          {detail.available_count}/{detail.total_count} available
                        </span>
                      </div>
                    ))}
                  </div>
                </div>
              )}

              <div className="space-y-2">
                <div className="flex justify-between">
                  <span className="text-muted-foreground">Price per kWh:</span>
                  <span className="font-medium text-foreground text-right">
                    {formatTariffRangeAllIn(
                      selectedStation.min_price_per_kwh_all_in,
                      selectedStation.max_price_per_kwh_all_in,
                    )}
                  </span>
                </div>
                {selectedStation.distance != null && (
                  <div className="flex justify-between">
                    <span className="text-muted-foreground">Distance:</span>
                    <span className="font-medium text-foreground">
                      {selectedStation.distance.toFixed(1)} km
                    </span>
                  </div>
                )}
              </div>

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
