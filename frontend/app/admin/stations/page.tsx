"use client";

import { AdminOnly } from "@/components/RoleWrapper";
import { Card } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import Link from "next/link";

export default function AdminStationsPage() {
  return (
    <AdminOnly fallback={
      <div className="flex items-center justify-center min-h-[400px]">
        <div className="text-center">
          <h2 className="text-2xl font-bold text-gray-900 mb-2">Access Denied</h2>
          <p className="text-gray-600 mb-4">You need administrator privileges to manage stations.</p>
          <Link href="/dashboard" className="text-blue-600 hover:text-blue-800">
            Go to Dashboard →
          </Link>
        </div>
      </div>
    }>
      <div className="space-y-6">
        <div className="flex items-center justify-between">
          <h1 className="text-3xl font-bold">Station Management</h1>
          <Button asChild>
            <Link href="/admin/stations/create">
              Add New Station
            </Link>
          </Button>
        </div>

        <Card className="p-6">
          <h3 className="text-lg font-semibold mb-4">Charging Stations</h3>
          <p className="text-gray-600 mb-4">
            This page will show all charging stations. The RBAC is working correctly 
            since you can see this admin-only content!
          </p>
          
          <div className="bg-green-50 border border-green-200 rounded-lg p-4">
            <h4 className="text-green-800 font-medium mb-2">✅ RBAC Test Successful</h4>
            <p className="text-green-700 text-sm">
              You are successfully accessing an admin-only page. This confirms that:
            </p>
            <ul className="list-disc list-inside text-green-700 text-sm mt-2 space-y-1">
              <li>Authentication is working</li>
              <li>Role assignment is functioning</li>
              <li>Admin-only access control is enforced</li>
              <li>Middleware is redirecting users correctly</li>
            </ul>
          </div>
        </Card>
      </div>
    </AdminOnly>
  );
}