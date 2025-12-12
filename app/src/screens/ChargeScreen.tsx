import { useParams, useNavigate } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import { useApi } from '../lib/api-client';
import { chargerService, transactionService } from '../lib/api-services';
import { Battery, Zap, Clock, IndianRupee, Power, AlertCircle, Loader2, ArrowLeft, X } from 'lucide-react';
import { useState, useEffect } from 'react';
import { useUser } from '@clerk/clerk-react';

export const ChargeScreen = () => {
  const { chargerId } = useParams<{ chargerId: string }>();
  const navigate = useNavigate();
  const api = useApi();
  const { user } = useUser();
  const [isStarting, setIsStarting] = useState(false);
  const [isStopping, setIsStopping] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [lastTransactionId, setLastTransactionId] = useState<number | null>(null);

  // Fetch charger details - always poll for real-time status updates
  const { data: chargerData, isLoading: isLoadingCharger, error: chargerError, refetch: refetchCharger } = useQuery({
    queryKey: ['charger', chargerId],
    queryFn: () => chargerService(api).getById(chargerId!),
    enabled: !!chargerId,
    staleTime: 1000 * 2, // 2 seconds
    refetchInterval: (query) => {
      const data = query.state.data;
      const hasTransaction = !!data?.current_transaction?.transaction_id;
      return hasTransaction ? 2000 : 3000; // 2s if has transaction, 3s otherwise
    },
  });

  // Fetch current transaction if exists
  const currentTransactionId = chargerData?.current_transaction?.transaction_id;
  const recentTransactionId = chargerData?.recent_transaction?.transaction_id;
  const isCharging = !!currentTransactionId;

  // Show current, recent, or last transaction (in that priority order)
  const transactionIdToShow = currentTransactionId || recentTransactionId || lastTransactionId;

  // Remember last transaction ID
  useEffect(() => {
    if (currentTransactionId) {
      setLastTransactionId(currentTransactionId);
    }
  }, [currentTransactionId]);

  const { data: transactionData, refetch: refetchTransaction } = useQuery({
    queryKey: ['transaction', transactionIdToShow],
    queryFn: () => transactionService(api).getUserTransaction(transactionIdToShow!),
    enabled: !!transactionIdToShow,
    staleTime: 1000 * 2, // 2 seconds
    refetchInterval: isCharging ? 2000 : false, // Poll every 2s while charging
  });

  // Fetch meter values for live readings
  const { data: meterData } = useQuery({
    queryKey: ['meter-values', transactionIdToShow],
    queryFn: () => transactionService(api).getUserTransactionMeterValues(transactionIdToShow!),
    enabled: !!transactionIdToShow,
    staleTime: 1000 * 2, // 2 seconds
    refetchInterval: isCharging ? 2000 : false, // Poll every 2s while charging
  });

  // Clear transaction handler
  const clearTransaction = () => {
    setLastTransactionId(null);
  };

  const handleStartCharging = async () => {
    if (!chargerId || !user) return;

    setIsStarting(true);
    setError(null);
    // Clear last transaction when starting new one
    setLastTransactionId(null);

    try {
      // Use user's email as ID tag
      const idTag = user.emailAddresses[0]?.emailAddress || user.id;

      await chargerService(api).remoteStart(chargerId, 1, idTag);

      // Wait a bit and refresh to show updated status
      setTimeout(() => {
        refetchCharger();
        setIsStarting(false);
      }, 2000);
    } catch (err: any) {
      console.error('Start charging error:', err);
      setError(err.message || 'Failed to start charging. Please try again.');
      setIsStarting(false);
    }
  };

  const handleStopCharging = async () => {
    if (!chargerId) return;

    setIsStopping(true);
    setError(null);

    try {
      await chargerService(api).remoteStop(chargerId, 'User requested stop');

      // Wait a bit and refresh to show updated status
      setTimeout(() => {
        refetchCharger();
        refetchTransaction();
        setIsStopping(false);
      }, 2000);
    } catch (err: any) {
      console.error('Stop charging error:', err);
      setError(err.message || 'Failed to stop charging. Please try again.');
      setIsStopping(false);
    }
  };

  if (isLoadingCharger) {
    return (
      <div className="flex items-center justify-center h-full">
        <Loader2 className="w-8 h-8 animate-spin text-blue-600" />
      </div>
    );
  }

  if (chargerError) {
    return (
      <div className="flex items-center justify-center h-full p-4">
        <div className="bg-red-50 border border-red-200 rounded-lg p-6 max-w-md w-full">
          <div className="flex items-center space-x-3 mb-4">
            <div className="bg-red-100 p-3 rounded-full">
              <AlertCircle className="w-6 h-6 text-red-600" />
            </div>
            <h3 className="text-lg font-semibold text-red-900">Failed to load charger</h3>
          </div>
          <p className="text-sm text-red-700 mb-4">
            {(chargerError as any)?.message || 'Unable to fetch charger details. Please check your connection.'}
          </p>
          <button
            onClick={() => refetchCharger()}
            className="w-full bg-red-600 text-white py-3 rounded-lg font-semibold hover:bg-red-700 transition-colors"
          >
            Try Again
          </button>
        </div>
      </div>
    );
  }

  if (!chargerData) {
    return (
      <div className="p-4">
        <div className="bg-red-50 border border-red-200 rounded-lg p-4">
          <p className="text-red-800">Charger not found</p>
        </div>
      </div>
    );
  }

  const charger = chargerData.charger;
  const station = chargerData.station;
  // Can start charging when status is "Preparing" and charger is connected
  const canStartCharging = charger.latest_status === 'Preparing' && charger.connection_status && !currentTransactionId;
  const latestMeter = meterData?.meter_values?.[meterData.meter_values.length - 1];
  const transaction = transactionData?.transaction;

  // Helper functions to safely access transaction properties
  const getTransactionId = () => transaction?.id;
  const getTransactionStatus = () => transaction?.transaction_status || 'Unknown';
  const getEnergyConsumed = () => transaction?.energy_consumed_kwh;

  // Calculate session duration
  const sessionDuration = transaction?.start_time
    ? Math.floor((Date.now() - new Date(transaction.start_time).getTime()) / 1000)
    : 0;

  const formatDuration = (seconds: number) => {
    const hours = Math.floor(seconds / 3600);
    const minutes = Math.floor((seconds % 3600) / 60);
    const secs = seconds % 60;
    return `${hours.toString().padStart(2, '0')}:${minutes.toString().padStart(2, '0')}:${secs.toString().padStart(2, '0')}`;
  };

  return (
    <div className="min-h-full bg-gray-50">
      {/* Header */}
      <div className="bg-white shadow-sm p-4 flex items-center space-x-3">
        <button onClick={() => navigate(-1)} className="p-2 hover:bg-gray-100 rounded-lg">
          <ArrowLeft className="w-5 h-5" />
        </button>
        <div className="flex-1">
          <h1 className="text-lg font-bold text-gray-900">{charger.name}</h1>
          <p className="text-sm text-gray-600">{station.name}</p>
        </div>
      </div>

      <div className="p-4 space-y-4">
        {/* Error message */}
        {error && (
          <div className="bg-red-50 border border-red-200 rounded-lg p-4 flex items-start space-x-3">
            <AlertCircle className="w-5 h-5 text-red-600 flex-shrink-0 mt-0.5" />
            <p className="text-red-800 text-sm">{error}</p>
          </div>
        )}

        {/* Status Card */}
        <div className={`rounded-lg p-6 ${isCharging ? 'bg-green-50 border-2 border-green-500' : 'bg-white border border-gray-200'}`}>
          <div className="flex items-center justify-between mb-4">
            <div className="flex items-center space-x-2">
              <div className={`w-3 h-3 rounded-full ${charger.connection_status ? 'bg-green-500' : 'bg-red-500'} animate-pulse`}></div>
              <div>
                <span className="font-semibold text-gray-900 block">
                  {isCharging ? 'Charging' : charger.latest_status}
                </span>
                <span className={`text-sm font-medium ${charger.connection_status ? 'text-green-600' : 'text-red-600'}`}>
                  {charger.connection_status ? 'Online' : 'Offline'}
                </span>
              </div>
            </div>
            <div className={`px-3 py-1 rounded-full text-sm font-medium ${
              isCharging ? 'bg-green-100 text-green-800' : 'bg-gray-100 text-gray-800'
            }`}>
              {isCharging ? 'Active' : 'Ready'}
            </div>
          </div>

          {isCharging && sessionDuration > 0 && (
            <div className="flex items-center space-x-2 text-gray-700">
              <Clock className="w-5 h-5" />
              <span className="text-2xl font-mono font-bold">{formatDuration(sessionDuration)}</span>
            </div>
          )}
        </div>

        {/* Live Metrics - Only show when charging */}
        {isCharging && latestMeter && (
          <div className="grid grid-cols-2 gap-4">
            {/* Energy Consumed */}
            <div className="bg-white rounded-lg p-4 shadow-sm">
              <div className="flex items-center space-x-2 text-gray-600 mb-2">
                <Battery className="w-5 h-5" />
                <span className="text-sm font-medium">Energy</span>
              </div>
              <p className="text-2xl font-bold text-gray-900">
                {latestMeter.reading_kwh?.toFixed(2) || '0.00'}
              </p>
              <p className="text-xs text-gray-500 mt-1">kWh</p>
            </div>

            {/* Power */}
            <div className="bg-white rounded-lg p-4 shadow-sm">
              <div className="flex items-center space-x-2 text-gray-600 mb-2">
                <Zap className="w-5 h-5" />
                <span className="text-sm font-medium">Power</span>
              </div>
              <p className="text-2xl font-bold text-gray-900">
                {latestMeter.power_kw?.toFixed(2) || '0.00'}
              </p>
              <p className="text-xs text-gray-500 mt-1">kW</p>
            </div>

            {/* Voltage */}
            {latestMeter.voltage && (
              <div className="bg-white rounded-lg p-4 shadow-sm">
                <div className="flex items-center space-x-2 text-gray-600 mb-2">
                  <Power className="w-5 h-5" />
                  <span className="text-sm font-medium">Voltage</span>
                </div>
                <p className="text-2xl font-bold text-gray-900">
                  {latestMeter.voltage?.toFixed(0)}
                </p>
                <p className="text-xs text-gray-500 mt-1">V</p>
              </div>
            )}

            {/* Current */}
            {latestMeter.current && (
              <div className="bg-white rounded-lg p-4 shadow-sm">
                <div className="flex items-center space-x-2 text-gray-600 mb-2">
                  <Zap className="w-5 h-5" />
                  <span className="text-sm font-medium">Current</span>
                </div>
                <p className="text-2xl font-bold text-gray-900">
                  {latestMeter.current?.toFixed(2)}
                </p>
                <p className="text-xs text-gray-500 mt-1">A</p>
              </div>
            )}
          </div>
        )}

        {/* Transaction Details - Show current, recent, or last transaction */}
        {transaction && (
          <div className="bg-white rounded-lg p-4 shadow-sm">
            <div className="flex items-center justify-between mb-4">
              <h3 className="font-semibold text-gray-900">
                {currentTransactionId ? 'Active Session' : recentTransactionId ? 'Recent Session' : 'Last Session'}
              </h3>
              {!currentTransactionId && transaction && (
                <button
                  onClick={clearTransaction}
                  className="p-1 hover:bg-gray-100 rounded"
                  title="Clear transaction"
                >
                  <X className="w-4 h-4 text-gray-600" />
                </button>
              )}
            </div>

            <div className="space-y-3">
              <div className="flex justify-between items-center">
                <span className="text-sm text-gray-600">Transaction ID</span>
                <span className="font-semibold text-gray-900">{getTransactionId() || 'N/A'}</span>
              </div>
              <div className="flex justify-between items-center">
                <span className="text-sm text-gray-600">Status</span>
                <span className={`px-2 py-1 rounded text-sm font-medium ${
                  getTransactionStatus() === 'RUNNING' ? 'bg-green-100 text-green-800' : 'bg-gray-100 text-gray-800'
                }`}>
                  {getTransactionStatus()}
                </span>
              </div>
              <div className="flex justify-between items-center">
                <span className="text-sm text-gray-600">Energy Consumed</span>
                <div className="text-right">
                  <p className="font-semibold text-gray-900">
                    {currentTransactionId && latestMeter?.reading_kwh
                      ? latestMeter.reading_kwh.toFixed(2)
                      : (getEnergyConsumed() || 0).toFixed(2)} kWh
                  </p>
                  {currentTransactionId && latestMeter?.reading_kwh && (
                    <p className="text-xs text-gray-500">Live reading</p>
                  )}
                </div>
              </div>
            </div>
          </div>
        )}

        {/* Billing Info - Show during and after session */}
        {transaction && (
          <>
            {/* Estimated cost while charging */}
            {isCharging && (
              <div className="bg-blue-50 rounded-lg p-4 border border-blue-200">
                <div className="flex items-center justify-between mb-2">
                  <span className="text-sm font-medium text-blue-900">Estimated Cost</span>
                  <div className="flex items-center space-x-1 text-blue-900">
                    <IndianRupee className="w-5 h-5" />
                    <span className="text-xl font-bold">
                      {((latestMeter?.reading_kwh || 0) * (charger.tariff_per_kwh || 0)).toFixed(2)}
                    </span>
                  </div>
                </div>
                <p className="text-xs text-blue-700">
                  Wallet will be debited after session ends
                  {charger.tariff_per_kwh && ` at ₹${charger.tariff_per_kwh}/kWh`}
                </p>
              </div>
            )}

            {/* Billing summary after session ends */}
            {!isCharging && ['COMPLETED', 'STOPPED'].includes(getTransactionStatus()) && transactionData?.wallet_transactions && (
              <div className="bg-white rounded-lg p-4 shadow-sm">
                <h3 className="font-semibold text-gray-900 mb-4">Billing Summary</h3>
                {transactionData.wallet_transactions.length > 0 ? (
                  <div className="space-y-3">
                    {transactionData.wallet_transactions.map((walletTx: any) => (
                      <div key={walletTx.id} className="bg-red-50 rounded-lg p-3 border border-red-200">
                        <div className="flex justify-between items-start">
                          <div className="flex-1">
                            <p className="font-semibold text-red-900">
                              {walletTx.type === 'CHARGE_DEDUCT' ? 'Charging Bill' : walletTx.type}
                            </p>
                            {walletTx.description && (
                              <p className="text-sm text-red-700 mt-1">{walletTx.description}</p>
                            )}
                          </div>
                          <div className="text-right ml-3">
                            <div className="flex items-center text-red-600 font-bold">
                              <IndianRupee className="w-4 h-4" />
                              <span className="text-lg">{Math.abs(walletTx.amount).toFixed(2)}</span>
                            </div>
                          </div>
                        </div>
                      </div>
                    ))}
                  </div>
                ) : (
                  <div className="bg-green-50 rounded-lg p-4 border border-green-200 text-center">
                    <p className="text-green-800 font-medium">No Billing Required</p>
                    <p className="text-sm text-green-700 mt-1">No energy was consumed during this session.</p>
                  </div>
                )}
              </div>
            )}
          </>
        )}

        {/* Charger Info */}
        <div className="bg-white rounded-lg p-4 shadow-sm space-y-3">
          <h3 className="font-semibold text-gray-900">Charger Information</h3>

          <div className="space-y-2 text-sm">
            <div className="flex justify-between">
              <span className="text-gray-600">Station</span>
              <span className="font-medium text-gray-900">{station.name}</span>
            </div>
            <div className="flex justify-between">
              <span className="text-gray-600">Location</span>
              <span className="font-medium text-gray-900 text-right flex-1 ml-4">
                {station.address}
              </span>
            </div>
            {charger.model && (
              <div className="flex justify-between">
                <span className="text-gray-600">Model</span>
                <span className="font-medium text-gray-900">{charger.model}</span>
              </div>
            )}
            {chargerData.connectors && chargerData.connectors.length > 0 && (
              <div className="flex justify-between">
                <span className="text-gray-600">Connector</span>
                <span className="font-medium text-gray-900">
                  {chargerData.connectors[0].connector_type}
                  {chargerData.connectors[0].max_power_kw &&
                    ` (${chargerData.connectors[0].max_power_kw} kW)`}
                </span>
              </div>
            )}
          </div>
        </div>

        {/* Action Button */}
        <div className="pb-8">
          {isCharging ? (
            <button
              onClick={handleStopCharging}
              disabled={isStopping}
              className="w-full bg-red-600 text-white py-4 rounded-lg font-semibold text-lg hover:bg-red-700 transition-colors disabled:opacity-50 disabled:cursor-not-allowed flex items-center justify-center space-x-2"
            >
              {isStopping ? (
                <>
                  <Loader2 className="w-5 h-5 animate-spin" />
                  <span>Stopping...</span>
                </>
              ) : (
                <>
                  <Power className="w-5 h-5" />
                  <span>Stop Charging</span>
                </>
              )}
            </button>
          ) : (
            <button
              onClick={handleStartCharging}
              disabled={isStarting || !canStartCharging}
              className="w-full bg-green-600 text-white py-4 rounded-lg font-semibold text-lg hover:bg-green-700 transition-colors disabled:opacity-50 disabled:cursor-not-allowed flex items-center justify-center space-x-2"
            >
              {isStarting ? (
                <>
                  <Loader2 className="w-5 h-5 animate-spin" />
                  <span>Starting...</span>
                </>
              ) : (
                <>
                  <Zap className="w-5 h-5" />
                  <span>Start Charging</span>
                </>
              )}
            </button>
          )}

          {!canStartCharging && !isCharging && (
            <p className="text-center text-sm text-gray-600 mt-2">
              {!charger.connection_status
                ? 'Charger is offline'
                : charger.latest_status !== 'Preparing'
                ? `Charger is currently ${charger.latest_status.toLowerCase()}`
                : 'Charger is not ready'}
            </p>
          )}
        </div>
      </div>
    </div>
  );
};
