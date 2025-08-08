"use client";

import { useUserRole, AuthenticatedOnly } from "@/components/RoleWrapper";
import { Card } from "@/components/ui/card";
import Link from "next/link";

export default function DashboardPage() {
  const { role, isAdmin, isUser, user } = useUserRole();

  return (
    <AuthenticatedOnly>
      <div className="space-y-6">
        <div className="flex items-center justify-between">
          <h1 className="text-3xl font-bold">Dashboard</h1>
          <div className="text-sm text-gray-600">
            Welcome, {user?.firstName || user?.emailAddresses[0]?.emailAddress}
            <span className="ml-2 px-2 py-1 bg-blue-100 text-blue-800 rounded-full text-xs">
              {role || 'Loading...'}
            </span>
          </div>
        </div>

        {/* Role-based content */}
        {isUser && (
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
            <Card className="p-6">
              <h3 className="text-lg font-semibold mb-2">My Charging Sessions</h3>
              <p className="text-gray-600 mb-4">View your recent charging history</p>
              <Link 
                href="/my-sessions" 
                className="text-blue-600 hover:text-blue-800 font-medium"
              >
                View Sessions →
              </Link>
            </Card>

            <Card className="p-6">
              <h3 className="text-lg font-semibold mb-2">Find Chargers</h3>
              <p className="text-gray-600 mb-4">Locate available charging stations</p>
              <Link 
                href="/stations" 
                className="text-blue-600 hover:text-blue-800 font-medium"
              >
                Find Stations →
              </Link>
            </Card>

            <Card className="p-6">
              <h3 className="text-lg font-semibold mb-2">My Wallet</h3>
              <p className="text-gray-600 mb-4">Check your balance and top up</p>
              <Link 
                href="/wallet" 
                className="text-blue-600 hover:text-blue-800 font-medium"
              >
                Manage Wallet →
              </Link>
            </Card>
          </div>
        )}

        {isAdmin && (
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
            <Card className="p-6">
              <h3 className="text-lg font-semibold mb-2">Station Management</h3>
              <p className="text-gray-600 mb-4">Manage charging stations</p>
              <Link 
                href="/admin/stations" 
                className="text-blue-600 hover:text-blue-800 font-medium"
              >
                Manage Stations →
              </Link>
            </Card>

            <Card className="p-6">
              <h3 className="text-lg font-semibold mb-2">Charger Management</h3>
              <p className="text-gray-600 mb-4">Monitor and control chargers</p>
              <Link 
                href="/admin/chargers" 
                className="text-blue-600 hover:text-blue-800 font-medium"
              >
                Manage Chargers →
              </Link>
            </Card>

            <Card className="p-6">
              <h3 className="text-lg font-semibold mb-2">System Analytics</h3>
              <p className="text-gray-600 mb-4">View system performance metrics</p>
              <Link 
                href="/admin/analytics" 
                className="text-blue-600 hover:text-blue-800 font-medium"
              >
                View Analytics →
              </Link>
            </Card>
          </div>
        )}

        {/* Quick Stats */}
        <div className="grid grid-cols-1 md:grid-cols-4 gap-4">
          <Card className="p-4">
            <h4 className="text-sm font-medium text-gray-600">Total Stations</h4>
            <p className="text-2xl font-bold">--</p>
          </Card>
          <Card className="p-4">
            <h4 className="text-sm font-medium text-gray-600">Active Chargers</h4>
            <p className="text-2xl font-bold">--</p>
          </Card>
          <Card className="p-4">
            <h4 className="text-sm font-medium text-gray-600">
              {isAdmin ? 'Total Sessions' : 'My Sessions'}
            </h4>
            <p className="text-2xl font-bold">--</p>
          </Card>
          <Card className="p-4">
            <h4 className="text-sm font-medium text-gray-600">
              {isAdmin ? 'System Status' : 'Wallet Balance'}
            </h4>
            <p className="text-2xl font-bold text-green-600">
              {isAdmin ? 'Online' : '--'}
            </p>
          </Card>
        </div>
      </div>
    </AuthenticatedOnly>
  );
}