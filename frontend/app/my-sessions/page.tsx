"use client";

import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Card, CardContent } from "@/components/ui/card";

import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { 
  Zap, 
  ArrowUpCircle, 
  ArrowDownCircle,
  Clock,
  MapPin,
  Battery,
  RefreshCw
} from "lucide-react";
import { api } from "@/lib/api-client";

interface WalletTransactionDetail {
  id: number;
  amount: number;
  type: string;
  description: string;
  created_at: string;
}

interface Transaction {
  id: number;
  type: "charging" | "wallet";
  created_at: string;
  // Charging transaction fields
  station_name?: string;
  charger_name?: string;
  energy_consumed_kwh?: number;
  start_time?: string;
  end_time?: string;
  status?: string;
  amount?: number;
  wallet_transactions?: WalletTransactionDetail[]; // Related wallet transactions for charging sessions
  // Wallet transaction fields
  transaction_type?: string;
  description?: string;
  payment_metadata?: any; // eslint-disable-line @typescript-eslint/no-explicit-any

}

interface SessionsResponse {
  data: Transaction[];
  total: number;
  page: number;
  limit: number;
  total_pages: number;
}

const getSessionService = {
  getMySessions: (page: number = 1, limit: number = 20) =>
    api.get<SessionsResponse>(`/users/my-sessions?page=${page}&limit=${limit}`)
};

export default function MySessionsPage() {
  const [page, setPage] = useState(1);
  const limit = 20;

  const { data: sessionsData, isLoading, error, refetch } = useQuery({
    queryKey: ["my-sessions", page],
    queryFn: () => getSessionService.getMySessions(page, limit),
    staleTime: 30000, // 30 seconds
  });

  const transactions = sessionsData?.data || [];
  const totalPages = sessionsData?.total_pages || 1;

  const formatDate = (dateString: string) => {
    return new Date(dateString).toLocaleString();
  };

  const formatCurrency = (amount: number) => {
    return `₹${amount.toFixed(2)}`;
  };

  const getStatusColor = (status: string) => {
    switch (status?.toLowerCase()) {
      case 'completed': return 'bg-green-100 text-green-800';
      case 'running': return 'bg-blue-100 text-blue-800';
      case 'failed': return 'bg-red-100 text-red-800';
      case 'pending': return 'bg-yellow-100 text-yellow-800';
      default: return 'bg-gray-100 text-gray-800';
    }
  };

  const getTransactionTypeColor = (type: string) => {
    switch (type?.toLowerCase()) {
      case 'topup': return 'bg-green-100 text-green-800';
      case 'charge': return 'bg-red-100 text-red-800';
      case 'charge_deduct': return 'bg-red-100 text-red-800';
      case 'refund': return 'bg-orange-100 text-orange-800';
      default: return 'bg-gray-100 text-gray-800';
    }
  };

  if (isLoading) {
    return (
      <div className="flex items-center justify-center py-8">
        <div className="text-center">
          <RefreshCw className="h-8 w-8 animate-spin mx-auto mb-2" />
          <p className="text-muted-foreground">Loading your sessions...</p>
        </div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="flex items-center justify-center py-8">
        <div className="text-center">
          <p className="text-red-600 mb-4">Failed to load sessions</p>
          <Button onClick={() => refetch()} variant="outline">
            <RefreshCw className="h-4 w-4 mr-2" />
            Retry
          </Button>
        </div>
      </div>
    );
  }

  return (
    <div className="container mx-auto py-6 space-y-6">
      <div className="flex justify-between items-center">
        <div>
          <h1 className="text-3xl font-bold">My Sessions</h1>
          <p className="text-muted-foreground">
            View your charging history and wallet transactions
          </p>
        </div>
        <Button onClick={() => refetch()} variant="outline" size="sm">
          <RefreshCw className="h-4 w-4 mr-2" />
          Refresh
        </Button>
      </div>

      {transactions.length === 0 ? (
        <Card>
          <CardContent className="py-8 text-center">
            <Battery className="h-12 w-12 mx-auto mb-4 text-muted-foreground" />
            <h3 className="text-lg font-medium mb-2">No sessions yet</h3>
            <p className="text-muted-foreground">
              Your charging sessions and wallet transactions will appear here.
            </p>
          </CardContent>
        </Card>
      ) : (
        <div className="space-y-4">
          {transactions.map((transaction) => (
            <Card key={`${transaction.type}-${transaction.id}`} className="hover:shadow-md transition-shadow">
              <CardContent className="p-6">
                {transaction.type === "charging" ? (
                  // Charging Transaction
                  <div className="flex items-start justify-between">
                    <div className="flex items-start space-x-4">
                      <div className="p-2 bg-blue-100 rounded-lg">
                        <Zap className="h-5 w-5 text-blue-600" />
                      </div>
                      <div className="flex-1">
                        <div className="flex items-center space-x-2 mb-1">
                          <h3 className="font-medium text-foreground">Charging Session</h3>
                          <Badge className={getStatusColor(transaction.status || '')}>
                            {transaction.status}
                          </Badge>
                        </div>
                        
                        <div className="space-y-1 text-sm text-muted-foreground">
                          <div className="flex items-center space-x-1">
                            <MapPin className="h-3 w-3" />
                            <span>{transaction.station_name}</span>
                          </div>
                          <div className="flex items-center space-x-1">
                            <Zap className="h-3 w-3" />
                            <span>{transaction.charger_name}</span>
                          </div>
                          {transaction.energy_consumed_kwh && (
                            <div className="flex items-center space-x-1">
                              <Battery className="h-3 w-3" />
                              <span>{transaction.energy_consumed_kwh.toFixed(2)} kWh consumed</span>
                            </div>
                          )}
                          <div className="flex items-center space-x-1">
                            <Clock className="h-3 w-3" />
                            <span>
                              {transaction.start_time && formatDate(transaction.start_time)}
                              {transaction.end_time && ` - ${formatDate(transaction.end_time)}`}
                            </span>
                          </div>
                          
                          {/* Show related wallet transactions */}
                          {transaction.wallet_transactions && transaction.wallet_transactions.length > 0 && (
                            <div className="mt-2 pt-2 border-t border-border">
                              <div className="text-xs text-muted-foreground mb-1">Payment Details:</div>
                              {transaction.wallet_transactions.map((wt) => (
                                <div key={wt.id} className="text-xs text-foreground flex justify-between">
                                  <span>{wt.description || `${wt.type} Transaction`}</span>
                                  <span className="text-red-400 font-medium">{formatCurrency(Math.abs(wt.amount))}</span>
                                </div>
                              ))}
                            </div>
                          )}
                        </div>
                      </div>
                    </div>
                    
                    <div className="text-right">
                      <div className="text-lg font-semibold text-foreground">
                        {transaction.amount ? formatCurrency(transaction.amount) : 'Free'}
                      </div>
                      <div className="text-xs text-muted-foreground">
                        {formatDate(transaction.created_at)}
                      </div>
                    </div>
                  </div>
                ) : (
                  // Wallet Transaction
                  <div className="flex items-start justify-between">
                    <div className="flex items-start space-x-4">
                      <div className={`p-2 rounded-lg ${
                        transaction.transaction_type === 'TOPUP' ? 'bg-green-100' : 'bg-red-100'
                      }`}>
                        {transaction.transaction_type === 'TOPUP' ? (
                          <ArrowUpCircle className="h-5 w-5 text-green-600" />
                        ) : (
                          <ArrowDownCircle className="h-5 w-5 text-red-600" />
                        )}
                      </div>
                      <div className="flex-1">
                        <div className="flex items-center space-x-2 mb-1">
                          <h3 className="font-medium text-foreground">
                            {transaction.transaction_type === 'TOPUP' ? 'Wallet Top-up' : 'Charging Payment'}
                          </h3>
                          <Badge className={getTransactionTypeColor(transaction.transaction_type || '')}>
                            {transaction.transaction_type === 'CHARGE_DEDUCT' ? 'CHARGE' : transaction.transaction_type}
                          </Badge>
                        </div>
                        
                        <div className="space-y-1 text-sm text-muted-foreground">
                          {transaction.description && (
                            <p>{transaction.description}</p>
                          )}
                          {transaction.payment_metadata && transaction.payment_metadata.payment_id && transaction.payment_metadata.payment_id !== 'N/A' && (
                            <div className="text-xs text-muted-foreground">
                              Payment ID: {transaction.payment_metadata.payment_id}
                            </div>
                          )}
                        </div>
                      </div>
                    </div>
                    
                    <div className="text-right">
                      <div className={`text-lg font-semibold ${
                        transaction.transaction_type === 'TOPUP' ? 'text-green-400' : 'text-red-400'
                      }`}>
                        {transaction.transaction_type === 'TOPUP' ? '+' : ''}
                        {formatCurrency(Math.abs(transaction.amount || 0))}
                      </div>
                      <div className="text-xs text-muted-foreground">
                        {formatDate(transaction.created_at)}
                      </div>
                    </div>
                  </div>
                )}
              </CardContent>
            </Card>
          ))}
        </div>
      )}

      {/* Pagination */}
      {totalPages > 1 && (
        <div className="flex justify-center space-x-2 mt-6">
          <Button
            variant="outline"
            onClick={() => setPage(page - 1)}
            disabled={page === 1}
          >
            Previous
          </Button>
          
          <div className="flex items-center space-x-1">
            {Array.from({ length: Math.min(5, totalPages) }, (_, i) => {
              const pageNum = Math.max(1, Math.min(totalPages - 4, page - 2)) + i;
              return (
                <Button
                  key={pageNum}
                  variant={pageNum === page ? "default" : "outline"}
                  size="sm"
                  onClick={() => setPage(pageNum)}
                >
                  {pageNum}
                </Button>
              );
            })}
          </div>
          
          <Button
            variant="outline"
            onClick={() => setPage(page + 1)}
            disabled={page === totalPages}
          >
            Next
          </Button>
        </div>
      )}
    </div>
  );
}