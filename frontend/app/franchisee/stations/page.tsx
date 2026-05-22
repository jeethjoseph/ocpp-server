"use client";

import Link from "next/link";
import { Building2, MapPin } from "lucide-react";

import { FranchiseeOnly } from "@/components/RoleWrapper";
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
import { usePortalStations } from "@/lib/queries/franchisee-portal";

export default function FranchiseeStationsPage() {
  const { data: stations, isLoading, error } = usePortalStations();

  return (
    <FranchiseeOnly
      fallback={
        <div className="flex items-center justify-center min-h-[400px]">
          <div className="text-center">
            <h2 className="text-2xl font-bold text-gray-900 mb-2">
              Access Denied
            </h2>
            <p className="text-gray-600">
              You need franchisee privileges to view stations.
            </p>
          </div>
        </div>
      }
    >
      <div className="space-y-6">
        <div>
          <h1 className="text-3xl font-bold">My Stations</h1>
          <p className="text-muted-foreground">
            View your charging station locations
          </p>
        </div>

        {isLoading ? (
          <div className="flex items-center justify-center py-8">
            <div className="text-center">
              <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-primary mx-auto" />
              <p className="text-muted-foreground mt-2">
                Loading stations...
              </p>
            </div>
          </div>
        ) : error ? (
          <div className="text-center py-8">
            <p className="text-destructive">Failed to load stations</p>
            <p className="text-muted-foreground text-sm mt-1">
              Please try refreshing the page
            </p>
          </div>
        ) : (
          <Card>
            <CardHeader>
              <CardTitle className="flex items-center gap-2">
                <Building2 className="h-5 w-5" />
                Stations
              </CardTitle>
            </CardHeader>
            <CardContent>
              {stations && stations.length > 0 ? (
                <Table>
                  <TableHeader>
                    <TableRow>
                      <TableHead>Name</TableHead>
                      <TableHead>Address</TableHead>
                      <TableHead>Chargers</TableHead>
                      <TableHead>State</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {stations.map(
                      (station: {
                        id: number;
                        name: string;
                        address: string;
                        charger_count: number;
                        state: string | null;
                      }) => (
                        <TableRow key={station.id}>
                          <TableCell className="font-medium">
                            <Link
                              href={`/franchisee/stations/${station.id}`}
                              className="text-blue-600 hover:text-blue-800 hover:underline"
                            >
                              {station.name}
                            </Link>
                          </TableCell>
                          <TableCell>
                            <div className="flex items-center gap-1">
                              <MapPin className="h-3 w-3 text-muted-foreground" />
                              {station.address}
                            </div>
                          </TableCell>
                          <TableCell>
                            <Badge variant="secondary">
                              {station.charger_count}
                            </Badge>
                          </TableCell>
                          <TableCell>{station.state || "--"}</TableCell>
                        </TableRow>
                      )
                    )}
                  </TableBody>
                </Table>
              ) : (
                <p className="text-center text-muted-foreground py-4">
                  No stations found
                </p>
              )}
            </CardContent>
          </Card>
        )}
      </div>
    </FranchiseeOnly>
  );
}
