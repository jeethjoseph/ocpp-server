"use client";

import { useParams, useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { 
  Zap, 
  Play, 
  Square, 
  Battery, 
  MapPin, 
  ArrowLeft,
  Bolt,
  Timer,
  Info,
  X,
  Receipt
} from "lucide-react";
import {
  useChargerByStringId,
  useRemoteStartByStringId,
  useRemoteStopByStringId,
} from "@/lib/queries/chargers";
import {
  useTransaction,
  useTransactionMeterValues,
} from "@/lib/queries/transactions";
import { toast } from "sonner";

export default function UserChargePage() {
  const params = useParams();
  const router = useRouter();
  const chargePointId = params.id as string; // This is now a string ID

  const [lastTransactionId, setLastTransactionId] = useState<number | null>(null);
  const [hasActiveTransaction, setHasActiveTransaction] = useState(false);

  const {
    data: chargerData,
    isLoading: chargerLoading,
    error: chargerError,
  } = useChargerByStringId(chargePointId, hasActiveTransaction);

  const remoteStartMutation = useRemoteStartByStringId();
  const remoteStopMutation = useRemoteStopByStringId();

  const charger = chargerData?.charger;
  const station = chargerData?.station;
  const currentTransactionId = chargerData?.current_transaction?.transaction_id;
  const recentTransactionId = chargerData?.recent_transaction?.transaction_id;

  const transactionIdToShow = currentTransactionId || recentTransactionId || lastTransactionId;

  const { data: transactionData } = useTransaction(transactionIdToShow || 0);
  const transaction = transactionData?.transaction;

  const { data: meterValuesData } = useTransactionMeterValues(transactionIdToShow || 0);
  const meterValues = meterValuesData?.meter_values || [];
  const latestMeterValue = meterValues[meterValues.length - 1];

  // Debug logging
  console.log("🔍 Debug - chargerData:", chargerData);
  console.log("🔍 Debug - currentTransactionId:", currentTransactionId);
  console.log("🔍 Debug - transaction:", transaction);
  console.log("🔍 Debug - meterValues:", meterValues);

  useEffect(() => {
    if (currentTransactionId) {
      setLastTransactionId(currentTransactionId);
    }
    setHasActiveTransaction(!!currentTransactionId);
  }, [currentTransactionId]);

  // Clear transaction handler (like admin page)
  const clearTransaction = () => {
    setLastTransactionId(null);
  };

  // Helper functions to safely access transaction properties (like admin page)
  const getTransactionId = () => transaction?.id;
  const getTransactionStatus = () =>
    transaction?.transaction_status || "Unknown";
  const getEnergyConsumed = () => transaction?.energy_consumed_kwh;

  const handleRemoteStart = () => {
    if (!charger) return;
    // Only clear last transaction if we're starting a new one
    // This prevents losing track of recently completed transactions
    setLastTransactionId(null);
    remoteStartMutation.mutate(
      {
        chargePointId,
        connectorId: 1,
      },
      {
        onSuccess: () => {
          toast.success("Charging session started!");
        },
        onError: (error) => {
          toast.error(`Failed to start: ${error.message}`);
        },
      }
    );
  };

  const handleRemoteStop = () => {
    if (!charger || !currentTransactionId) return;
    remoteStopMutation.mutate(
      {
        chargePointId,
        reason: "Remote"
      },
      {
        onSuccess: () => {
          toast.success("Charging session stopped!");
        },
        onError: (error) => {
          toast.error(`Failed to stop: ${error.message}`);
        },
      }
    );
  };

  const getStatusColor = (status: string) => {
    switch (status) {
      case "Available":
        return "bg-green-500 dark:bg-green-600";
      case "Preparing":
        return "bg-yellow-500 dark:bg-yellow-600";
      case "Charging":
        return "bg-blue-500 dark:bg-blue-600";
      case "SuspendedEVSE":
      case "SuspendedEV":
        return "bg-orange-500 dark:bg-orange-600";
      case "Finishing":
        return "bg-purple-500 dark:bg-purple-600";
      case "Reserved":
        return "bg-indigo-500 dark:bg-indigo-600";
      case "Unavailable":
      case "Faulted":
        return "bg-red-500 dark:bg-red-600";
      default:
        return "bg-gray-500 dark:bg-gray-600";
    }
  };

  const getStatusBadgeColor = (status: string) => {
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
      case "Faulted":
        return "bg-red-100 text-red-800 dark:bg-red-900/20 dark:text-red-400";
      default:
        return "bg-muted text-muted-foreground";
    }
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

  const isActionLoading = remoteStartMutation.isPending || remoteStopMutation.isPending;

  const formatDuration = (startTime: string) => {
    const start = new Date(startTime);
    const now = new Date();
    const diff = now.getTime() - start.getTime();
    const hours = Math.floor(diff / (1000 * 60 * 60));
    const minutes = Math.floor((diff % (1000 * 60 * 60)) / (1000 * 60));
    return `${hours}h ${minutes}m`;
  };

  if (chargerLoading) {
    return (
      <div className="min-h-screen bg-background flex items-center justify-center px-4">
        <div className="text-center">
          <div className="animate-spin rounded-full h-16 w-16 border-b-2 border-primary mx-auto"></div>
          <p className="text-muted-foreground mt-6 text-lg">Loading charger...</p>
        </div>
      </div>
    );
  }

  if (chargerError || !charger) {
    return (
      <div className="min-h-screen bg-background flex items-center justify-center px-4">
        <div className="text-center">
          <p className="text-destructive text-xl mb-6">Charger not found</p>
          <Button onClick={() => router.back()} size="lg">
            <ArrowLeft className="h-4 w-4 mr-2" />
            Go Back
          </Button>
        </div>
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-background">
      <div className="px-4 py-6 space-y-6 max-w-md mx-auto">
        {/* Mobile Header with Back Button */}
        <div className="flex items-center gap-3 mb-6">
          <Button variant="ghost" size="icon" onClick={() => router.back()}>
            <ArrowLeft className="h-6 w-6" />
          </Button>
          <div className="flex-1 min-w-0">
            <h1 className="text-xl font-bold truncate">{charger.name}</h1>
            {station && (
              <div className="flex items-center gap-2 text-muted-foreground">
                <MapPin className="h-4 w-4 flex-shrink-0" />
                <span className="text-sm truncate">{station.name}</span>
              </div>
            )}
          </div>
        </div>

        {/* Status Indicator - Large and Prominent */}
        <Card className="border-0 shadow-lg bg-card">
          <CardContent className="pt-8 pb-8">
            <div className="flex flex-col items-center space-y-4">
              <div className={`w-6 h-6 rounded-full ${getStatusColor(charger.latest_status)} animate-pulse`} />
              <Badge 
                className={`text-xl px-6 py-3 font-medium border-0 ${getStatusBadgeColor(charger.latest_status)}`}
              >
                {charger.latest_status}
              </Badge>
              <p className="text-muted-foreground font-medium">
                {charger.connection_status ? "Online" : "Offline"}
              </p>
            </div>
          </CardContent>
        </Card>

        {/* Main Action Button - Full Width, Large */}
        <div className="space-y-4">
          {!currentTransactionId ? (
            <Button
              onClick={handleRemoteStart}
              disabled={!canStartCharging() || isActionLoading}
              size="lg"
              className="w-full h-16 text-xl font-semibold shadow-lg"
            >
              <Play className="h-8 w-8 mr-3" />
              {remoteStartMutation.isPending ? "Starting..." : "Start Charging"}
            </Button>
          ) : (
            <Button
              onClick={handleRemoteStop}
              disabled={!canStopCharging() || isActionLoading}
              size="lg"
              variant="destructive"
              className="w-full h-16 text-xl font-semibold shadow-lg"
            >
              <Square className="h-8 w-8 mr-3" />
              {remoteStopMutation.isPending ? "Stopping..." : "Stop Charging"}
            </Button>
          )}

          {/* Helper Text - Mobile Optimized */}
          {!canStartCharging() && !currentTransactionId && (
            <div className="bg-yellow-50 dark:bg-yellow-900/30 border border-yellow-200 dark:border-yellow-700 p-4 rounded-lg">
              <p className="text-sm text-center text-yellow-800 dark:text-yellow-200 font-medium">
                {!charger.connection_status
                  ? "⚠️ Charger is offline"
                  : charger.latest_status !== "Preparing"
                  ? `Status: ${charger.latest_status}`
                  : "Charger is not ready"}
              </p>
            </div>
          )}
        </div>

        {/* Current Session - Mobile First Layout */}
        {transaction && (
          <Card className="border-0 shadow-lg bg-card">
            <CardHeader className="pb-4 flex flex-row items-center justify-between">
              <CardTitle className="flex items-center gap-2 text-lg text-card-foreground">
                <Battery className="h-5 w-5" />
                {currentTransactionId ? "Active Session" : recentTransactionId ? "Recent Session" : "Last Session"}
              </CardTitle>
              {!currentTransactionId && transaction && (
                <Button
                  variant="ghost"
                  size="sm"
                  onClick={clearTransaction}
                  className="h-8 w-8 p-0 shrink-0">
                  <X className="h-4 w-4" />
                </Button>
              )}
            </CardHeader>
            <CardContent>
              {/* Transaction Status - Mobile First */}
              <div className="flex justify-between items-center mb-4">
                <div>
                  <p className="text-sm text-muted-foreground">Transaction ID</p>
                  <p className="font-semibold">{getTransactionId() || "N/A"}</p>
                </div>
                <Badge>{getTransactionStatus()}</Badge>
              </div>
              
              {/* Energy Display - Prominent */}
              <div className="text-center mb-6">
                <p className="text-sm text-muted-foreground mb-2">
                  {currentTransactionId ? "Live Energy Reading" : "Energy Consumed"}
                </p>
                <p className="text-4xl font-bold text-green-600">
                  {currentTransactionId && latestMeterValue?.reading_kwh 
                    ? latestMeterValue.reading_kwh.toFixed(2)
                    : (getEnergyConsumed() || 0).toFixed(2)
                  }
                </p>
                <p className="text-xl text-green-600">kWh</p>
                {currentTransactionId && latestMeterValue?.reading_kwh && (
                  <p className="text-xs text-muted-foreground mt-1">
                    Live reading from charger
                  </p>
                )}
              </div>
              
              {/* Duration - If Active */}
              {currentTransactionId && transaction.start_time && (
                <div className="text-center mb-6">
                  <p className="text-sm text-muted-foreground mb-2">Duration</p>
                  <p className="text-2xl font-semibold">
                    {formatDuration(transaction.start_time)}
                  </p>
                </div>
              )}

              {/* Live Metrics - Single Column for Mobile */}
              {latestMeterValue && (
                <div className="space-y-3">
                  {latestMeterValue.power_kw && (
                    <div className="flex justify-between items-center p-3 bg-blue-50 dark:bg-blue-900/30 border border-blue-200 dark:border-blue-700 rounded-lg">
                      <div className="flex items-center gap-2">
                        <Timer className="h-5 w-5 text-blue-600 dark:text-blue-400" />
                        <span className="font-medium text-blue-900 dark:text-blue-100">Power</span>
                      </div>
                      <span className="text-lg font-bold text-blue-600 dark:text-blue-400">
                        {latestMeterValue.power_kw.toFixed(1)} kW
                      </span>
                    </div>
                  )}
                  
                  {latestMeterValue.current && (
                    <div className="flex justify-between items-center p-3 bg-green-50 dark:bg-green-900/30 border border-green-200 dark:border-green-700 rounded-lg">
                      <div className="flex items-center gap-2">
                        <Zap className="h-5 w-5 text-green-600 dark:text-green-400" />
                        <span className="font-medium text-green-900 dark:text-green-100">Current</span>
                      </div>
                      <span className="text-lg font-bold text-green-600 dark:text-green-400">
                        {latestMeterValue.current.toFixed(1)} A
                      </span>
                    </div>
                  )}
                  
                  {latestMeterValue.voltage && (
                    <div className="flex justify-between items-center p-3 bg-purple-50 dark:bg-purple-900/30 border border-purple-200 dark:border-purple-700 rounded-lg">
                      <div className="flex items-center gap-2">
                        <Bolt className="h-5 w-5 text-purple-600 dark:text-purple-400" />
                        <span className="font-medium text-purple-900 dark:text-purple-100">Voltage</span>
                      </div>
                      <span className="text-lg font-bold text-purple-600 dark:text-purple-400">
                        {latestMeterValue.voltage.toFixed(0)} V
                      </span>
                    </div>
                  )}
                </div>
              )}
            </CardContent>
          </Card>
        )}

        {/* Billing Information - Show when transaction ends */}
        {transaction && ['COMPLETED', 'STOPPED'].includes(getTransactionStatus()) && (
          <Card className="border-0 shadow-lg bg-card">
            <CardHeader className="pb-4">
              <CardTitle className="flex items-center gap-2 text-lg text-card-foreground">
                <Receipt className="h-5 w-5" />
                Billing Summary
              </CardTitle>
            </CardHeader>
            <CardContent>
              {transactionData?.wallet_transactions && transactionData.wallet_transactions.length > 0 ? (
                <>
                  <div className="space-y-3">
                    {transactionData.wallet_transactions.map((walletTx) => (
                      <div key={walletTx.id} className="flex justify-between items-start p-4 bg-gradient-to-r from-red-50 to-red-100 dark:from-red-900/20 dark:to-red-800/20 border border-red-200 dark:border-red-700 rounded-lg">
                        <div className="flex-1">
                          <p className="font-semibold text-red-900 dark:text-red-100">
                            {walletTx.type === 'CHARGE_DEDUCT' ? '⚡ Charging Bill' : walletTx.type}
                          </p>
                          {walletTx.description && (
                            <p className="text-sm text-red-700 dark:text-red-300 mt-1">
                              {walletTx.description}
                            </p>
                          )}
                          <p className="text-xs text-red-600 dark:text-red-400 mt-2">
                            Billed on {new Date(walletTx.created_at).toLocaleDateString()} at {new Date(walletTx.created_at).toLocaleTimeString([], {hour: '2-digit', minute: '2-digit'})}
                          </p>
                        </div>
                        <div className="text-right ml-4">
                          <p className="text-2xl font-bold text-red-600 dark:text-red-400">
                            ₹{Math.abs(walletTx.amount).toFixed(2)}
                          </p>
                          <p className="text-sm text-red-600 dark:text-red-400 font-medium">
                            Charged
                          </p>
                        </div>
                      </div>
                    ))}
                  </div>

                  {/* Total billing summary - Mobile optimized */}
                  <div className="border-t border-gray-200 dark:border-gray-700 pt-4 mt-4">
                    <div className="bg-gray-50 dark:bg-gray-800 p-4 rounded-lg">
                      <div className="flex justify-between items-center">
                        <p className="text-lg font-semibold text-gray-900 dark:text-gray-100">
                          Total Paid:
                        </p>
                        <p className="text-3xl font-bold text-red-600 dark:text-red-400">
                          ₹{Math.abs(transactionData.wallet_transactions.reduce(
                            (sum, wt) => sum + (wt.amount < 0 ? Math.abs(wt.amount) : 0),
                            0
                          )).toFixed(2)}
                        </p>
                      </div>
                      <div className="flex justify-between items-center mt-2">
                        <p className="text-sm text-gray-600 dark:text-gray-400">
                          Debited from your wallet
                        </p>
                        <p className="text-sm text-gray-600 dark:text-gray-400">
                          Session #{getTransactionId()}
                        </p>
                      </div>
                    </div>
                  </div>
                </>
              ) : (
                <div className="bg-gradient-to-r from-green-50 to-blue-50 dark:from-green-900/20 dark:to-blue-800/20 border border-green-200 dark:border-green-700 p-6 rounded-lg text-center">
                  <div className="flex flex-col items-center space-y-3">
                    <div className="w-16 h-16 bg-green-100 dark:bg-green-800/30 rounded-full flex items-center justify-center">
                      <Info className="h-8 w-8 text-green-600 dark:text-green-400" />
                    </div>
                    <div>
                      <p className="text-lg font-semibold text-green-900 dark:text-green-100">
                        No Billing Required
                      </p>
                      <p className="text-sm text-green-700 dark:text-green-300 mt-2">
                        No energy was consumed during this session.
                      </p>
                      <p className="text-xs text-green-600 dark:text-green-400 mt-1">
                        Your wallet was not charged.
                      </p>
                    </div>
                  </div>
                </div>
              )}
            </CardContent>
          </Card>
        )}

        {/* Charger Info - Collapsible for Mobile */}
        <Card className="border-0 shadow-lg bg-card">
          <CardHeader className="pb-4">
            <CardTitle className="flex items-center gap-2 text-lg text-card-foreground">
              <Info className="h-5 w-5" />
              Charger Details
            </CardTitle>
          </CardHeader>
          <CardContent className="space-y-4">
            <div className="space-y-3">
              <div className="flex justify-between items-center">
                <span className="font-medium text-card-foreground">ID:</span>
                <span className="text-sm font-mono text-muted-foreground bg-muted px-2 py-1 rounded">
                  {charger.charge_point_string_id}
                </span>
              </div>
              
              {station && (
                <div className="space-y-2">
                  <div className="flex justify-between items-start">
                    <span className="font-medium text-card-foreground">Location:</span>
                    <div className="text-right text-sm max-w-48">
                      <div className="font-medium text-card-foreground">{station.name}</div>
                      <div className="text-muted-foreground">{station.address}</div>
                    </div>
                  </div>
                </div>
              )}
              
              <div className="flex justify-between items-center">
                <span className="font-medium text-card-foreground">Updated:</span>
                <span className="text-sm text-muted-foreground">
                  {charger.last_heart_beat_time
                    ? new Date(charger.last_heart_beat_time).toLocaleTimeString([], {
                        hour: '2-digit',
                        minute: '2-digit'
                      })
                    : "Unknown"}
                </span>
              </div>
            </div>
          </CardContent>
        </Card>

        {/* Bottom Padding for Mobile Navigation */}
        <div className="h-6"></div>
      </div>
    </div>
  );
}