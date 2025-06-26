"use client";

import { useParams } from "next/navigation";
import { useEffect, useState } from "react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Zap, Play, Square, Activity, Clock, MapPin, X } from "lucide-react";
import {
  useCharger,
  useRemoteStart,
  useRemoteStop,
} from "@/lib/queries/chargers";
import {
  useTransaction,
  useTransactionMeterValues,
} from "@/lib/queries/transactions";

// Transaction data comes exclusively from transaction API

export default function ChargerDetailPage() {
  const params = useParams();
  const chargerId = parseInt(params.id as string);

  // State to track last known transaction ID for persistence
  const [lastTransactionId, setLastTransactionId] = useState<number | null>(
    null
  );

  // TanStack Query hooks
  const {
    data: chargerData,
    isLoading: chargerLoading,
    error: chargerError,
  } = useCharger(chargerId);
  const remoteStartMutation = useRemoteStart();
  const remoteStopMutation = useRemoteStop();

  // Extract data from charger query
  const charger = chargerData?.charger;
  const station = chargerData?.station;
  const currentTransactionId = chargerData?.current_transaction?.transaction_id;

  // Get transaction ID to use (current or last known)
  const transactionIdToShow = currentTransactionId || lastTransactionId;

  // Fetch full transaction details using transactions API
  const { data: transactionData } = useTransaction(transactionIdToShow || 0);
  const transaction = transactionData?.transaction;

  // Track last known transaction ID for persistence
  useEffect(() => {
    if (currentTransactionId) {
      setLastTransactionId(currentTransactionId);
    }
  }, [currentTransactionId]);

  // Meter values query - only enabled if there's a transaction
  const { data: meterValuesData } = useTransactionMeterValues(
    transactionIdToShow || 0
  );
  const meterValues = meterValuesData?.meter_values || [];

  // Helper functions to safely access transaction properties
  const getTransactionId = () => transaction?.id;
  const getTransactionStatus = () =>
    transaction?.transaction_status || "Unknown";
  const getEnergyConsumed = () => transaction?.energy_consumed_kwh;
  const getStartTime = () => transaction?.start_time;

  // Clear transaction handler
  const clearTransaction = () => {
    setLastTransactionId(null);
  };

  const handleRemoteStart = () => {
    if (!charger) return;
    // Clear last transaction when starting new one
    setLastTransactionId(null);
    remoteStartMutation.mutate({ id: chargerId });
  };

  const handleRemoteStop = () => {
    if (!charger || !currentTransactionId) return;
    remoteStopMutation.mutate({ id: chargerId });
  };

  const getStatusColor = (status: string) => {
    switch (status) {
      case "Available":
        return "bg-green-100 text-green-800 dark:bg-green-900/20 dark:text-green-400";
      case "Preparing":
        return "bg-yellow-100 text-yellow-800 dark:bg-yellow-900/20 dark:text-yellow-400";
      case "Charging":
        return "bg-blue-100 text-blue-800 dark:bg-blue-900/20 dark:text-blue-400";
      case "SuspendedEVSE":
      case "SuspendedEV":
        return "bg-orange-100 text-orange-800 dark:bg-orange-900/20 dark:text-orange-400";
      case "Finishing":
        return "bg-purple-100 text-purple-800 dark:bg-purple-900/20 dark:text-purple-400";
      case "Reserved":
        return "bg-indigo-100 text-indigo-800 dark:bg-indigo-900/20 dark:text-indigo-400";
      case "Unavailable":
        return "bg-red-100 text-red-800 dark:bg-red-900/20 dark:text-red-400";
      case "Faulted":
        return "bg-destructive/10 text-destructive";
      default:
        return "bg-muted text-muted-foreground";
    }
  };

  const getConnectionStatusColor = (connected: boolean) => {
    return connected
      ? "bg-green-100 text-green-800 dark:bg-green-900/20 dark:text-green-400"
      : "bg-red-100 text-red-800 dark:bg-red-900/20 dark:text-red-400";
  };

  const canStartCharging = () => {
    return (
      charger &&
      charger.latest_status === "Preparing" &&
      charger.connection_status &&
      !currentTransactionId
    );
  };

  const canStopCharging = () => {
    return (
      charger &&
      currentTransactionId &&
      (charger.latest_status === "Charging" ||
        transaction?.transaction_status === "RUNNING")
    );
  };

  const isActionLoading =
    remoteStartMutation.isPending || remoteStopMutation.isPending;

  if (chargerLoading) {
    return (
      <div className="flex items-center justify-center py-8">
        <div className="text-center">
          <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-primary mx-auto"></div>
          <p className="text-muted-foreground mt-2">
            Loading charger details...
          </p>
        </div>
      </div>
    );
  }

  if (chargerError || !charger) {
    return (
      <div className="text-center py-8">
        <p className="text-destructive">Failed to load charger details</p>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex justify-between items-start">
        <div>
          <h1 className="text-3xl font-bold">{charger.name}</h1>
          <p className="text-muted-foreground">
            ID: {charger.charge_point_string_id}
          </p>
          {station && (
            <div className="flex items-center gap-2 mt-2">
              <MapPin className="h-4 w-4 text-muted-foreground" />
              <span className="text-sm text-muted-foreground">
                {station.name} - {station.address}
              </span>
            </div>
          )}
        </div>
      </div>

      {/* Status and Controls */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
        {/* Status Card */}
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <Activity className="h-5 w-5" />
              Charger Status
            </CardTitle>
          </CardHeader>
          <CardContent className="space-y-4">
            <div className="flex justify-between items-center">
              <span className="text-sm font-medium">Status:</span>
              <Badge className={getStatusColor(charger.latest_status)}>
                {charger.latest_status}
              </Badge>
            </div>
            <div className="flex justify-between items-center">
              <span className="text-sm font-medium">Connection:</span>
              <Badge
                className={getConnectionStatusColor(charger.connection_status)}>
                {charger.connection_status ? "Connected" : "Disconnected"}
              </Badge>
            </div>
            <div className="flex justify-between items-center">
              <span className="text-sm font-medium">Last Heartbeat:</span>
              <div className="flex items-center gap-2">
                <Clock className="h-4 w-4 text-muted-foreground" />
                <span className="text-sm">
                  {charger.last_heart_beat_time
                    ? new Date(charger.last_heart_beat_time).toLocaleString()
                    : "Never"}
                </span>
              </div>
            </div>
          </CardContent>
        </Card>

        {/* Controls Card */}
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <Zap className="h-5 w-5" />
              Charging Controls
            </CardTitle>
          </CardHeader>
          <CardContent className="space-y-4">
            <Button
              onClick={handleRemoteStart}
              disabled={!canStartCharging() || isActionLoading}
              className="w-full"
              variant={canStartCharging() ? "default" : "secondary"}>
              <Play className="h-4 w-4 mr-2" />
              {remoteStartMutation.isPending ? "Starting..." : "Start Charging"}
            </Button>

            <Button
              onClick={handleRemoteStop}
              disabled={!canStopCharging() || isActionLoading}
              className="w-full"
              variant={canStopCharging() ? "destructive" : "secondary"}>
              <Square className="h-4 w-4 mr-2" />
              {remoteStopMutation.isPending ? "Stopping..." : "Stop Charging"}
            </Button>

            {!canStartCharging() && !canStopCharging() && (
              <p className="text-sm text-muted-foreground text-center">
                {!charger.connection_status
                  ? "Charger is disconnected"
                  : charger.latest_status !== "Preparing" &&
                    !currentTransactionId
                  ? `Cannot start - status is ${charger.latest_status}`
                  : "No actions available"}
              </p>
            )}
          </CardContent>
        </Card>
      </div>

      {/* Current Transaction */}
      {transaction && (
        <Card>
          <CardHeader className="flex flex-row items-center justify-between">
            <CardTitle>
              {currentTransactionId
                ? "Current Charging Session"
                : "Last Charging Session"}
            </CardTitle>
            {!currentTransactionId && transaction && (
              <Button
                variant="ghost"
                size="sm"
                onClick={clearTransaction}
                className="h-8 w-8 p-0">
                <X className="h-4 w-4" />
              </Button>
            )}
          </CardHeader>
          <CardContent>
            <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
              <div>
                <p className="text-sm font-medium">Transaction ID</p>
                <p className="text-2xl font-bold">
                  {getTransactionId() || "N/A"}
                </p>
              </div>
              <div>
                <p className="text-sm font-medium">Status</p>
                <Badge>{getTransactionStatus()}</Badge>
              </div>
              <div>
                <p className="text-sm font-medium">Started</p>
                <p className="text-sm">
                  {getStartTime()
                    ? new Date(getStartTime()!).toLocaleString()
                    : "N/A"}
                </p>
              </div>
              <div>
                <p className="text-sm font-medium">Energy Consumed</p>
                <p className="text-2xl font-bold">
                  {(getEnergyConsumed() || 0).toFixed(2)} kWh
                </p>
              </div>
            </div>
          </CardContent>
        </Card>
      )}

      {/* Meter Values */}
      {meterValues.length > 0 && (
        <Card>
          <CardHeader>
            <CardTitle>Live Meter Values</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-4">
              {meterValues.slice(-1).map((mv) => (
                <div key={mv.id} className="space-y-2">
                  <div>
                    <p className="text-sm font-medium">Energy Reading</p>
                    <p className="text-xl font-bold">
                      {mv.reading_kwh.toFixed(2)} kWh
                    </p>
                  </div>
                  {mv.power_kw && (
                    <div>
                      <p className="text-sm font-medium">Power</p>
                      <p className="text-lg font-semibold">
                        {mv.power_kw.toFixed(2)} kW
                      </p>
                    </div>
                  )}
                  {mv.current && (
                    <div>
                      <p className="text-sm font-medium">Current</p>
                      <p className="text-lg font-semibold">
                        {mv.current.toFixed(2)} A
                      </p>
                    </div>
                  )}
                  {mv.voltage && (
                    <div>
                      <p className="text-sm font-medium">Voltage</p>
                      <p className="text-lg font-semibold">
                        {mv.voltage.toFixed(2)} V
                      </p>
                    </div>
                  )}
                </div>
              ))}
            </div>

            {/* Recent Meter Values Table */}
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b">
                    <th className="text-left p-2">Time</th>
                    <th className="text-left p-2">Energy (kWh)</th>
                    <th className="text-left p-2">Power (kW)</th>
                    <th className="text-left p-2">Current (A)</th>
                    <th className="text-left p-2">Voltage (V)</th>
                  </tr>
                </thead>
                <tbody>
                  {meterValues
                    .slice(-10)
                    .reverse()
                    .map((mv) => (
                      <tr key={mv.id} className="border-b">
                        <td className="p-2">
                          {new Date(mv.created_at).toLocaleTimeString()}
                        </td>
                        <td className="p-2">{mv.reading_kwh.toFixed(2)}</td>
                        <td className="p-2">
                          {mv.power_kw?.toFixed(2) || "-"}
                        </td>
                        <td className="p-2">{mv.current?.toFixed(2) || "-"}</td>
                        <td className="p-2">{mv.voltage?.toFixed(2) || "-"}</td>
                      </tr>
                    ))}
                </tbody>
              </table>
            </div>
          </CardContent>
        </Card>
      )}
    </div>
  );
}
