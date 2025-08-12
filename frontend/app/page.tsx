"use client";

import { useUserRole, AuthenticatedOnly } from "@/components/RoleWrapper";
import { Card } from "@/components/ui/card";
import Link from "next/link";

export default function Dashboard() {
  const { role, isUser, user } = useUserRole();

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


      </div>
    </AuthenticatedOnly>
  );
}
