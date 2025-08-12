"use client";

import { AdminOnly } from "@/components/RoleWrapper";
import { Card } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import Link from "next/link";
import { useParams } from "next/navigation";
import { useUser, useUserTransactionSummary } from "@/lib/queries/users";
import { UserDetail } from "@/types/api";

function UserProfileCard({ user }: { user: UserDetail }) {
  return (
    <Card className="p-6">
      <div className="flex items-start justify-between mb-4">
        <div>
          <h2 className="text-2xl font-bold">{user.display_name}</h2>
          <p className="text-gray-600">{user.email}</p>
        </div>
        <div className="flex items-center gap-2">
          {user.is_active ? (
            <Badge variant="default">Active</Badge>
          ) : (
            <Badge variant="destructive">Deactivated</Badge>
          )}
          {!user.is_email_verified && (
            <Badge variant="secondary">Unverified Email</Badge>
          )}
        </div>
      </div>
      
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
        {/* Contact Information */}
        <div>
          <h3 className="font-semibold text-gray-900 mb-3">Contact Information</h3>
          <div className="space-y-2 text-sm">
            <div>
              <span className="font-medium">Email:</span> {user.email}
            </div>
            {user.phone_number && (
              <div>
                <span className="font-medium">Phone:</span> {user.phone_number}
              </div>
            )}
            <div>
              <span className="font-medium">Language:</span> {user.preferred_language.toUpperCase()}
            </div>
          </div>
        </div>
        
        {/* Account Details */}
        <div>
          <h3 className="font-semibold text-gray-900 mb-3">Account Details</h3>
          <div className="space-y-2 text-sm">
            <div>
              <span className="font-medium">User ID:</span> {user.id}
            </div>
            <div>
              <span className="font-medium">Auth Provider:</span> {user.auth_provider}
            </div>
            {user.rfid_card_id && (
              <div>
                <span className="font-medium">RFID Card:</span> {user.rfid_card_id}
              </div>
            )}
            <div>
              <span className="font-medium">Role:</span> {user.role}
            </div>
          </div>
        </div>
        
        {/* Activity */}
        <div>
          <h3 className="font-semibold text-gray-900 mb-3">Activity</h3>
          <div className="space-y-2 text-sm">
            <div>
              <span className="font-medium">Created:</span> {new Date(user.created_at).toLocaleDateString()}
            </div>
            <div>
              <span className="font-medium">Last Updated:</span> {new Date(user.updated_at).toLocaleDateString()}
            </div>
            {user.last_login ? (
              <div>
                <span className="font-medium">Last Login:</span> {new Date(user.last_login).toLocaleDateString()}
              </div>
            ) : (
              <div className="text-gray-500">Never logged in</div>
            )}
            {user.terms_accepted_at && (
              <div>
                <span className="font-medium">Terms Accepted:</span> {new Date(user.terms_accepted_at).toLocaleDateString()}
              </div>
            )}
          </div>
        </div>
      </div>
      
      {/* Wallet Information */}
      <div className="mt-6 pt-6 border-t">
        <div className="flex items-center justify-between mb-3">
          <h3 className="font-semibold text-gray-900">Wallet & Usage</h3>
          <div className="text-2xl font-bold text-green-600">
            ₹{user.wallet_balance?.toFixed(2) || '0.00'}
          </div>
        </div>
        <div className="grid grid-cols-2 md:grid-cols-4 gap-4 text-sm">
          <div className="text-center p-3 bg-gray-50 rounded-lg">
            <div className="font-semibold text-lg">{user.total_transactions}</div>
            <div className="text-gray-600">Charging Sessions</div>
          </div>
          <div className="text-center p-3 bg-gray-50 rounded-lg">
            <div className="font-semibold text-lg">{user.total_wallet_transactions}</div>
            <div className="text-gray-600">Wallet Transactions</div>
          </div>
        </div>
      </div>
      
      {/* Notification Preferences */}
      {user.notification_preferences && Object.keys(user.notification_preferences).length > 0 && (
        <div className="mt-6 pt-6 border-t">
          <h3 className="font-semibold text-gray-900 mb-3">Notification Preferences</h3>
          <div className="flex flex-wrap gap-2">
            {Object.entries(user.notification_preferences).map(([key, value]) => (
              <Badge key={key} variant={value ? "default" : "secondary"}>
                {key}: {value ? "enabled" : "disabled"}
              </Badge>
            ))}
          </div>
        </div>
      )}
    </Card>
  );
}

function TransactionSummaryCard({ userId }: { userId: number }) {
  const { data: summary, isLoading, error } = useUserTransactionSummary(userId);
  
  if (isLoading) {
    return (
      <Card className="p-6">
        <div className="animate-pulse space-y-3">
          <div className="h-4 bg-gray-200 rounded w-1/3"></div>
          <div className="h-8 bg-gray-200 rounded"></div>
        </div>
      </Card>
    );
  }
  
  if (error || !summary) {
    return (
      <Card className="p-6">
        <p className="text-red-600">Failed to load transaction summary</p>
      </Card>
    );
  }
  
  return (
    <Card className="p-6">
      <h3 className="font-semibold text-gray-900 mb-4">Transaction Summary</h3>
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        <div className="text-center p-4 bg-blue-50 rounded-lg">
          <div className="text-2xl font-bold text-blue-600">{summary.charging_transactions}</div>
          <div className="text-sm text-blue-800">Charging Sessions</div>
        </div>
        <div className="text-center p-4 bg-purple-50 rounded-lg">
          <div className="text-2xl font-bold text-purple-600">{summary.wallet_transactions}</div>
          <div className="text-sm text-purple-800">Wallet Transactions</div>
        </div>
        <div className="text-center p-4 bg-green-50 rounded-lg">
          <div className="text-2xl font-bold text-green-600">{summary.total_energy_consumed} kWh</div>
          <div className="text-sm text-green-800">Energy Consumed</div>
        </div>
        <div className="text-center p-4 bg-red-50 rounded-lg">
          <div className="text-2xl font-bold text-red-600">₹{summary.total_amount_spent}</div>
          <div className="text-sm text-red-800">Total Spent</div>
        </div>
      </div>
      {summary.last_transaction_date && (
        <div className="mt-4 text-sm text-gray-600">
          <span className="font-medium">Last Transaction:</span> {new Date(summary.last_transaction_date).toLocaleDateString()}
        </div>
      )}
    </Card>
  );
}

export default function UserDetailPage() {
  const params = useParams();
  const userId = parseInt(params.id as string);
  
  const { data: user, isLoading, error } = useUser(userId);
  
  if (isLoading) {
    return (
      <AdminOnly fallback={
        <div className="flex items-center justify-center min-h-[400px]">
          <div className="text-center">
            <h2 className="text-2xl font-bold text-gray-900 mb-2">Access Denied</h2>
            <p className="text-gray-600 mb-4">You need administrator privileges to view user details.</p>
            <Link href="/admin" className="text-blue-600 hover:text-blue-800">
              Go to Admin Dashboard →
            </Link>
          </div>
        </div>
      }>
        <div className="flex items-center justify-center py-8">
          <div className="text-center">
            <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-primary mx-auto"></div>
            <p className="text-muted-foreground mt-2">Loading user details...</p>
          </div>
        </div>
      </AdminOnly>
    );
  }
  
  if (error || !user) {
    return (
      <AdminOnly fallback={
        <div className="flex items-center justify-center min-h-[400px]">
          <div className="text-center">
            <h2 className="text-2xl font-bold text-gray-900 mb-2">Access Denied</h2>
            <p className="text-gray-600 mb-4">You need administrator privileges to view user details.</p>
            <Link href="/admin" className="text-blue-600 hover:text-blue-800">
              Go to Admin Dashboard →
            </Link>
          </div>
        </div>
      }>
        <div className="text-center py-8">
          <p className="text-red-600">User not found or failed to load</p>
          <Link href="/admin/users" className="text-blue-600 hover:text-blue-800 mt-2 inline-block">
            ← Back to Users
          </Link>
        </div>
      </AdminOnly>
    );
  }
  
  return (
    <AdminOnly fallback={
      <div className="flex items-center justify-center min-h-[400px]">
        <div className="text-center">
          <h2 className="text-2xl font-bold text-gray-900 mb-2">Access Denied</h2>
          <p className="text-gray-600 mb-4">You need administrator privileges to view user details.</p>
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
            <Link href="/admin/users" className="text-blue-600 hover:text-blue-800 text-sm mb-2 inline-block">
              ← Back to Users
            </Link>
            <h1 className="text-3xl font-bold">User Details</h1>
          </div>
          <div className="flex gap-2">
            <Link href={`/admin/users/${userId}/transactions`}>
              <Button variant="outline">
                View Transactions
              </Button>
            </Link>
            <Link href={`/admin/users/${userId}/wallet`}>
              <Button variant="outline">
                Wallet History
              </Button>
            </Link>
          </div>
        </div>
        
        {/* User Profile */}
        <UserProfileCard user={user} />
        
        {/* Transaction Summary */}
        <TransactionSummaryCard userId={userId} />
      </div>
    </AdminOnly>
  );
}