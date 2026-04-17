"use client";

import { FranchiseeOnly } from "@/components/RoleWrapper";
import { usePortalDashboard } from "@/lib/queries/franchisee-portal";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import Link from "next/link";
import { Building2, Zap, DollarSign, Activity } from "lucide-react";

function StatusBadge({ status }: { status: string }) {
  const variant =
    status === "ACTIVE"
      ? "default"
      : status === "SUSPENDED"
        ? "destructive"
        : "secondary";

  return <Badge variant={variant}>{status}</Badge>;
}

function DashboardContent() {
  const { data, isLoading, error } = usePortalDashboard();

  if (isLoading) {
    return (
      <div className="flex items-center justify-center min-h-[400px]">
        <div className="text-center">
          <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-primary mx-auto" />
          <p className="text-muted-foreground mt-2">Loading dashboard...</p>
        </div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="flex items-center justify-center min-h-[400px]">
        <div className="text-center">
          <h2 className="text-2xl font-bold text-gray-900 mb-2">
            Failed to load dashboard
          </h2>
          <p className="text-gray-600">Please try refreshing the page.</p>
        </div>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h1 className="text-3xl font-bold">Franchisee Dashboard</h1>
        {data?.franchisee_status && (
          <StatusBadge status={data.franchisee_status} />
        )}
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4">
        <Card>
          <CardHeader className="flex flex-row items-center justify-between pb-2">
            <CardTitle className="text-sm font-medium text-muted-foreground">
              Station Count
            </CardTitle>
            <Building2 className="h-4 w-4 text-muted-foreground" />
          </CardHeader>
          <CardContent>
            <p className="text-2xl font-bold">{data?.station_count ?? 0}</p>
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="flex flex-row items-center justify-between pb-2">
            <CardTitle className="text-sm font-medium text-muted-foreground">
              Charger Count
            </CardTitle>
            <Zap className="h-4 w-4 text-muted-foreground" />
          </CardHeader>
          <CardContent>
            <p className="text-2xl font-bold">{data?.charger_count ?? 0}</p>
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="flex flex-row items-center justify-between pb-2">
            <CardTitle className="text-sm font-medium text-muted-foreground">
              Active Sessions
            </CardTitle>
            <Activity className="h-4 w-4 text-muted-foreground" />
          </CardHeader>
          <CardContent>
            <p className="text-2xl font-bold text-blue-600">
              {data?.active_sessions ?? 0}
            </p>
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="flex flex-row items-center justify-between pb-2">
            <CardTitle className="text-sm font-medium text-muted-foreground">
              Total Payout
            </CardTitle>
            <DollarSign className="h-4 w-4 text-muted-foreground" />
          </CardHeader>
          <CardContent>
            <p className="text-2xl font-bold text-green-600">
              {data?.total_payout ?? "0.00"}
            </p>
          </CardContent>
        </Card>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
        <Card className="p-6">
          <h3 className="text-lg font-semibold mb-2">Stations</h3>
          <p className="text-gray-600 mb-4">
            View and manage your charging stations
          </p>
          <Link
            href="/franchisee/stations"
            className="text-blue-600 hover:text-blue-800 font-medium"
          >
            View Stations →
          </Link>
        </Card>

        <Card className="p-6">
          <h3 className="text-lg font-semibold mb-2">Transactions</h3>
          <p className="text-gray-600 mb-4">
            Monitor charging transactions across your stations
          </p>
          <Link
            href="/franchisee/transactions"
            className="text-blue-600 hover:text-blue-800 font-medium"
          >
            View Transactions →
          </Link>
        </Card>

        <Card className="p-6">
          <h3 className="text-lg font-semibold mb-2">Settlements</h3>
          <p className="text-gray-600 mb-4">
            Track your payouts and settlement history
          </p>
          <Link
            href="/franchisee/settlements"
            className="text-blue-600 hover:text-blue-800 font-medium"
          >
            View Settlements →
          </Link>
        </Card>
      </div>
    </div>
  );
}

export default function FranchiseeDashboard() {
  return (
    <FranchiseeOnly
      fallback={
        <div className="flex items-center justify-center min-h-[400px]">
          <div className="text-center">
            <h2 className="text-2xl font-bold text-gray-900 mb-2">
              Access Denied
            </h2>
            <p className="text-gray-600 mb-4">
              You need franchisee privileges to access this page.
            </p>
            <Link
              href="/dashboard"
              className="text-blue-600 hover:text-blue-800"
            >
              Go to Dashboard →
            </Link>
          </div>
        </div>
      }
    >
      <DashboardContent />
    </FranchiseeOnly>
  );
}
