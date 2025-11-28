import { useParams, useNavigate } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import { useApi } from '../lib/api-client';
import { chargerService, transactionService } from '../lib/api-services';
import { Battery, Zap, Clock, IndianRupee, Power, AlertCircle, Loader2, ArrowLeft } from 'lucide-react';
import { useState } from 'react';
import { useUser } from '@clerk/clerk-react';

export const ChargeScreen = () => {
  const { chargerId } = useParams<{ chargerId: string }>();
  const navigate = useNavigate();
  const api = useApi();
  const { user } = useUser();
  const [isStarting, setIsStarting] = useState(false);
  const [isStopping, setIsStopping] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Fetch charger details
  const { data: chargerData, isLoading: isLoadingCharger, refetch: refetchCharger } = useQuery({
    queryKey: ['charger', chargerId],
    queryFn: () => chargerService(api).getById(Number(chargerId)),
    enabled: !!chargerId,
    refetchInterval: 5000, // Refresh every 5 seconds
  });

  // Fetch current transaction if exists
  const currentTransactionId = chargerData?.current_transaction?.transaction_id;

  const { data: transactionData, refetch: refetchTransaction } = useQuery({
    queryKey: ['transaction', currentTransactionId],
    queryFn: () => transactionService(api).getUserTransaction(currentTransactionId!),
    enabled: !!currentTransactionId,
    refetchInterval: 3000, // Refresh every 3 seconds for live data
  });

  // Fetch meter values for live readings
  const { data: meterData } = useQuery({
    queryKey: ['meter-values', currentTransactionId],
    queryFn: () => transactionService(api).getUserTransactionMeterValues(currentTransactionId!),
    enabled: !!currentTransactionId,
    refetchInterval: 3000, // Refresh every 3 seconds
  });

  const handleStartCharging = async () => {
    if (!chargerId || !user) return;

    setIsStarting(true);
    setError(null);

    try {
      // Use user's email as ID tag
      const idTag = user.emailAddresses[0]?.emailAddress || user.id;

      await chargerService(api).remoteStart(Number(chargerId), 1, idTag);

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
      await chargerService(api).remoteStop(Number(chargerId), 'User requested stop');

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
  const isCharging = !!currentTransactionId;
  const isAvailable = charger.latest_status === 'Available';
  const latestMeter = meterData?.meter_values?.[meterData.meter_values.length - 1];

  // Calculate session duration
  const sessionDuration = transactionData?.transaction.start_time
    ? Math.floor((Date.now() - new Date(transactionData.transaction.start_time).getTime()) / 1000)
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
              <div className={`w-3 h-3 rounded-full ${charger.connection_status ? 'bg-green-500' : 'bg-red-500'}`}></div>
              <span className="font-semibold text-gray-900">
                {isCharging ? 'Charging' : charger.latest_status}
              </span>
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

        {/* Billing Info - Only show when charging */}
        {isCharging && transactionData && (
          <div className="bg-blue-50 rounded-lg p-4 border border-blue-200">
            <div className="flex items-center justify-between mb-2">
              <span className="text-sm font-medium text-blue-900">Estimated Cost</span>
              <div className="flex items-center space-x-1 text-blue-900">
                <IndianRupee className="w-5 h-5" />
                <span className="text-xl font-bold">
                  {((latestMeter?.reading_kwh || 0) * (station.address ? 10 : 8)).toFixed(2)}
                </span>
              </div>
            </div>
            <p className="text-xs text-blue-700">
              Wallet will be debited after session ends
            </p>
          </div>
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
              disabled={isStarting || !isAvailable}
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

          {!isAvailable && !isCharging && (
            <p className="text-center text-sm text-gray-600 mt-2">
              Charger is currently {charger.latest_status.toLowerCase()}
            </p>
          )}
        </div>
      </div>
    </div>
  );
};
