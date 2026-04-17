"use client";

import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { ArrowLeft, Building2, Cpu } from "lucide-react";

import { FranchiseeOnly } from "@/components/RoleWrapper";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { usePortalStation } from "@/lib/queries/franchisee-portal";

function formatHeartbeat(iso: string | null): string {
  if (!iso) return "--";
  return new Date(iso).toLocaleString();
}

function statusVariant(
  status: string | null
): "default" | "secondary" | "destructive" | "outline" {
  if (!status) return "outline";
  const s = status.toLowerCase();
  if (s === "available") return "default";
  if (s === "charging" || s === "occupied") return "secondary";
  if (s === "faulted" || s === "unavailable") return "destructive";
  return "outline";
}

export default function FranchiseeStationDetailPage() {
  const params = useParams();
  const router = useRouter();
  const stationId = Number(params.id);

  const { data, isLoading, error } = usePortalStation(stationId);

  const station = data?.station;
  const chargers = data?.chargers || [];

  return (
    <FranchiseeOnly
      fallback={
        <div className="flex items-center justify-center min-h-[400px]">
          <div className="text-center">
            <h2 className="text-2xl font-bold text-gray-900 mb-2">
              Access Denied
            </h2>
            <p className="text-gray-600">
              You need franchisee privileges to view this station.
            </p>
          </div>
        </div>
      }
    >
      <div className="space-y-6">
        <Button
          variant="ghost"
          size="sm"
          onClick={() => router.push("/franchisee/stations")}
        >
          <ArrowLeft className="h-4 w-4 mr-1" />
          Back to Stations
        </Button>

        {isLoading ? (
          <div className="flex items-center justify-center py-8">
            <div className="text-center">
              <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-primary mx-auto" />
              <p className="text-muted-foreground mt-2">
                Loading station...
              </p>
            </div>
          </div>
        ) : error ? (
          <div className="text-center py-8">
            <p className="text-destructive">Failed to load station</p>
            <p className="text-muted-foreground text-sm mt-1">
              Please try refreshing the page
            </p>
          </div>
        ) : station ? (
          <>
            <Card>
              <CardHeader>
                <CardTitle className="flex items-center gap-2">
                  <Building2 className="h-5 w-5" />
                  {station.name}
                </CardTitle>
              </CardHeader>
              <CardContent>
                <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                  <div>
                    <p className="text-sm text-muted-foreground">Address</p>
                    <p className="font-medium">{station.address}</p>
                  </div>
                  <div>
                    <p className="text-sm text-muted-foreground">State</p>
                    <p className="font-medium">{station.state || "--"}</p>
                  </div>
                  <div>
                    <p className="text-sm text-muted-foreground">Pincode</p>
                    <p className="font-medium">{station.pincode || "--"}</p>
                  </div>
                </div>
              </CardContent>
            </Card>

            <Card>
              <CardHeader>
                <CardTitle className="flex items-center gap-2">
                  <Cpu className="h-5 w-5" />
                  Chargers ({chargers.length})
                </CardTitle>
              </CardHeader>
              <CardContent>
                {chargers.length > 0 ? (
                  <Table>
                    <TableHeader>
                      <TableRow>
                        <TableHead>Name</TableHead>
                        <TableHead>ID</TableHead>
                        <TableHead>Status</TableHead>
                        <TableHead>Last Heartbeat</TableHead>
                      </TableRow>
                    </TableHeader>
                    <TableBody>
                      {chargers.map(
                        (charger: {
                          id: number;
                          name: string;
                          charge_point_string_id: string;
                          latest_status: string | null;
                          last_heart_beat_time: string | null;
                        }) => (
                          <TableRow key={charger.id}>
                            <TableCell className="font-medium">
                              <Link
                                href={`/franchisee/chargers/${charger.id}`}
                                className="text-blue-600 hover:text-blue-800 hover:underline"
                              >
                                {charger.name}
                              </Link>
                            </TableCell>
                            <TableCell className="font-mono text-sm">
                              {charger.charge_point_string_id}
                            </TableCell>
                            <TableCell>
                              <Badge variant={statusVariant(charger.latest_status)}>
                                {charger.latest_status || "Unknown"}
                              </Badge>
                            </TableCell>
                            <TableCell>
                              {formatHeartbeat(charger.last_heart_beat_time)}
                            </TableCell>
                          </TableRow>
                        )
                      )}
                    </TableBody>
                  </Table>
                ) : (
                  <p className="text-center text-muted-foreground py-4">
                    No chargers at this station
                  </p>
                )}
              </CardContent>
            </Card>
          </>
        ) : null}
      </div>
    </FranchiseeOnly>
  );
}
