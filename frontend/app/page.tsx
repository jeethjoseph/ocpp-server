"use client";

import Link from "next/link";
import { Building2, Zap, CheckCircle, Clock } from "lucide-react";

import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { useDashboardStats } from "@/lib/queries/dashboard";

export default function Dashboard() {
  const { data: stats, isLoading, error } = useDashboardStats();

  if (isLoading) {
    return (
      <div className="flex items-center justify-center py-8">
        <div className="text-center">
          <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-primary mx-auto"></div>
          <p className="text-muted-foreground mt-2">Loading dashboard...</p>
        </div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="text-center py-8">
        <p className="text-destructive">Failed to load dashboard data</p>
        <p className="text-muted-foreground text-sm mt-1">Please try refreshing the page</p>
      </div>
    );
  }

  return (
    <div className="space-y-8">
      <div>
        <h1 className="text-3xl font-bold">OCPP Admin Dashboard</h1>
        <p className="text-muted-foreground mt-2">
          Manage your EV charging stations and chargers
        </p>
      </div>

      {/* Stats Cards */}
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-6">
        <Card>
          <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
            <CardTitle className="text-sm font-medium">Total Stations</CardTitle>
            <Building2 className="h-4 w-4 text-muted-foreground" />
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold">{stats?.totalStations || 0}</div>
            <p className="text-xs text-muted-foreground">
              <Link href="/stations" className="text-primary hover:underline">
                Manage stations →
              </Link>
            </p>
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
            <CardTitle className="text-sm font-medium">Total Chargers</CardTitle>
            <Zap className="h-4 w-4 text-muted-foreground" />
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold">{stats?.totalChargers || 0}</div>
            <div className="flex gap-1 mt-1">
              <Badge variant="success" className="text-xs">
                {stats?.connectedChargers || 0} online
              </Badge>
              <Badge variant="outline" className="text-xs">
                {stats?.disconnectedChargers || 0} offline
              </Badge>
            </div>
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
            <CardTitle className="text-sm font-medium">Available</CardTitle>
            <CheckCircle className="h-4 w-4 text-green-600" />
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold text-green-600">{stats?.availableChargers || 0}</div>
            <p className="text-xs text-muted-foreground">Ready for charging</p>
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
            <CardTitle className="text-sm font-medium">Status Overview</CardTitle>
            <Clock className="h-4 w-4 text-muted-foreground" />
          </CardHeader>
          <CardContent>
            <div className="space-y-1">
              <div className="flex justify-between text-sm">
                <span>Charging:</span>
                <Badge variant="info">{stats?.chargingChargers || 0}</Badge>
              </div>
              <div className="flex justify-between text-sm">
                <span>Unavailable:</span>
                <Badge variant="warning">{stats?.unavailableChargers || 0}</Badge>
              </div>
              <div className="flex justify-between text-sm">
                <span>Faulted:</span>
                <Badge variant="destructive">{stats?.faultedChargers || 0}</Badge>
              </div>
            </div>
          </CardContent>
        </Card>
      </div>

      {/* Quick Actions */}
      <Card>
        <CardHeader>
          <CardTitle>Quick Actions</CardTitle>
          <CardDescription>Common management tasks</CardDescription>
        </CardHeader>
        <CardContent>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            <Button asChild variant="outline" className="h-auto p-4 justify-start">
              <Link href="/stations">
                <Building2 className="h-5 w-5 mr-2" />
                <div className="text-left">
                  <div className="font-medium">Add New Station</div>
                  <div className="text-sm text-muted-foreground">Create a new charging station</div>
                </div>
              </Link>
            </Button>
            <Button asChild variant="outline" className="h-auto p-4 justify-start">
              <Link href="/chargers">
                <Zap className="h-5 w-5 mr-2" />
                <div className="text-left">
                  <div className="font-medium">Add New Charger</div>
                  <div className="text-sm text-muted-foreground">Onboard a new charger</div>
                </div>
              </Link>
            </Button>
          </div>
        </CardContent>
      </Card>
    </div>
  );
}
