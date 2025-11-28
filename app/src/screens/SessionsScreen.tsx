import { useQuery } from '@tanstack/react-query';
import { useApi } from '../lib/api-client';
import { userSessionService, walletPaymentService } from '../lib/api-services';
import { Wallet, Zap, IndianRupee, Clock, MapPin, TrendingUp, TrendingDown, Loader2, Plus } from 'lucide-react';
import { format } from 'date-fns';
import { useState } from 'react';

export const SessionsScreen = () => {
  const api = useApi();
  const [showRechargeModal, setShowRechargeModal] = useState(false);
  const [rechargeAmount, setRechargeAmount] = useState('');
  const [isProcessing, setIsProcessing] = useState(false);

  // Fetch user sessions and wallet balance
  const { data: sessionsData, isLoading, refetch } = useQuery({
    queryKey: ['my-sessions'],
    queryFn: () => userSessionService(api).getMySessions(),
    refetchInterval: 10000, // Refresh every 10 seconds
  });

  const handleRecharge = async () => {
    if (!rechargeAmount || isNaN(Number(rechargeAmount))) {
      alert('Please enter a valid amount');
      return;
    }

    const amount = Number(rechargeAmount);
    if (amount < 1 || amount > 100000) {
      alert('Amount must be between ₹1 and ₹100,000');
      return;
    }

    setIsProcessing(true);

    try {
      // Create Razorpay order
      const orderData = await walletPaymentService(api).createRechargeOrder(amount);

      // TODO: Implement Razorpay integration here
      // For now, just show success message
      alert(`Razorpay integration pending. Order created: ${orderData.order_id}`);

      setShowRechargeModal(false);
      setRechargeAmount('');
      refetch();
    } catch (err: any) {
      console.error('Recharge error:', err);
      alert('Failed to create recharge order. Please try again.');
    } finally {
      setIsProcessing(false);
    }
  };

  const quickAmounts = [100, 200, 500, 1000];

  if (isLoading) {
    return (
      <div className="flex items-center justify-center h-full">
        <Loader2 className="w-8 h-8 animate-spin text-blue-600" />
      </div>
    );
  }

  const walletBalance = sessionsData?.wallet_balance || 0;
  const chargingSessions = sessionsData?.charging_sessions || [];
  const walletTransactions = sessionsData?.wallet_transactions || [];

  // Combine and sort all transactions by date
  const allTransactions = [
    ...chargingSessions.map((session) => ({
      ...session,
      type: 'charging' as const,
      created_at: session.end_time || session.start_time,
    })),
    ...walletTransactions.map((tx) => ({
      ...tx,
      type: 'wallet' as const,
    })),
  ].sort((a, b) => new Date(b.created_at).getTime() - new Date(a.created_at).getTime());

  return (
    <div className="p-4 space-y-6">
      <div>
        <h2 className="text-2xl font-bold text-gray-900">My Sessions</h2>
        <p className="text-gray-600 mt-1">View your charging history and wallet</p>
      </div>

      {/* Wallet Balance Card */}
      <div className="bg-gradient-to-r from-blue-600 to-blue-700 rounded-lg p-6 text-white shadow-lg">
        <div className="flex items-center justify-between mb-4">
          <div className="flex items-center space-x-2">
            <Wallet className="w-6 h-6" />
            <span className="text-sm font-medium opacity-90">Wallet Balance</span>
          </div>
        </div>

        <div className="flex items-baseline space-x-2 mb-4">
          <IndianRupee className="w-8 h-8" />
          <span className="text-4xl font-bold">{walletBalance.toFixed(2)}</span>
        </div>

        <button
          onClick={() => setShowRechargeModal(true)}
          className="w-full bg-white text-blue-600 py-3 rounded-lg font-semibold hover:bg-blue-50 transition-colors flex items-center justify-center space-x-2"
        >
          <Plus className="w-5 h-5" />
          <span>Recharge Wallet</span>
        </button>
      </div>

      {/* Transaction History */}
      <div>
        <h3 className="text-lg font-semibold text-gray-900 mb-4">Recent Activity</h3>

        {allTransactions.length === 0 ? (
          <div className="bg-white rounded-lg p-8 text-center">
            <p className="text-gray-600">No transactions yet</p>
            <p className="text-sm text-gray-500 mt-1">Start charging to see your history</p>
          </div>
        ) : (
          <div className="space-y-3">
            {allTransactions.map((transaction, index) => (
              <div key={`${transaction.type}-${index}`} className="bg-white rounded-lg p-4 shadow-sm">
                {transaction.type === 'charging' ? (
                  // Charging Session
                  <div className="flex items-start space-x-3">
                    <div className="bg-green-100 p-2 rounded-lg flex-shrink-0">
                      <Zap className="w-5 h-5 text-green-600" />
                    </div>

                    <div className="flex-1 min-w-0">
                      <div className="flex items-center justify-between mb-1">
                        <h4 className="font-semibold text-gray-900 truncate">
                          {transaction.charger_name}
                        </h4>
                        <div className={`px-2 py-1 rounded text-xs font-medium ${
                          transaction.status === 'completed'
                            ? 'bg-green-100 text-green-800'
                            : transaction.status === 'active'
                            ? 'bg-blue-100 text-blue-800'
                            : 'bg-gray-100 text-gray-800'
                        }`}>
                          {transaction.status}
                        </div>
                      </div>

                      <div className="flex items-center space-x-4 text-sm text-gray-600 mb-2">
                        <div className="flex items-center space-x-1">
                          <MapPin className="w-4 h-4" />
                          <span>{transaction.station_name}</span>
                        </div>
                      </div>

                      <div className="flex items-center justify-between text-sm">
                        <div className="flex items-center space-x-1 text-gray-600">
                          <Clock className="w-4 h-4" />
                          <span>{format(new Date(transaction.start_time), 'MMM d, h:mm a')}</span>
                        </div>

                        <div className="flex items-center space-x-4">
                          {transaction.energy_kwh !== undefined && (
                            <span className="text-gray-700 font-medium">
                              {transaction.energy_kwh.toFixed(2)} kWh
                            </span>
                          )}
                          <div className="flex items-center text-red-600 font-semibold">
                            <IndianRupee className="w-4 h-4" />
                            <span>{transaction.cost?.toFixed(2) || '0.00'}</span>
                          </div>
                        </div>
                      </div>
                    </div>
                  </div>
                ) : (
                  // Wallet Transaction
                  <div className="flex items-start space-x-3">
                    <div className={`p-2 rounded-lg flex-shrink-0 ${
                      transaction.amount > 0
                        ? 'bg-green-100'
                        : 'bg-red-100'
                    }`}>
                      {transaction.amount > 0 ? (
                        <TrendingUp className={`w-5 h-5 text-green-600`} />
                      ) : (
                        <TrendingDown className={`w-5 h-5 text-red-600`} />
                      )}
                    </div>

                    <div className="flex-1 min-w-0">
                      <div className="flex items-center justify-between mb-1">
                        <h4 className="font-semibold text-gray-900">
                          {transaction.description || 'Wallet Transaction'}
                        </h4>
                      </div>

                      <div className="flex items-center justify-between text-sm">
                        <div className="flex items-center space-x-1 text-gray-600">
                          <Clock className="w-4 h-4" />
                          <span>{format(new Date(transaction.created_at), 'MMM d, h:mm a')}</span>
                        </div>

                        <div className={`flex items-center font-semibold ${
                          transaction.amount > 0
                            ? 'text-green-600'
                            : 'text-red-600'
                        }`}>
                          {transaction.amount > 0 ? '+' : '-'}
                          <IndianRupee className="w-4 h-4" />
                          <span>{Math.abs(transaction.amount).toFixed(2)}</span>
                        </div>
                      </div>
                    </div>
                  </div>
                )}
              </div>
            ))}
          </div>
        )}
      </div>

      {/* Recharge Modal */}
      {showRechargeModal && (
        <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center p-4 z-50">
          <div className="bg-white rounded-lg max-w-md w-full p-6 space-y-4">
            <div className="flex items-center justify-between">
              <h3 className="text-xl font-bold text-gray-900">Recharge Wallet</h3>
              <button
                onClick={() => setShowRechargeModal(false)}
                className="text-gray-500 hover:text-gray-700"
              >
                ✕
              </button>
            </div>

            {/* Quick amount buttons */}
            <div className="grid grid-cols-4 gap-2">
              {quickAmounts.map((amount) => (
                <button
                  key={amount}
                  onClick={() => setRechargeAmount(amount.toString())}
                  className="py-2 px-3 border-2 border-gray-300 rounded-lg hover:border-blue-500 hover:bg-blue-50 transition-colors text-sm font-medium"
                >
                  ₹{amount}
                </button>
              ))}
            </div>

            {/* Custom amount input */}
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-2">
                Enter Amount
              </label>
              <div className="relative">
                <div className="absolute inset-y-0 left-0 pl-3 flex items-center pointer-events-none">
                  <IndianRupee className="w-5 h-5 text-gray-400" />
                </div>
                <input
                  type="number"
                  placeholder="Enter amount"
                  value={rechargeAmount}
                  onChange={(e) => setRechargeAmount(e.target.value)}
                  className="w-full pl-10 pr-4 py-3 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-transparent"
                  min="1"
                  max="100000"
                />
              </div>
              <p className="text-xs text-gray-500 mt-1">Min: ₹1 | Max: ₹100,000</p>
            </div>

            {/* Action buttons */}
            <div className="flex space-x-3">
              <button
                onClick={() => setShowRechargeModal(false)}
                className="flex-1 py-3 border border-gray-300 rounded-lg font-semibold hover:bg-gray-50 transition-colors"
              >
                Cancel
              </button>
              <button
                onClick={handleRecharge}
                disabled={isProcessing || !rechargeAmount}
                className="flex-1 py-3 bg-blue-600 text-white rounded-lg font-semibold hover:bg-blue-700 transition-colors disabled:opacity-50 disabled:cursor-not-allowed flex items-center justify-center space-x-2"
              >
                {isProcessing ? (
                  <>
                    <Loader2 className="w-5 h-5 animate-spin" />
                    <span>Processing...</span>
                  </>
                ) : (
                  <span>Proceed to Pay</span>
                )}
              </button>
            </div>

            <p className="text-xs text-gray-500 text-center">
              Powered by Razorpay • Secure payment gateway
            </p>
          </div>
        </div>
      )}
    </div>
  );
};
