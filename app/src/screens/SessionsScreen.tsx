import { useQuery } from '@tanstack/react-query';
import { useApi } from '../lib/api-client';
import { userSessionService, walletPaymentService } from '../lib/api-services';
import { Wallet, Zap, IndianRupee, Clock, MapPin, TrendingUp, TrendingDown, Loader2, Plus, X } from 'lucide-react';
import { format } from 'date-fns';
import { useState, useMemo } from 'react';
import { Capacitor } from '@capacitor/core';
import { PullToRefresh } from '../components/PullToRefresh';
import { SessionsSkeleton } from '../components/SessionsSkeleton';

export const SessionsScreen = () => {
  const api = useApi();
  const [showRechargeSection, setShowRechargeSection] = useState(false);
  const [rechargeAmount, setRechargeAmount] = useState('');
  const [isProcessing, setIsProcessing] = useState(false);

  // Fetch user sessions
  const { data: sessionsData, isLoading, error, refetch } = useQuery({
    queryKey: ['my-sessions'],
    queryFn: () => userSessionService(api).getMySessions(1, 100),
    staleTime: 30 * 1000, // 30 seconds - data stays fresh
    gcTime: 10 * 60 * 1000, // 10 minutes - keep in cache
    refetchOnMount: false, // Don't refetch on mount if data is fresh
    placeholderData: (previousData) => previousData, // Keep showing old data while refetching
    // Only poll if user has active charging sessions
    refetchInterval: (query) => {
      const data = query.state.data;
      const hasActiveSessions = data?.data?.some(
        (transaction: any) => transaction.type === 'charging' && transaction.status === 'active'
      );
      return hasActiveSessions ? 10000 : false; // 10s if active, else don't poll
    },
  });

  // Fetch wallet balance separately
  const { data: walletData, isLoading: isLoadingWallet, refetch: refetchWallet } = useQuery({
    queryKey: ['my-wallet'],
    queryFn: () => userSessionService(api).getMyWallet(),
    staleTime: 30 * 1000, // 30 seconds
    gcTime: 10 * 60 * 1000, // 10 minutes
    refetchOnMount: false,
    placeholderData: (previousData) => previousData,
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
      // Create Razorpay order on backend
      const orderData = await walletPaymentService(api).createRechargeOrder(amount);

      const razorpayKeyId = import.meta.env.VITE_RAZORPAY_KEY_ID;

      if (!razorpayKeyId) {
        throw new Error('Razorpay key not configured. Please add VITE_RAZORPAY_KEY_ID to .env');
      }

      // Check if running on native platform
      const isNative = Capacitor.isNativePlatform();

      if (isNative) {
        // Use Capacitor Razorpay plugin for native apps
        try {
          const { Checkout } = await import('capacitor-razorpay');

          const options = {
            key: razorpayKeyId,
            amount: (orderData.amount * 100).toString(), // Convert rupees to paise for Razorpay
            currency: orderData.currency,
            order_id: orderData.order_id,
            name: 'LyncPower',
            description: 'Wallet Recharge',
            theme: {
              color: '#2563eb', // Blue color
            },
          };

          const result: any = await Checkout.open(options as any);
          console.log('Capacitor Razorpay result:', result, 'Type:', typeof result);

          // Parse payment data - handle both string and object formats
          let paymentData: any;
          if (typeof result === 'string') {
            paymentData = JSON.parse(result);
          } else if (typeof result === 'object' && result !== null) {
            paymentData = result;
          } else {
            throw new Error('Invalid payment result format');
          }

          console.log('Parsed payment data:', paymentData);
          console.log('Payment data keys:', Object.keys(paymentData));
          console.log('Payment data stringified:', JSON.stringify(paymentData));

          // capacitor-razorpay wraps the response in a "response" property
          const responseData = paymentData.response || paymentData;

          // Check for payment details in different possible formats
          const paymentId = responseData.razorpay_payment_id || responseData.paymentId || responseData.payment_id;
          const orderId = responseData.razorpay_order_id || responseData.orderId || responseData.order_id;
          const signature = responseData.razorpay_signature || responseData.signature;

          console.log('Extracted values:', { paymentId, orderId, signature });

          if (!paymentId || !orderId || !signature) {
            console.error('Missing payment details. Full data:', paymentData);
            throw new Error('Missing payment details in response');
          }

          // Verify payment on backend
          const verifyResponse = await walletPaymentService(api).verifyPayment({
            razorpay_order_id: orderId,
            razorpay_payment_id: paymentId,
            razorpay_signature: signature,
          });

          // Refetch wallet and sessions data
          await refetchWallet();
          await refetch();

          alert(`Payment successful! ₹${amount} added to wallet. New balance: ₹${verifyResponse.wallet_balance}`);
          setRechargeAmount('');
          setShowRechargeSection(false);
        } catch (paymentError: any) {
          console.error('Payment error:', paymentError);

          if (paymentError.code === 0) {
            // User cancelled payment
            alert('Payment cancelled');
          } else if (paymentError.message?.includes('Missing payment details')) {
            alert('Payment completed but verification pending. Please check your transaction history.');
          } else {
            alert('Payment failed. Please try again or check your transaction history.');
          }
        }
      } else {
        // Web platform - use Razorpay web checkout
        if (typeof window === 'undefined' || !(window as any).Razorpay) {
          // Load Razorpay script dynamically
          const script = document.createElement('script');
          script.src = 'https://checkout.razorpay.com/v1/checkout.js';
          script.async = true;
          document.body.appendChild(script);

          await new Promise((resolve, reject) => {
            script.onload = resolve;
            script.onerror = reject;
          });
        }

        const options = {
          key: razorpayKeyId,
          amount: orderData.amount * 100, // Convert rupees to paise for Razorpay (backend returns rupees)
          currency: orderData.currency,
          order_id: orderData.order_id,
          name: 'LyncPower',
          description: 'Wallet Recharge',
          theme: {
            color: '#2563eb',
          },
          handler: async (response: any) => {
            try {
              // Verify payment on backend
              const verifyResponse = await walletPaymentService(api).verifyPayment({
                razorpay_order_id: response.razorpay_order_id,
                razorpay_payment_id: response.razorpay_payment_id,
                razorpay_signature: response.razorpay_signature,
              });

              // Refetch wallet and sessions data
              await refetchWallet();
              await refetch();

              alert(`Payment successful! ₹${amount} added to wallet. New balance: ₹${verifyResponse.wallet_balance}`);
              setRechargeAmount('');
              setShowRechargeSection(false);
            } catch (verifyError) {
              console.error('Payment verification failed:', verifyError);
              alert('Payment verification failed. Please contact support.');
            }
          },
          modal: {
            ondismiss: () => {
              alert('Payment cancelled');
            },
          },
        };

        const razorpay = new (window as any).Razorpay(options);
        razorpay.open();
      }
    } catch (err: any) {
      console.error('Recharge error:', err);
      alert(err.message || 'Failed to initiate payment. Please try again.');
    } finally {
      setIsProcessing(false);
    }
  };

  const quickAmounts = [100, 200, 500, 1000];

  // Extract data - must be called before early returns to avoid hooks order violation
  const walletBalance = walletData?.wallet_balance ?? 0;
  const allTransactions = sessionsData?.data || [];

  // Transactions are already sorted by backend, but ensure client-side sorting as fallback
  const sortedTransactions = useMemo(() => {
    return [...allTransactions].sort((a, b) =>
      new Date(b.created_at).getTime() - new Date(a.created_at).getTime()
    );
  }, [allTransactions]);

  // Early returns AFTER all hooks have been called
  // Show skeleton on initial load, not on refetch
  if (isLoading && !sessionsData) {
    return <SessionsSkeleton />;
  }

  if (error) {
    return (
      <div className="flex items-center justify-center h-full p-4">
        <div className="bg-red-50 border border-red-200 rounded-lg p-6 max-w-md w-full">
          <div className="flex items-center space-x-3 mb-4">
            <div className="bg-red-100 p-3 rounded-full">
              <Loader2 className="w-6 h-6 text-red-600" />
            </div>
            <h3 className="text-lg font-semibold text-red-900">Failed to load sessions</h3>
          </div>
          <p className="text-sm text-red-700 mb-4">
            {(error as any)?.message || 'Unable to fetch your sessions. Please check your connection.'}
          </p>
          <button
            onClick={() => refetch()}
            className="w-full bg-red-600 text-white py-3 rounded-lg font-semibold hover:bg-red-700 transition-colors"
          >
            Try Again
          </button>
        </div>
      </div>
    );
  }

  return (
    <PullToRefresh onRefresh={async () => {
      await Promise.all([refetch(), refetchWallet()]);
    }}>
      <div className="p-4 space-y-6">
        <div>
          <h2 className="text-2xl font-bold text-gray-900">My Sessions</h2>
          <p className="text-gray-600 mt-1">View your charging history and wallet</p>
        </div>

      {/* Wallet Balance & Recharge Card */}
      <div className="bg-gradient-to-r from-blue-600 to-blue-700 rounded-lg p-6 text-white shadow-lg">
        <div className="flex items-center justify-between mb-4">
          <div className="flex items-center space-x-2">
            <Wallet className="w-6 h-6" />
            <span className="text-sm font-medium opacity-90">Wallet Balance</span>
          </div>
          {showRechargeSection && (
            <button
              onClick={() => {
                setShowRechargeSection(false);
                setRechargeAmount('');
              }}
              className="p-1 hover:bg-white/20 rounded-full transition-colors"
            >
              <X className="w-5 h-5" />
            </button>
          )}
        </div>

        <div className="flex items-baseline space-x-2 mb-4">
          <IndianRupee className="w-8 h-8" />
          <span className="text-4xl font-bold">
            {isLoadingWallet ? '...' : walletBalance.toFixed(2)}
          </span>
        </div>

        {!showRechargeSection ? (
          <button
            onClick={() => setShowRechargeSection(true)}
            className="w-full bg-white text-blue-600 py-3 rounded-lg font-semibold hover:bg-blue-50 transition-colors flex items-center justify-center space-x-2"
          >
            <Plus className="w-5 h-5" />
            <span>Recharge Wallet</span>
          </button>
        ) : (
          <div className="space-y-4">
            {/* Quick amount buttons */}
            <div className="grid grid-cols-4 gap-2">
              {quickAmounts.map((amount) => (
                <button
                  key={amount}
                  onClick={() => setRechargeAmount(amount.toString())}
                  className={`py-2 px-3 border-2 rounded-lg transition-colors text-sm font-medium ${
                    rechargeAmount === amount.toString()
                      ? 'border-white bg-white text-blue-600'
                      : 'border-white/30 hover:border-white hover:bg-white/10'
                  }`}
                >
                  ₹{amount}
                </button>
              ))}
            </div>

            {/* Custom amount input */}
            <div>
              <label className="block text-sm font-medium mb-2 opacity-90">
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
                  className="w-full pl-10 pr-4 py-3 border-2 border-white/30 bg-white/10 rounded-lg focus:ring-2 focus:ring-white focus:border-white text-white placeholder-white/50 transition-colors"
                  min="1"
                  max="100000"
                />
              </div>
              <p className="text-xs opacity-75 mt-1">Min: ₹1 | Max: ₹100,000</p>
            </div>

            {/* Action button */}
            <button
              onClick={handleRecharge}
              disabled={isProcessing || !rechargeAmount}
              className="w-full py-3 bg-white text-blue-600 rounded-lg font-semibold hover:bg-blue-50 transition-colors disabled:opacity-50 disabled:cursor-not-allowed flex items-center justify-center space-x-2"
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

            <p className="text-xs text-center opacity-75">
              Powered by Razorpay • Secure payment gateway
            </p>
          </div>
        )}
      </div>

      {/* Transaction History */}
      <div>
        <h3 className="text-lg font-semibold text-gray-900 mb-4">Recent Activity</h3>

        {sortedTransactions.length === 0 ? (
          <div className="bg-white rounded-lg p-8 text-center">
            <p className="text-gray-600">No transactions yet</p>
            <p className="text-sm text-gray-500 mt-1">Start charging to see your history</p>
          </div>
        ) : (
          <div className="space-y-3">
            {sortedTransactions.map((transaction, index) => (
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
                          transaction.status === 'COMPLETED'
                            ? 'bg-green-100 text-green-800'
                            : transaction.status === 'RUNNING'
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
                          <span>{transaction.start_time && format(new Date(transaction.start_time), 'MMM d, h:mm a')}</span>
                        </div>

                        <div className="flex items-center space-x-4">
                          {transaction.energy_consumed_kwh !== undefined && transaction.energy_consumed_kwh !== null && (
                            <span className="text-gray-700 font-medium">
                              {transaction.energy_consumed_kwh.toFixed(2)} kWh
                            </span>
                          )}
                          <div className="flex items-center text-red-600 font-semibold">
                            <IndianRupee className="w-4 h-4" />
                            <span>{transaction.amount?.toFixed(2) || '0.00'}</span>
                          </div>
                        </div>
                      </div>
                    </div>
                  </div>
                ) : (
                  // Wallet Transaction
                  <div className="flex items-start space-x-3">
                    <div className={`p-2 rounded-lg flex-shrink-0 ${
                      transaction.payment_metadata?.status === 'PENDING'
                        ? 'bg-yellow-100'
                        : transaction.transaction_type === 'TOP_UP'
                        ? 'bg-green-100'
                        : 'bg-red-100'
                    }`}>
                      {transaction.payment_metadata?.status === 'PENDING' ? (
                        <Loader2 className="w-5 h-5 text-yellow-600 animate-spin" />
                      ) : transaction.transaction_type === 'TOP_UP' ? (
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
                        <div className="flex items-center space-x-2">
                          {transaction.payment_metadata?.status === 'PENDING' && (
                            <div className="px-2 py-1 rounded text-xs font-medium bg-yellow-100 text-yellow-800">
                              PENDING
                            </div>
                          )}
                          <div className={`px-2 py-1 rounded text-xs font-medium ${
                            transaction.payment_metadata?.status === 'COMPLETED'
                              ? 'bg-green-100 text-green-800'
                              : transaction.transaction_type === 'TOP_UP'
                              ? 'bg-green-100 text-green-800'
                              : 'bg-red-100 text-red-800'
                          }`}>
                            {transaction.transaction_type}
                          </div>
                        </div>
                      </div>

                      <div className="flex items-center justify-between text-sm">
                        <div className="flex items-center space-x-1 text-gray-600">
                          <Clock className="w-4 h-4" />
                          <span>{format(new Date(transaction.created_at), 'MMM d, h:mm a')}</span>
                        </div>

                        <div className={`flex items-center font-semibold ${
                          transaction.transaction_type === 'TOP_UP'
                            ? 'text-green-600'
                            : 'text-red-600'
                        }`}>
                          {transaction.transaction_type === 'TOP_UP' ? '+' : '-'}
                          <IndianRupee className="w-4 h-4" />
                          <span>{transaction.amount ? Math.abs(transaction.amount).toFixed(2) : '0.00'}</span>
                        </div>
                      </div>

                      {/* Show note for pending transactions */}
                      {transaction.payment_metadata?.status === 'PENDING' && (
                        <div className="mt-2 text-xs text-yellow-700 bg-yellow-50 px-2 py-1 rounded">
                          Payment verification in progress. Your wallet will be updated shortly.
                        </div>
                      )}
                    </div>
                  </div>
                )}
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
    </PullToRefresh>
  );
};
