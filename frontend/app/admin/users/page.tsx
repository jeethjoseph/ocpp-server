"use client";

import { useState } from "react";
import { AdminOnly } from "@/components/RoleWrapper";
import { Card } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";
import Link from "next/link";
import { useUsers, useDeactivateUser, useReactivateUser } from "@/lib/queries/users";
import { UserListItem } from "@/types/api";
import { toast } from "sonner";

function UserStatusBadge({ user }: { user: UserListItem }) {
  if (!user.is_active) {
    return <Badge variant="destructive">Deactivated</Badge>;
  }
  if (!user.is_email_verified) {
    return <Badge variant="secondary">Unverified</Badge>;
  }
  return <Badge variant="default">Active</Badge>;
}

function UserActionsCell({ user }: { user: UserListItem }) {
  const [showDeactivateDialog, setShowDeactivateDialog] = useState(false);
  const [showReactivateDialog, setShowReactivateDialog] = useState(false);
  
  const deactivateUser = useDeactivateUser();
  const reactivateUser = useReactivateUser();

  const handleDeactivate = async () => {
    try {
      await deactivateUser.mutateAsync(user.id);
      toast.success(`User ${user.display_name} has been deactivated`);
      setShowDeactivateDialog(false);
    } catch (error: unknown) {
      const errorMessage = error instanceof Error ? error.message : "Failed to deactivate user";
      toast.error(errorMessage);
    }
  };

  const handleReactivate = async () => {
    try {
      await reactivateUser.mutateAsync(user.id);
      toast.success(`User ${user.display_name} has been reactivated`);
      setShowReactivateDialog(false);
    } catch (error: unknown) {
      const errorMessage = error instanceof Error ? error.message : "Failed to reactivate user";
      toast.error(errorMessage);
    }
  };

  return (
    <div className="flex items-center gap-2">
      {/* View Details Link */}
      <Link 
        href={`/admin/users/${user.id}`}
        className="text-blue-600 hover:text-blue-800 text-sm font-medium"
      >
        Details
      </Link>
      
      {/* Transactions Link */}
      <Link 
        href={`/admin/users/${user.id}/transactions`}
        className="text-green-600 hover:text-green-800 text-sm font-medium"
      >
        Transactions
      </Link>
      
      {/* Wallet Link */}
      <Link 
        href={`/admin/users/${user.id}/wallet`}
        className="text-purple-600 hover:text-purple-800 text-sm font-medium"
      >
        Wallet
      </Link>

      {/* Deactivate/Reactivate Button */}
      {user.is_active ? (
        <Dialog open={showDeactivateDialog} onOpenChange={setShowDeactivateDialog}>
          <DialogTrigger asChild>
            <Button variant="destructive" size="sm">
              Deactivate
            </Button>
          </DialogTrigger>
          <DialogContent>
            <DialogHeader>
              <DialogTitle>Deactivate User</DialogTitle>
              <DialogDescription>
                Are you sure you want to deactivate <strong>{user.display_name}</strong> ({user.email})? 
                This will prevent them from logging in and using the system.
              </DialogDescription>
            </DialogHeader>
            <DialogFooter>
              <Button 
                variant="outline" 
                onClick={() => setShowDeactivateDialog(false)}
                disabled={deactivateUser.isPending}
              >
                Cancel
              </Button>
              <Button 
                variant="destructive" 
                onClick={handleDeactivate}
                disabled={deactivateUser.isPending}
              >
                {deactivateUser.isPending ? "Deactivating..." : "Deactivate User"}
              </Button>
            </DialogFooter>
          </DialogContent>
        </Dialog>
      ) : (
        <Dialog open={showReactivateDialog} onOpenChange={setShowReactivateDialog}>
          <DialogTrigger asChild>
            <Button variant="default" size="sm">
              Reactivate
            </Button>
          </DialogTrigger>
          <DialogContent>
            <DialogHeader>
              <DialogTitle>Reactivate User</DialogTitle>
              <DialogDescription>
                Are you sure you want to reactivate <strong>{user.display_name}</strong> ({user.email})? 
                This will allow them to log in and use the system again.
              </DialogDescription>
            </DialogHeader>
            <DialogFooter>
              <Button 
                variant="outline" 
                onClick={() => setShowReactivateDialog(false)}
                disabled={reactivateUser.isPending}
              >
                Cancel
              </Button>
              <Button 
                onClick={handleReactivate}
                disabled={reactivateUser.isPending}
              >
                {reactivateUser.isPending ? "Reactivating..." : "Reactivate User"}
              </Button>
            </DialogFooter>
          </DialogContent>
        </Dialog>
      )}
    </div>
  );
}

function UsersTable() {
  const [currentPage, setCurrentPage] = useState(1);
  const [searchTerm, setSearchTerm] = useState("");
  const [statusFilter, setStatusFilter] = useState<boolean | undefined>(undefined);
  
  const { data: usersData, isLoading, error } = useUsers({
    page: currentPage,
    limit: 20,
    search: searchTerm || undefined,
    is_active: statusFilter,
  });

  if (isLoading) {
    return (
      <div className="flex items-center justify-center py-8">
        <div className="text-center">
          <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-primary mx-auto"></div>
          <p className="text-muted-foreground mt-2">Loading users...</p>
        </div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="text-center py-8">
        <p className="text-red-600">Failed to load users</p>
        <p className="text-gray-600 text-sm mt-1">
          Please try refreshing the page or contact support
        </p>
      </div>
    );
  }

  const users = usersData?.data || [];
  const totalPages = usersData?.total_pages || 1;

  return (
    <div className="space-y-4">
      {/* Filters */}
      <div className="flex flex-col sm:flex-row gap-4 items-start sm:items-center">
        <div className="flex-1 max-w-md">
          <Input
            placeholder="Search by name, email, or phone..."
            value={searchTerm}
            onChange={(e) => setSearchTerm(e.target.value)}
            className="w-full"
          />
        </div>
        <div className="flex gap-2">
          <Button
            variant={statusFilter === true ? "default" : "outline"}
            size="sm"
            onClick={() => setStatusFilter(statusFilter === true ? undefined : true)}
          >
            Active Only
          </Button>
          <Button
            variant={statusFilter === false ? "default" : "outline"}
            size="sm"
            onClick={() => setStatusFilter(statusFilter === false ? undefined : false)}
          >
            Inactive Only
          </Button>
        </div>
      </div>

      {/* Users Table */}
      <Card>
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>User</TableHead>
              <TableHead>Contact</TableHead>
              <TableHead>Status</TableHead>
              <TableHead>Wallet</TableHead>
              <TableHead>Activity</TableHead>
              <TableHead>Actions</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {users.map((user) => (
              <TableRow key={user.id}>
                <TableCell>
                  <div>
                    <div className="font-medium">{user.display_name}</div>
                    <div className="text-sm text-gray-600">{user.email}</div>
                    <div className="text-xs text-gray-500">ID: {user.id}</div>
                  </div>
                </TableCell>
                <TableCell>
                  <div className="text-sm">
                    {user.phone_number && (
                      <div>{user.phone_number}</div>
                    )}
                    <div className="text-gray-600">{user.auth_provider}</div>
                    {user.rfid_card_id && (
                      <div className="text-xs text-gray-500">RFID: {user.rfid_card_id}</div>
                    )}
                  </div>
                </TableCell>
                <TableCell>
                  <UserStatusBadge user={user} />
                </TableCell>
                <TableCell>
                  <div className="text-sm">
                    <div className="font-medium">₹{user.wallet_balance?.toFixed(2) || '0.00'}</div>
                    <div className="text-gray-600">{user.total_wallet_transactions} transactions</div>
                  </div>
                </TableCell>
                <TableCell>
                  <div className="text-sm">
                    <div>{user.total_transactions} charging sessions</div>
                    <div className="text-gray-600">
                      {user.last_login ? 
                        `Last login: ${new Date(user.last_login).toLocaleDateString()}` : 
                        'Never logged in'
                      }
                    </div>
                  </div>
                </TableCell>
                <TableCell>
                  <UserActionsCell user={user} />
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </Card>

      {/* Pagination */}
      {totalPages > 1 && (
        <div className="flex items-center justify-between">
          <div className="text-sm text-gray-600">
            Showing {users.length} of {usersData?.total || 0} users
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

export default function AdminUsersPage() {
  return (
    <AdminOnly fallback={
      <div className="flex items-center justify-center min-h-[400px]">
        <div className="text-center">
          <h2 className="text-2xl font-bold text-gray-900 mb-2">Access Denied</h2>
          <p className="text-gray-600 mb-4">You need administrator privileges to manage users.</p>
          <Link href="/dashboard" className="text-blue-600 hover:text-blue-800">
            Go to Dashboard →
          </Link>
        </div>
      </div>
    }>
      <div className="space-y-6">
        <div className="flex items-center justify-between">
          <div>
            <h1 className="text-3xl font-bold">User Management</h1>
            <p className="text-gray-600 mt-1">Manage EV driver accounts, view transactions, and control access</p>
          </div>
        </div>

        <UsersTable />
      </div>
    </AdminOnly>
  );
}