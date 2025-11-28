"use client";

import { useParams } from "next/navigation";
import { useEffect, useState } from "react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Zap, Play, Square, Activity, Clock, MapPin, X, CreditCard, Download, Signal } from "lucide-react";
import { AdminOnly } from "@/components/RoleWrapper";
import { toast } from "sonner";
import ChargerLogs from "@/components/ChargerLogs";
import MeterValuesChart from "@/components/MeterValuesChart";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  useCharger,
  useRemoteStart,
  useRemoteStop,
  useResetCharger,
  useLatestSignalQuality,
} from "@/lib/queries/chargers";
import {
  useAdminTransaction,
  useAdminTransactionMeterValues,
} from "@/lib/queries/transactions";
import {
  useFirmwareFiles,
  useTriggerUpdate,
  useFirmwareHistory,
} from "@/lib/queries/firmware";

// Transaction data comes exclusively from transaction API

export default function ChargerDetailPage() {
  const params = useParams();
  const chargerId = parseInt(params.id as string);

  // State to track last known transaction ID for persistence
  const [lastTransactionId, setLastTransactionId] = useState<number | null>(
    null
  );

  // Firmware update dialog state
  const [showFirmwareDialog, setShowFirmwareDialog] = useState(false);
  const [selectedFirmwareId, setSelectedFirmwareId] = useState<string>("");

  // Reset dialog state
  const [showResetDialog, setShowResetDialog] = useState(false);
  const [resetType, setResetType] = useState<'Hard' | 'Soft'>('Hard');

  // TanStack Query hooks - they automatically wait for auth
  const {
    data: chargerData,
    isLoading: chargerLoading,
    error: chargerError,
  } = useCharger(chargerId);
  const remoteStartMutation = useRemoteStart();
  const remoteStopMutation = useRemoteStop();
  const resetMutation = useResetCharger();

  // Signal quality query
  const { data: signalQuality } = useLatestSignalQuality(chargerId);

  // Firmware queries
  const { data: firmwareData } = useFirmwareFiles({ is_active: true });
  const { data: firmwareHistoryData } = useFirmwareHistory(chargerId);
  const triggerUpdateMutation = useTriggerUpdate();

  // Extract data from charger query
  const charger = chargerData?.charger;
  const station = chargerData?.station;
  const currentTransactionId = chargerData?.current_transaction?.transaction_id;
  const recentTransactionId = chargerData?.recent_transaction?.transaction_id;

  // Get transaction ID to use (current, recent, or last known)
  const transactionIdToShow = currentTransactionId || recentTransactionId || lastTransactionId;

  // Fetch full transaction details using transactions API
  const { data: transactionData } = useAdminTransaction(transactionIdToShow || 0);
  const transaction = transactionData?.transaction;

  // Track last known transaction ID for persistence
  useEffect(() => {
    if (currentTransactionId) {
      setLastTransactionId(currentTransactionId);
    }
  }, [currentTransactionId]);

  // Meter values query - only enabled if there's a transaction
  const { data: meterValuesData } = useAdminTransactionMeterValues(
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
    remoteStartMutation.mutate({ 
      id: chargerId, 
      connectorId: 1, 
      idTag: "auto" // Backend will use authenticated user's ID
    });
  };

  const handleRemoteStop = () => {
    if (!charger || !currentTransactionId) return;
    remoteStopMutation.mutate({
      id: chargerId,
      reason: "Remote"
    });
  };

  const handleFirmwareUpdate = async () => {
    if (!selectedFirmwareId) return;

    await triggerUpdateMutation.mutateAsync({
      chargerId: chargerId,
      firmwareFileId: parseInt(selectedFirmwareId),
    });

    setShowFirmwareDialog(false);
    setSelectedFirmwareId("");
  };

  const handleReset = async () => {
    if (!chargerData?.charger?.id) return;

    try {
      await resetMutation.mutateAsync({
        chargerId: chargerData.charger.id,
        type: resetType,
      });

      toast.success(`${resetType} reset command sent successfully. The charger will reboot shortly.`);
      setShowResetDialog(false);
    } catch (error) {
      const errorMessage = error instanceof Error
        ? error.message
        : (error as { response?: { data?: { detail?: string } } })?.response?.data?.detail || "Failed to send reset command";
      toast.error(errorMessage);
    }
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

  const getSignalQualityInfo = (rssi?: number) => {
    if (rssi === undefined || rssi === null || rssi === 99) {
      return {
        label: "Unknown",
        color: "bg-gray-100 text-gray-800 dark:bg-gray-900/20 dark:text-gray-400",
      };
    }
    if (rssi >= 10) {
      return {
        label: "Good",
        color: "bg-green-100 text-green-800 dark:bg-green-900/20 dark:text-green-400",
      };
    }
    if (rssi >= 5) {
      return {
        label: "Fair",
        color: "bg-yellow-100 text-yellow-800 dark:bg-yellow-900/20 dark:text-yellow-400",
      };
    }
    return {
      label: "Poor",
      color: "bg-red-100 text-red-800 dark:bg-red-900/20 dark:text-red-400",
    };
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
      <AdminOnly>
        <div className="flex items-center justify-center py-8">
          <div className="text-center">
            <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-primary mx-auto"></div>
            <p className="text-muted-foreground mt-2">
              Loading charger details...
            </p>
          </div>
        </div>
      </AdminOnly>
    );
  }

  if (chargerError || !charger) {
    return (
      <AdminOnly>
        <div className="text-center py-8">
          <p className="text-destructive">Failed to load charger details</p>
        </div>
      </AdminOnly>
    );
  }

  return (
    <AdminOnly>
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
        <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
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
              <div className="flex justify-between items-center">
                <span className="text-sm font-medium">Signal Quality:</span>
                <div className="flex items-center gap-2">
                  <Signal className="h-4 w-4 text-muted-foreground" />
                  <Badge className={getSignalQualityInfo(signalQuality?.rssi).color}>
                    {getSignalQualityInfo(signalQuality?.rssi).label}
                    {signalQuality?.rssi !== undefined && signalQuality?.rssi !== 99 && (
                      <span className="ml-1 text-xs opacity-75">
                        ({signalQuality.rssi})
                      </span>
                    )}
                  </Badge>
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

              <Button
                onClick={() => setShowResetDialog(true)}
                disabled={!charger?.connection_status}
                className="w-full"
                variant="outline">
                <Activity className="h-4 w-4 mr-2" />
                Reset Charger
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
              
              <div className="text-xs text-muted-foreground text-center mt-2">
                Transactions will be linked to your account automatically
              </div>
            </CardContent>
          </Card>

          {/* Firmware Update Card */}
          <Card>
            <CardHeader>
              <CardTitle className="flex items-center gap-2">
                <Download className="h-5 w-5" />
                Firmware Update
              </CardTitle>
            </CardHeader>
            <CardContent className="space-y-4">
              <div className="space-y-2">
                <div className="flex justify-between items-center">
                  <span className="text-sm font-medium">Current Version:</span>
                  <Badge variant="outline">
                    {charger.firmware_version || "Unknown"}
                  </Badge>
                </div>
              </div>

              <Button
                onClick={() => setShowFirmwareDialog(true)}
                disabled={!charger.connection_status}
                className="w-full"
                variant="secondary">
                <Download className="h-4 w-4 mr-2" />
                Update Firmware
              </Button>

              {!charger.connection_status && (
                <p className="text-sm text-muted-foreground text-center">
                  Charger must be online to update
                </p>
              )}

              {/* Recent Update History */}
              {firmwareHistoryData && firmwareHistoryData.data.length > 0 && (
                <div className="mt-4 pt-4 border-t">
                  <p className="text-sm font-medium mb-2">Recent Updates:</p>
                  <div className="space-y-2">
                    {firmwareHistoryData.data.slice(0, 3).map((update) => (
                      <div key={update.id} className="text-xs">
                        <Badge
                          variant={
                            update.status === "INSTALLED"
                              ? "outline"
                              : update.status.includes("FAILED")
                              ? "destructive"
                              : "default"
                          }
                          className="text-xs">
                          {update.status}
                        </Badge>
                        <span className="ml-2 text-muted-foreground">
                          {new Date(update.initiated_at).toLocaleDateString()}
                        </span>
                      </div>
                    ))}
                  </div>
                </div>
              )}
            </CardContent>
          </Card>
        </div>

        {/* Firmware Update Dialog */}
        <Dialog open={showFirmwareDialog} onOpenChange={setShowFirmwareDialog}>
          <DialogContent>
            <DialogHeader>
              <DialogTitle>Update Firmware</DialogTitle>
              <DialogDescription>
                Select a firmware version to install on {charger.name}
              </DialogDescription>
            </DialogHeader>

            <div className="space-y-4">
              <div className="space-y-2">
                <Label htmlFor="firmware-select">Firmware Version</Label>
                <Select value={selectedFirmwareId} onValueChange={setSelectedFirmwareId}>
                  <SelectTrigger id="firmware-select">
                    <SelectValue placeholder="Select firmware version" />
                  </SelectTrigger>
                  <SelectContent>
                    {firmwareData?.data.map((firmware) => (
                      <SelectItem key={firmware.id} value={firmware.id.toString()}>
                        {firmware.version} - {firmware.filename}
                        {firmware.version === charger.firmware_version && " (Current)"}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>

              <div className="bg-yellow-50 dark:bg-yellow-900/20 p-3 rounded-lg text-sm">
                <p className="font-medium mb-1">Safety Checks:</p>
                <ul className="list-disc list-inside space-y-1 text-muted-foreground">
                  <li>Charger must be online</li>
                  <li>No active charging session</li>
                  <li>Update will be sent immediately via OCPP</li>
                </ul>
              </div>
            </div>

            <DialogFooter>
              <Button
                type="button"
                variant="outline"
                onClick={() => setShowFirmwareDialog(false)}>
                Cancel
              </Button>
              <Button
                type="button"
                onClick={handleFirmwareUpdate}
                disabled={!selectedFirmwareId || triggerUpdateMutation.isPending}>
                {triggerUpdateMutation.isPending ? "Sending..." : "Update Firmware"}
              </Button>
            </DialogFooter>
          </DialogContent>
        </Dialog>

        {/* Reset Dialog */}
        <Dialog open={showResetDialog} onOpenChange={setShowResetDialog}>
          <DialogContent>
            <DialogHeader>
              <DialogTitle>Reset Charger</DialogTitle>
              <DialogDescription>
                Choose the type of reset to perform on this charger.
              </DialogDescription>
            </DialogHeader>

            <div className="space-y-4 py-4">
              <div className="space-y-2">
                <Label htmlFor="reset-type">Reset Type</Label>
                <Select value={resetType} onValueChange={(value: 'Hard' | 'Soft') => setResetType(value)}>
                  <SelectTrigger id="reset-type">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="Soft">
                      <div className="flex flex-col items-start">
                        <span className="font-medium">Soft Reset</span>
                        <span className="text-xs text-muted-foreground">
                          Graceful restart - may continue operating
                        </span>
                      </div>
                    </SelectItem>
                    <SelectItem value="Hard">
                      <div className="flex flex-col items-start">
                        <span className="font-medium">Hard Reset</span>
                        <span className="text-xs text-muted-foreground">
                          Complete reboot - stops all operations
                        </span>
                      </div>
                    </SelectItem>
                  </SelectContent>
                </Select>
              </div>

              {resetType === 'Hard' && currentTransactionId && (
                <div className="rounded-md bg-yellow-50 p-3 border border-yellow-200">
                  <p className="text-sm text-yellow-800">
                    ⚠️ Cannot perform Hard reset during active charging session.
                    Please stop the transaction first or choose Soft reset.
                  </p>
                </div>
              )}
            </div>

            <DialogFooter>
              <Button
                variant="outline"
                onClick={() => setShowResetDialog(false)}
              >
                Cancel
              </Button>
              <Button
                onClick={handleReset}
                disabled={resetMutation.isPending || (resetType === 'Hard' && !!currentTransactionId)}
              >
                {resetMutation.isPending ? "Sending..." : `Send ${resetType} Reset`}
              </Button>
            </DialogFooter>
          </DialogContent>
        </Dialog>

        {/* Current Transaction */}
        {transaction && (
          <Card>
            <CardHeader className="flex flex-row items-center justify-between">
              <CardTitle>
                {currentTransactionId
                  ? "Current Charging Session"
                  : recentTransactionId 
                  ? "Recent Charging Session"
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

        {/* Wallet Transactions - Show when transaction ends */}
        {transactionData?.wallet_transactions && transactionData.wallet_transactions.length > 0 && (
          <Card>
            <CardHeader>
              <CardTitle className="flex items-center gap-2">
                <CreditCard className="h-5 w-5" />
                Billing Information
              </CardTitle>
            </CardHeader>
            <CardContent>
              <div className="space-y-3">
                {transactionData.wallet_transactions.map((walletTx) => (
                  <div key={walletTx.id} className="flex justify-between items-start p-3 bg-gray-50 dark:bg-gray-800 rounded-lg">
                    <div className="flex-1">
                      <p className="font-medium">
                        {walletTx.type === 'CHARGE_DEDUCT' ? 'Charging Bill' : walletTx.type}
                      </p>
                      {walletTx.description && (
                        <p className="text-sm text-muted-foreground mt-1">
                          {walletTx.description}
                        </p>
                      )}
                      <p className="text-xs text-muted-foreground mt-1">
                        {new Date(walletTx.created_at).toLocaleString()}
                      </p>
                    </div>
                    <div className="text-right ml-4">
                      <p className={`text-lg font-bold ${
                        walletTx.amount < 0 
                          ? 'text-red-600' 
                          : 'text-green-600'
                      }`}>
                        {walletTx.amount < 0 ? '-' : '+'}₹{Math.abs(walletTx.amount).toFixed(2)}
                      </p>
                      <p className="text-xs text-muted-foreground">
                        {walletTx.amount < 0 ? 'Deducted' : 'Added'}
                      </p>
                    </div>
                  </div>
                ))}
              </div>
              
              {/* Total billing summary */}
              {transactionData.wallet_transactions.length > 0 && (
                <div className="border-t pt-3 mt-3">
                  <div className="flex justify-between items-center">
                    <p className="font-medium">Total Billed:</p>
                    <p className="text-xl font-bold text-red-600">
                      ₹{Math.abs(transactionData.wallet_transactions.reduce(
                        (sum, wt) => sum + (wt.amount < 0 ? Math.abs(wt.amount) : 0), 
                        0
                      )).toFixed(2)}
                    </p>
                  </div>
                </div>
              )}
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
                        {mv.reading_kwh.toFixed(5)} kWh
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

        {/* Meter Values Chart */}
        {meterValues.length > 0 && (
          <MeterValuesChart
            meterValues={meterValues}
            transactionId={getTransactionId()}
          />
        )}

        {/* OCPP Logs Section */}
        {charger && (
          <ChargerLogs 
            chargePointId={charger.charge_point_string_id}
            chargerName={charger.name}
          />
        )}
      </div>
    </AdminOnly>
  );
}