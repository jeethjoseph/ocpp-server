"use client";

import { useParams } from "next/navigation";
import { FranchiseeOnly } from "@/components/RoleWrapper";
import {
  usePortalCharger,
  useRemoteStop,
  useResetCharger,
} from "@/lib/queries/franchisee-portal";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Zap, Square, RotateCcw } from "lucide-react";
import Link from "next/link";

const STATUS_COLORS: Record<string, string> = {
  Available: "bg-green-100 text-green-800",
  Preparing: "bg-blue-100 text-blue-800",
  Charging: "bg-blue-200 text-blue-900",
  SuspendedEVSE: "bg-yellow-100 text-yellow-800",
  SuspendedEV: "bg-yellow-100 text-yellow-800",
  Finishing: "bg-indigo-100 text-indigo-800",
  Reserved: "bg-purple-100 text-purple-800",
  Unavailable: "bg-gray-100 text-gray-800",
  Faulted: "bg-red-100 text-red-800",
};

function ChargerDetailContent() {
  const params = useParams();
  const chargerId = parseInt(params.id as string);

  const { data, isLoading, error } = usePortalCharger(chargerId);
  const remoteStop = useRemoteStop();
  const resetCharger = useResetCharger();

  if (isLoading) {
    return (
      <div className="flex items-center justify-center min-h-[400px]">
        <div className="text-center">
          <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-primary mx-auto" />
          <p className="text-muted-foreground mt-2">Loading charger...</p>
        </div>
      </div>
    );
  }

  if (error || !data) {
    return (
      <div className="flex items-center justify-center min-h-[400px]">
        <div className="text-center">
          <h2 className="text-2xl font-bold text-gray-900 mb-2">
            Failed to load charger
          </h2>
          <p className="text-gray-600">Please try refreshing the page.</p>
        </div>
      </div>
    );
  }

  const status = data.latest_status || "Unknown";

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-3xl font-bold">{data.name}</h1>
          <p className="text-muted-foreground font-mono text-sm">
            {data.charge_point_string_id}
          </p>
        </div>
        <Badge
          variant="secondary"
          className={STATUS_COLORS[status] || "bg-gray-100 text-gray-800"}
        >
          {status}
        </Badge>
      </div>

      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <Zap className="h-5 w-5" />
            Charger Details
          </CardTitle>
        </CardHeader>
        <CardContent className="grid grid-cols-1 sm:grid-cols-2 gap-4 text-sm">
          <InfoRow label="Name" value={data.name} />
          <InfoRow
            label="Charge Point ID"
            value={data.charge_point_string_id}
          />
          <InfoRow label="Model" value={data.model || "N/A"} />
          <InfoRow label="Vendor" value={data.vendor || "N/A"} />
          <InfoRow label="Serial Number" value={data.serial_number || "N/A"} />
          <InfoRow
            label="Firmware"
            value={data.firmware_version || "N/A"}
          />
          <InfoRow label="Status" value={status} />
          <InfoRow label="Station" value={data.station_name || "N/A"} />
          {data.last_heart_beat_time && (
            <InfoRow
              label="Last Heartbeat"
              value={new Date(data.last_heart_beat_time).toLocaleString()}
            />
          )}
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Actions</CardTitle>
        </CardHeader>
        <CardContent className="flex gap-3">
          <Button
            variant="destructive"
            onClick={() => remoteStop.mutate(chargerId)}
            disabled={remoteStop.isPending}
          >
            <Square className="h-4 w-4 mr-2" />
            {remoteStop.isPending ? "Stopping..." : "Remote Stop"}
          </Button>
          <Button
            variant="outline"
            onClick={() => resetCharger.mutate(chargerId)}
            disabled={resetCharger.isPending}
          >
            <RotateCcw className="h-4 w-4 mr-2" />
            {resetCharger.isPending ? "Resetting..." : "Soft Reset"}
          </Button>
        </CardContent>
      </Card>
    </div>
  );
}

function InfoRow({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <span className="text-muted-foreground">{label}:</span>{" "}
      <span className="font-medium">{value}</span>
    </div>
  );
}

export default function ChargerDetailPage() {
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
              Go to Dashboard
            </Link>
          </div>
        </div>
      }
    >
      <ChargerDetailContent />
    </FranchiseeOnly>
  );
}
