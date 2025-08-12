"use client";

import { useState } from "react";
import { AdminOnly } from "@/components/RoleWrapper";
import { Card } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import Link from "next/link";
import { useParams } from "next/navigation";
import { useUser, useUserWalletTransactions } from "@/lib/queries/users";

function getTransactionTypeColor(type: string) {
  switch (type.toUpperCase()) {
    case 'TOP_UP':
      return 'default';
    case 'CHARGE_DEDUCT':
      return 'destructive';
    default:
      return 'secondary';
  }
}

function WalletTransactionsTable({ userId }: { userId: number }) {
  const [currentPage, setCurrentPage] = useState(1);
  const { data: transactionsData, isLoading, error } = useUserWalletTransactions({
    userId,
    page: currentPage,
    limit: 15
  });
  
  if (isLoading) {
    return (
      <div className="flex items-center justify-center py-8">
        <div className="text-center">
          <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-primary mx-auto"></div>
          <p className="text-muted-foreground mt-2">Loading wallet transactions...</p>
        </div>
      </div>
    );
  }
  
  if (error) {
    return (
      <div className="text-center py-8">
        <p className="text-red-600">Failed to load wallet transactions</p>
      </div>
    );
  }
  
  const transactions = transactionsData?.data || [];
  const totalPages = transactionsData?.total_pages || 1;
  
  if (transactions.length === 0) {
    return (
      <Card className="p-6 text-center">
        <p className="text-gray-600">No wallet transactions found for this user.</p>
      </Card>
    );
  }
  
  // Calculate running balance
  let runningBalance = 0;
  const transactionsWithBalance = transactions.map(transaction => {
    runningBalance += transaction.amount;
    return {
      ...transaction,
      running_balance: runningBalance
    };
  });
  
  return (
    <div className="space-y-4">
      <Card>
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Date & Time</TableHead>
              <TableHead>Type</TableHead>
              <TableHead>Amount</TableHead>
              <TableHead>Description</TableHead>
              <TableHead>Payment Details</TableHead>
              <TableHead className="text-right">Balance Change</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {transactionsWithBalance.map((transaction) => {
              const transactionDate = new Date(transaction.created_at);
              const isCredit = transaction.amount > 0;
              
              return (
                <TableRow key={transaction.id}>
                  <TableCell>
                    <div>
                      <div className="font-medium">{transactionDate.toLocaleDateString()}</div>
                      <div className="text-sm text-gray-600">{transactionDate.toLocaleTimeString()}</div>
                    </div>
                  </TableCell>
                  <TableCell>
                    <Badge variant={getTransactionTypeColor(transaction.type)}>
                      {transaction.type.replace('_', ' ')}
                    </Badge>
                  </TableCell>
                  <TableCell>
                    <span className={`font-medium ${isCredit ? 'text-green-600' : 'text-red-600'}`}>
                      {isCredit ? '+' : ''}₹{Math.abs(transaction.amount).toFixed(2)}
                    </span>
                  </TableCell>
                  <TableCell>
                    <div className="max-w-xs">
                      {transaction.description || 'No description'}
                    </div>
                  </TableCell>
                  <TableCell>
                    {transaction.payment_metadata ? (
                      <div className="text-sm">
                        {transaction.payment_metadata.gateway && (
                          <div>Gateway: {transaction.payment_metadata.gateway}</div>
                        )}
                        {transaction.payment_metadata.payment_method && (
                          <div>Method: {transaction.payment_metadata.payment_method}</div>
                        )}
                        {transaction.payment_metadata.transaction_id && (
                          <div className="text-gray-600 text-xs">
                            ID: {transaction.payment_metadata.transaction_id}
                          </div>
                        )}
                      </div>
                    ) : (
                      <span className="text-gray-400">-</span>
                    )}
                  </TableCell>
                  <TableCell className="text-right">
                    <span className={`font-medium ${isCredit ? 'text-green-600' : 'text-red-600'}`}>
                      {isCredit ? '+' : '-'}₹{Math.abs(transaction.amount).toFixed(2)}
                    </span>
                  </TableCell>
                </TableRow>
              );
            })}
          </TableBody>
        </Table>
      </Card>
      
      {/* Pagination */}
      {totalPages > 1 && (
        <div className="flex items-center justify-between">
          <div className="text-sm text-gray-600">
            Showing {transactions.length} of {transactionsData?.total || 0} transactions
          </div>
          <div className="flex items-center gap-2">
            <Button
              variant="outline"
              size="sm"
              onClick={() => setCurrentPage(prev => Math.max(prev - 1, 1))}
              disabled={currentPage === 1}
            >
              Previous
            </Button>
            <span className="text-sm px-3 py-1 bg-gray-100 rounded">
              {currentPage} of {totalPages}
            </span>
            <Button
              variant="outline"
              size="sm"
              onClick={() => setCurrentPage(prev => Math.min(prev + 1, totalPages))}
              disabled={currentPage === totalPages}
            >
              Next
            </Button>
          </div>
        </div>
      )}
    </div>
  );
}

export default function UserWalletPage() {
  const params = useParams();
  const userId = parseInt(params.id as string);
  
  const { data: user, isLoading: userLoading } = useUser(userId);
  
  return (
    <AdminOnly fallback={
      <div className="flex items-center justify-center min-h-[400px]">
        <div className="text-center">
          <h2 className="text-2xl font-bold text-gray-900 mb-2">Access Denied</h2>
          <p className="text-gray-600 mb-4">You need administrator privileges to view user wallet details.</p>
          <Link href="/admin" className="text-blue-600 hover:text-blue-800">
            Go to Admin Dashboard →
          </Link>
        </div>
      </div>
    }>
      <div className="space-y-6">
        {/* Header */}
        <div className="flex items-center justify-between">
          <div>
            <Link 
              href={`/admin/users/${userId}`} 
              className="text-blue-600 hover:text-blue-800 text-sm mb-2 inline-block"
            >
              ← Back to User Details
            </Link>
            <h1 className="text-3xl font-bold">Wallet Transactions</h1>
            {user && (
              <div className="mt-2">
                <p className="text-gray-600">
                  Wallet history for {user.display_name} ({user.email})
                </p>
                <div className="flex items-center gap-4 mt-2">
                  <div className="text-lg font-semibold text-green-600">
                    Current Balance: ₹{user.wallet_balance?.toFixed(2) || '0.00'}
                  </div>
                  <Badge variant="outline">
                    {user.total_wallet_transactions} total transactions
                  </Badge>
                </div>
              </div>
            )}
          </div>
          <Link href={`/admin/users/${userId}/transactions`}>
            <Button variant="outline">
              View Charging Transactions
            </Button>
          </Link>
        </div>
        
        {/* Loading State */}
        {userLoading && (
          <div className="flex items-center justify-center py-4">
            <div className="animate-spin rounded-full h-6 w-6 border-b-2 border-primary"></div>
          </div>
        )}
        
        {/* Summary Cards */}
        {user && (
          <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
            <Card className="p-4">
              <h3 className="font-semibold text-green-600">Total Top-ups</h3>
              <p className="text-2xl font-bold">
                ₹{/* Calculate from transactions - would need separate API call for this summary */}
                --.--
              </p>
              <p className="text-sm text-gray-600">All time deposits</p>
            </Card>
            <Card className="p-4">
              <h3 className="font-semibold text-red-600">Total Spent</h3>
              <p className="text-2xl font-bold">
                ₹{/* Calculate from transactions */}
                --.--
              </p>
              <p className="text-sm text-gray-600">On charging sessions</p>
            </Card>
            <Card className="p-4">
              <h3 className="font-semibold text-blue-600">Current Balance</h3>
              <p className="text-2xl font-bold">
                ₹{user.wallet_balance?.toFixed(2) || '0.00'}
              </p>
              <p className="text-sm text-gray-600">Available funds</p>
            </Card>
          </div>
        )}
        
        {/* Wallet Transactions Table */}
        <WalletTransactionsTable userId={userId} />
      </div>
    </AdminOnly>
  );
}