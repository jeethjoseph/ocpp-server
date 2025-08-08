"use client";

import { AdminOnly } from "@/components/RoleWrapper";
import { Card } from "@/components/ui/card";
import Link from "next/link";

export default function AdminChargersPage() {
  return (
    <AdminOnly fallback={
      <div className="flex items-center justify-center min-h-[400px]">
        <div className="text-center">
          <h2 className="text-2xl font-bold text-gray-900 mb-2">Access Denied</h2>
          <p className="text-gray-600 mb-4">You need administrator privileges to manage chargers.</p>
          <Link href="/dashboard" className="text-blue-600 hover:text-blue-800">
            Go to Dashboard →
          </Link>
        </div>
      </div>
    }>
      <div className="space-y-6">
        <div className="flex items-center justify-between">
          <h1 className="text-3xl font-bold">Charger Management</h1>
        </div>

        <Card className="p-6">
          <h3 className="text-lg font-semibold mb-4">OCPP Chargers</h3>
          <p className="text-gray-600 mb-4">
            Admin Chargers page is working! RBAC is functioning correctly.
          </p>
          
          <div className="bg-green-50 border border-green-200 rounded-lg p-4">
            <h4 className="text-green-800 font-medium mb-2">✅ Admin Access Confirmed</h4>
            <p className="text-green-700 text-sm">
              You can successfully access the admin chargers page.
            </p>
          </div>
        </Card>
      </div>
    </AdminOnly>
  );
}