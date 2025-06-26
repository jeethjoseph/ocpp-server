"use client";

import { useState } from "react";
import { Building2, MapPin, Plus, Pencil, Trash2 } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";

import { Station, StationCreate, StationUpdate } from "@/types/api";
import {
  useStations,
  useCreateStation,
  useUpdateStation,
  useDeleteStation,
} from "@/lib/queries/stations";

export default function StationsPage() {
  const [showCreateDialog, setShowCreateDialog] = useState(false);
  const [editingStation, setEditingStation] = useState<Station | null>(null);
  const [searchTerm, setSearchTerm] = useState("");
  const [currentPage, setCurrentPage] = useState(1);

  // TanStack Query hooks
  const {
    data: stationsData,
    isLoading,
    error,
  } = useStations({
    page: currentPage,
    limit: 10,
    search: searchTerm || undefined,
  });

  const createStationMutation = useCreateStation();
  const updateStationMutation = useUpdateStation();
  const deleteStationMutation = useDeleteStation();

  // Extract data from query
  const stations = stationsData?.data || [];
  const totalPages = stationsData ? Math.ceil(stationsData.total / 10) : 1;

  const handleCreateStation = (data: StationCreate) => {
    createStationMutation.mutate(data, {
      onSuccess: () => {
        setShowCreateDialog(false);
      },
    });
  };

  const handleUpdateStation = (data: StationUpdate) => {
    if (!editingStation) return;
    updateStationMutation.mutate(
      { id: editingStation.id, data },
      {
        onSuccess: () => {
          setEditingStation(null);
        },
      }
    );
  };

  const handleDeleteStation = (id: number) => {
    if (!confirm("Are you sure you want to delete this station?")) return;
    deleteStationMutation.mutate(id);
  };

  if (isLoading) {
    return (
      <div className="flex items-center justify-center py-8">
        <div className="text-center">
          <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-primary mx-auto"></div>
          <p className="text-muted-foreground mt-2">Loading stations...</p>
        </div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="text-center py-8">
        <p className="text-destructive">Failed to load stations</p>
        <p className="text-muted-foreground text-sm mt-1">Please try refreshing the page</p>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <div className="flex justify-between items-center">
        <div>
          <h1 className="text-3xl font-bold">Charging Stations</h1>
          <p className="text-muted-foreground">Manage your charging station locations</p>
        </div>
        <Dialog open={showCreateDialog} onOpenChange={setShowCreateDialog}>
          <DialogTrigger asChild>
            <Button>
              <Plus className="h-4 w-4 mr-2" />
              Add Station
            </Button>
          </DialogTrigger>
          <DialogContent>
            <DialogHeader>
              <DialogTitle>Create New Station</DialogTitle>
              <DialogDescription>
                Add a new charging station location to your network.
              </DialogDescription>
            </DialogHeader>
            <StationForm
              onSubmit={handleCreateStation}
              isLoading={createStationMutation.isPending}
            />
          </DialogContent>
        </Dialog>
      </div>

      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <Building2 className="h-5 w-5" />
            Stations
          </CardTitle>
        </CardHeader>
        <CardContent>
          <div className="flex gap-4 mb-6">
            <Input
              placeholder="Search stations..."
              value={searchTerm}
              onChange={(e) => setSearchTerm(e.target.value)}
              className="max-w-sm"
            />
          </div>

          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Name</TableHead>
                <TableHead>Address</TableHead>
                <TableHead>Location</TableHead>
                <TableHead>Created</TableHead>
                <TableHead className="text-right">Actions</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {stations.map((station) => (
                <TableRow key={station.id}>
                  <TableCell className="font-medium">{station.name}</TableCell>
                  <TableCell>{station.address}</TableCell>
                  <TableCell>
                    <div className="flex items-center gap-1">
                      <MapPin className="h-3 w-3" />
                      <span className="text-sm">
                        {station.latitude?.toFixed(4)}, {station.longitude?.toFixed(4)}
                      </span>
                    </div>
                  </TableCell>
                  <TableCell>{new Date(station.created_at).toLocaleDateString()}</TableCell>
                  <TableCell className="text-right">
                    <div className="flex items-center justify-end gap-2">
                      <Button
                        variant="ghost"
                        size="sm"
                        onClick={() => setEditingStation(station)}
                      >
                        <Pencil className="h-4 w-4" />
                      </Button>
                      <Button
                        variant="ghost"
                        size="sm"
                        onClick={() => handleDeleteStation(station.id)}
                        disabled={deleteStationMutation.isPending}
                      >
                        <Trash2 className="h-4 w-4" />
                      </Button>
                    </div>
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </CardContent>
      </Card>

      {totalPages > 1 && (
        <div className="flex justify-center items-center gap-2">
          <Button
            variant="outline"
            size="sm"
            onClick={() => setCurrentPage((prev) => Math.max(1, prev - 1))}
            disabled={currentPage === 1}
          >
            Previous
          </Button>
          <span className="text-sm text-muted-foreground">
            Page {currentPage} of {totalPages}
          </span>
          <Button
            variant="outline"
            size="sm"
            onClick={() => setCurrentPage((prev) => Math.min(totalPages, prev + 1))}
            disabled={currentPage === totalPages}
          >
            Next
          </Button>
        </div>
      )}

      {/* Edit Station Dialog */}
      <Dialog open={!!editingStation} onOpenChange={() => setEditingStation(null)}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Edit Station</DialogTitle>
            <DialogDescription>
              Update the station information.
            </DialogDescription>
          </DialogHeader>
          {editingStation && (
            <StationForm
              station={editingStation}
              onSubmit={handleUpdateStation}
              isLoading={updateStationMutation.isPending}
            />
          )}
        </DialogContent>
      </Dialog>
    </div>
  );
}

interface StationFormProps {
  station?: Station;
  onSubmit: (data: StationCreate) => void;
  isLoading: boolean;
}

function StationForm({ station, onSubmit, isLoading }: StationFormProps) {
  const [formData, setFormData] = useState({
    name: station?.name || "",
    address: station?.address || "",
    latitude: station?.latitude || 0,
    longitude: station?.longitude || 0,
  });

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    onSubmit(formData);
  };

  return (
    <form onSubmit={handleSubmit} className="space-y-4">
      <div className="space-y-2">
        <Label htmlFor="name">Name</Label>
        <Input
          id="name"
          type="text"
          required
          value={formData.name}
          onChange={(e) => setFormData({ ...formData, name: e.target.value })}
          disabled={isLoading}
        />
      </div>
      
      <div className="space-y-2">
        <Label htmlFor="address">Address</Label>
        <Input
          id="address"
          type="text"
          required
          value={formData.address}
          onChange={(e) => setFormData({ ...formData, address: e.target.value })}
          disabled={isLoading}
        />
      </div>
      
      <div className="grid grid-cols-2 gap-4">
        <div className="space-y-2">
          <Label htmlFor="latitude">Latitude</Label>
          <Input
            id="latitude"
            type="number"
            step="any"
            required
            value={formData.latitude}
            onChange={(e) =>
              setFormData({
                ...formData,
                latitude: parseFloat(e.target.value),
              })
            }
            disabled={isLoading}
          />
        </div>
        <div className="space-y-2">
          <Label htmlFor="longitude">Longitude</Label>
          <Input
            id="longitude"
            type="number"
            step="any"
            required
            value={formData.longitude}
            onChange={(e) =>
              setFormData({
                ...formData,
                longitude: parseFloat(e.target.value),
              })
            }
            disabled={isLoading}
          />
        </div>
      </div>
      
      <DialogFooter>
        <Button type="submit" disabled={isLoading}>
          {isLoading ? "Saving..." : station ? "Update" : "Create"}
        </Button>
      </DialogFooter>
    </form>
  );
}
