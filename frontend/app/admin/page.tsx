"use client";

import { AdminOnly, useUserRole } from "@/components/RoleWrapper";
import { Card } from "@/components/ui/card";
import Link from "next/link";

export default function AdminDashboard() {
  const { user } = useUserRole();

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
        <div className="grid grid-cols-1 md:grid-cols-5 gap-4">
          <Card className="p-4">
            <h4 className="text-sm font-medium text-gray-600">Total Stations</h4>
            <p className="text-2xl font-bold">--</p>
          </Card>
          <Card className="p-4">
            <h4 className="text-sm font-medium text-gray-600">Total Chargers</h4>
            <p className="text-2xl font-bold">--</p>
          </Card>
          <Card className="p-4">
            <h4 className="text-sm font-medium text-gray-600">Active Sessions</h4>
            <p className="text-2xl font-bold text-green-600">--</p>
          </Card>
          <Card className="p-4">
            <h4 className="text-sm font-medium text-gray-600">Total Users</h4>
            <p className="text-2xl font-bold">--</p>
          </Card>
          <Card className="p-4">
            <h4 className="text-sm font-medium text-gray-600">System Status</h4>
            <p className="text-2xl font-bold text-green-600">Online</p>
          </Card>
        </div>
      </div>
    </AdminOnly>
  );
}