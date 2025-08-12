"use client";

import { AdminOnly, useUserRole } from "@/components/RoleWrapper";
import { Card } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import Link from "next/link";
import { useDashboardStats } from "@/lib/queries/dashboard";

export default function AdminDashboard() {
  const { user } = useUserRole();
  const { data: stats, isLoading, error } = useDashboardStats();

  return (
    <AdminOnly fallback={
      <div className="flex items-center justify-center min-h-[400px]">
        <div className="text-center">
          <h2 className="text-2xl font-bold text-gray-900 mb-2">Access Denied</h2>
          <p className="text-gray-600 mb-4">You need administrator privileges to access this page.</p>
          <Link href="/dashboard" className="text-blue-600 hover:text-blue-800">
            Go to Dashboard →
          </Link>
        </div>
      </div>
    }>
      <div className="space-y-6">
        <div className="flex items-center justify-between">
          <h1 className="text-3xl font-bold">Admin Dashboard</h1>
          <div className="text-sm text-gray-600">
            Welcome Admin, {user?.firstName || user?.emailAddresses[0]?.emailAddress}
            <span className="ml-2 px-2 py-1 bg-red-100 text-red-800 rounded-full text-xs">
              ADMIN
            </span>
          </div>
        </div>

        {/* Admin Actions */}
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
          <Card className="p-6">
            <h3 className="text-lg font-semibold mb-2">Station Management</h3>
            <p className="text-gray-600 mb-4">Create, edit, and manage charging stations</p>
            <div className="space-y-2">
              <Link 
                href="/admin/stations" 
                className="block text-blue-600 hover:text-blue-800 font-medium"
              >
                View All Stations →
              </Link>
              <Link 
                href="/admin/stations/create" 
                className="block text-green-600 hover:text-green-800 font-medium"
              >
                Add New Station →
              </Link>
            </div>
          </Card>

          <Card className="p-6">
            <h3 className="text-lg font-semibold mb-2">Charger Management</h3>
            <p className="text-gray-600 mb-4">Monitor and control individual chargers</p>
            <div className="space-y-2">
              <Link 
                href="/admin/chargers" 
                className="block text-blue-600 hover:text-blue-800 font-medium"
              >
                View All Chargers →
              </Link>
              <Link 
                href="/admin/chargers/create" 
                className="block text-green-600 hover:text-green-800 font-medium"
              >
                Add New Charger →
              </Link>
            </div>
          </Card>

          <Card className="p-6">
            <h3 className="text-lg font-semibold mb-2">User Management</h3>
            <p className="text-gray-600 mb-4">Manage user accounts and roles</p>
            <div className="space-y-2">
              <Link 
                href="/admin/users" 
                className="block text-blue-600 hover:text-blue-800 font-medium"
              >
                View All Users →
              </Link>
              <Link 
                href="/admin/roles" 
                className="block text-purple-600 hover:text-purple-800 font-medium"
              >
                Manage Roles →
              </Link>
            </div>
          </Card>

          <Card className="p-6">
            <h3 className="text-lg font-semibold mb-2">Transaction Monitoring</h3>
            <p className="text-gray-600 mb-4">Monitor all charging transactions</p>
            <div className="space-y-2">
              <Link 
                href="/admin/transactions" 
                className="block text-blue-600 hover:text-blue-800 font-medium"
              >
                View Transactions →
              </Link>
              <Link 
                href="/admin/reports" 
                className="block text-orange-600 hover:text-orange-800 font-medium"
              >
                Generate Reports →
              </Link>
            </div>
          </Card>

          <Card className="p-6">
            <h3 className="text-lg font-semibold mb-2">System Monitoring</h3>
            <p className="text-gray-600 mb-4">Monitor system health and performance</p>
            <div className="space-y-2">
              <Link 
                href="/admin/monitoring" 
                className="block text-blue-600 hover:text-blue-800 font-medium"
              >
                System Status →
              </Link>
              <Link 
                href="/admin/logs" 
                className="block text-gray-600 hover:text-gray-800 font-medium"
              >
                View Logs →
              </Link>
            </div>
          </Card>

          <Card className="p-6">
            <h3 className="text-lg font-semibold mb-2">Settings</h3>
            <p className="text-gray-600 mb-4">Configure system settings</p>
            <div className="space-y-2">
              <Link 
                href="/admin/settings" 
                className="block text-blue-600 hover:text-blue-800 font-medium"
              >
                System Settings →
              </Link>
              <Link 
                href="/admin/billing" 
                className="block text-green-600 hover:text-green-800 font-medium"
              >
                Billing Configuration →
              </Link>
            </div>
          </Card>
        </div>

        {/* System Overview */}
        {isLoading ? (
          <div className="flex items-center justify-center py-8">
            <div className="text-center">
              <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-primary mx-auto"></div>
              <p className="text-muted-foreground mt-2">Loading dashboard data...</p>
            </div>
          </div>
        ) : error ? (
          <div className="text-center py-8">
            <p className="text-red-600">Failed to load dashboard data</p>
            <p className="text-gray-600 text-sm mt-1">
              Please try refreshing the page
            </p>
          </div>
        ) : (
          <div className="grid grid-cols-1 md:grid-cols-5 gap-4">
            <Card className="p-4">
              <h4 className="text-sm font-medium text-gray-600">Total Stations</h4>
              <p className="text-2xl font-bold">{stats?.totalStations || 0}</p>
            </Card>
            <Card className="p-4">
              <h4 className="text-sm font-medium text-gray-600">Total Chargers</h4>
              <p className="text-2xl font-bold">{stats?.totalChargers || 0}</p>
              <div className="flex gap-1 mt-2">
                <Badge variant="default" className="text-xs">
                  {stats?.connectedChargers || 0} online
                </Badge>
                <Badge variant="outline" className="text-xs">
                  {stats?.disconnectedChargers || 0} offline
                </Badge>
              </div>
            </Card>
            <Card className="p-4">
              <h4 className="text-sm font-medium text-gray-600">Available</h4>
              <p className="text-2xl font-bold text-green-600">{stats?.availableChargers || 0}</p>
              <p className="text-xs text-gray-500 mt-1">Ready for charging</p>
            </Card>
            <Card className="p-4">
              <h4 className="text-sm font-medium text-gray-600">Charging Now</h4>
              <p className="text-2xl font-bold text-blue-600">{stats?.chargingChargers || 0}</p>
              <p className="text-xs text-gray-500 mt-1">Active sessions</p>
            </Card>
            <Card className="p-4">
              <h4 className="text-sm font-medium text-gray-600">Status Overview</h4>
              <div className="space-y-1 mt-2">
                <div className="flex justify-between text-sm">
                  <span>Unavailable:</span>
                  <Badge variant="secondary" className="text-xs">
                    {stats?.unavailableChargers || 0}
                  </Badge>
                </div>
                <div className="flex justify-between text-sm">
                  <span>Faulted:</span>
                  <Badge variant="destructive" className="text-xs">
                    {stats?.faultedChargers || 0}
                  </Badge>
                </div>
              </div>
            </Card>
          </div>
        )}
      </div>
    </AdminOnly>
  );
}