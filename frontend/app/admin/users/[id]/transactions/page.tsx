"use client";

import { useState } from "react";
import { AdminOnly } from "@/components/RoleWrapper";
import { Card } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import Link from "next/link";
import { useParams } from "next/navigation";
import { useUser, useUserTransactions } from "@/lib/queries/users";

function getStatusColor(status: string) {
  switch (status.toLowerCase()) {
    case 'completed':
      return 'default';
    case 'stopped':
      return 'secondary';
    case 'running':
      return 'default';
    case 'failed':
      return 'destructive';
    case 'cancelled':
      return 'destructive';
    default:
      return 'outline';
  }
}

function TransactionsTable({ userId }: { userId: number }) {
  const [currentPage, setCurrentPage] = useState(1);
  const { data: transactionsData, isLoading, error } = useUserTransactions({
    userId,
    page: currentPage,
    limit: 10
  });
  
  if (isLoading) {
    return (
      <div className="flex items-center justify-center py-8">
        <div className="text-center">
          <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-primary mx-auto"></div>
          <p className="text-muted-foreground mt-2">Loading transactions...</p>
        </div>
      </div>
    );
  }
  
  if (error) {
    return (
      <div className="text-center py-8">
        <p className="text-red-600">Failed to load transactions</p>
      </div>
    );
  }
  
  const transactions = transactionsData?.data || [];
  const totalPages = transactionsData?.total_pages || 1;
  
  if (transactions.length === 0) {
    return (
      <Card className="p-6 text-center">
        <p className="text-gray-600">No charging transactions found for this user.</p>
      </Card>
    );
  }
  
  return (
    <div className="space-y-4">
      <Card>
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Transaction ID</TableHead>
              <TableHead>Charger</TableHead>
              <TableHead>Energy</TableHead>
              <TableHead>Duration</TableHead>
              <TableHead>Status</TableHead>
              <TableHead>Start Time</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {transactions.map((transaction) => {
              const startTime = new Date(transaction.start_time);
              const endTime = transaction.end_time ? new Date(transaction.end_time) : null;
              const duration = endTime ? Math.round((endTime.getTime() - startTime.getTime()) / (1000 * 60)) : null;
              
              return (
                <TableRow key={transaction.id}>
                  <TableCell className="font-medium">#{transaction.id}</TableCell>
                  <TableCell>
                    <div>
                      <div className="font-medium">{transaction.charger_name}</div>
                      <div className="text-sm text-gray-600">{transaction.charger_id}</div>
                    </div>
                  </TableCell>
                  <TableCell>
                    {transaction.energy_consumed_kwh ? (
                      <span>{transaction.energy_consumed_kwh.toFixed(2)} kWh</span>
                    ) : (
                      <span className="text-gray-400">-</span>
                    )}
                  </TableCell>
                  <TableCell>
                    {duration ? (
                      <span>{duration} minutes</span>
                    ) : (
                      <span className="text-gray-400">Ongoing</span>
                    )}
                  </TableCell>
                  <TableCell>
                    <Badge variant={getStatusColor(transaction.status)}>
                      {transaction.status}
                    </Badge>
                  </TableCell>
                  <TableCell>
                    <div>
                      <div>{startTime.toLocaleDateString()}</div>
                      <div className="text-sm text-gray-600">{startTime.toLocaleTimeString()}</div>
                    </div>
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

export default function UserTransactionsPage() {
  const params = useParams();
  const userId = parseInt(params.id as string);
  
  const { data: user, isLoading: userLoading } = useUser(userId);
  
  return (
    <AdminOnly fallback={
      <div className="flex items-center justify-center min-h-[400px]">
        <div className="text-center">
          <h2 className="text-2xl font-bold text-gray-900 mb-2">Access Denied</h2>
          <p className="text-gray-600 mb-4">You need administrator privileges to view user transactions.</p>
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
            <h1 className="text-3xl font-bold">Charging Transactions</h1>
            {user && (
              <p className="text-gray-600 mt-1">
                Transaction history for {user.display_name} ({user.email})
              </p>
            )}
          </div>
          <Link href={`/admin/users/${userId}/wallet`}>
            <Button variant="outline">
              View Wallet Transactions
            </Button>
          </Link>
        </div>
        
        {/* Loading State */}
        {userLoading && (
          <div className="flex items-center justify-center py-4">
            <div className="animate-spin rounded-full h-6 w-6 border-b-2 border-primary"></div>
          </div>
        )}
        
        {/* Transactions Table */}
        <TransactionsTable userId={userId} />
      </div>
    </AdminOnly>
  );
}