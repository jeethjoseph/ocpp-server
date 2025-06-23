"use client";

import { useState, useEffect, useCallback } from "react";
import { Station, StationCreate, StationUpdate } from "@/types/api";
import { stationService } from "@/lib/api-services";

export default function StationsPage() {
  const [stations, setStations] = useState<Station[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [showCreateModal, setShowCreateModal] = useState(false);
  const [editingStation, setEditingStation] = useState<Station | null>(null);
  const [searchTerm, setSearchTerm] = useState("");
  const [currentPage, setCurrentPage] = useState(1);
  const [totalPages, setTotalPages] = useState(1);

  // Move loadStations to component scope so it can be used elsewhere
  const loadStations = useCallback(async () => {
    try {
      setLoading(true);
      const response = await stationService.getAll({
        page: currentPage,
        limit: 10,
        search: searchTerm || undefined,
      });
      setStations(response.data);
      setTotalPages(Math.ceil(response.total / 10));
    } catch (err) {
      setError("Failed to load stations");
      console.error(err);
    } finally {
      setLoading(false);
    }
  }, [currentPage, searchTerm]);

  useEffect(() => {
    loadStations();
  }, [loadStations]);

  const handleCreateStation = async (data: StationCreate) => {
    try {
      await stationService.create(data);
      setShowCreateModal(false);
      loadStations();
    } catch (err) {
      setError("Failed to create station");
      console.error(err);
    }
  };

  const handleUpdateStation = async (id: number, data: StationUpdate) => {
    try {
      await stationService.update(id, data);
      setEditingStation(null);
      loadStations();
    } catch (err) {
      setError("Failed to update station");
      console.error(err);
    }
  };

  const handleDeleteStation = async (id: number) => {
    if (!confirm("Are you sure you want to delete this station?")) return;

    try {
      await stationService.delete(id);
      loadStations();
    } catch (err) {
      setError("Failed to delete station");
      console.error(err);
    }
  };

  if (loading && stations.length === 0) {
    return (
      <div className="text-center py-8 text-muted-foreground">
        Loading stations...
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <div className="flex justify-between items-center">
        <h1 className="text-3xl font-bold text-foreground">
          Charging Stations
        </h1>
        <button
          onClick={() => setShowCreateModal(true)}
          className="bg-primary text-primary-foreground px-4 py-2 rounded-lg hover:bg-primary/90 focus:outline-none focus:ring-2 focus:ring-primary transition-colors duration-200">
          Add Station
        </button>
      </div>

      {error && (
        <div className="bg-destructive/10 border border-destructive/20 text-destructive px-4 py-3 rounded-lg">
          {error}
        </div>
      )}

      <div className="flex gap-4 mb-6">
        <input
          type="text"
          placeholder="Search stations..."
          value={searchTerm}
          onChange={(e) => setSearchTerm(e.target.value)}
          className="flex-1 px-4 py-2 bg-input border border-border rounded-lg focus:outline-none focus:ring-2 focus:ring-primary text-foreground placeholder:text-muted-foreground transition-colors duration-200"
        />
      </div>

      <div className="bg-card shadow overflow-hidden sm:rounded-lg border border-border">
        <div className="overflow-x-auto">
          <table className="min-w-full divide-y divide-border">
            <thead className="bg-muted">
              <tr>
                <th className="px-6 py-3 text-left text-xs font-medium text-muted-foreground uppercase tracking-wider">
                  Name
                </th>
                <th className="px-6 py-3 text-left text-xs font-medium text-muted-foreground uppercase tracking-wider">
                  Address
                </th>
                <th className="px-6 py-3 text-left text-xs font-medium text-muted-foreground uppercase tracking-wider">
                  Location
                </th>
                <th className="px-6 py-3 text-left text-xs font-medium text-muted-foreground uppercase tracking-wider">
                  Created
                </th>
                <th className="px-6 py-3 text-right text-xs font-medium text-muted-foreground uppercase tracking-wider">
                  Actions
                </th>
              </tr>
            </thead>
            <tbody className="bg-card divide-y divide-border">
              {stations.map((station) => (
                <tr
                  key={station.id}
                  className="hover:bg-accent transition-colors duration-150">
                  <td className="px-6 py-4 whitespace-nowrap text-sm font-medium text-card-foreground">
                    {station.name}
                  </td>
                  <td className="px-6 py-4 whitespace-nowrap text-sm text-muted-foreground">
                    {station.address}
                  </td>
                  <td className="px-6 py-4 whitespace-nowrap text-sm text-muted-foreground">
                    {station.latitude.toFixed(4)},{" "}
                    {station.longitude.toFixed(4)}
                  </td>
                  <td className="px-6 py-4 whitespace-nowrap text-sm text-muted-foreground">
                    {new Date(station.created_at).toLocaleDateString()}
                  </td>
                  <td className="px-6 py-4 whitespace-nowrap text-right text-sm font-medium space-x-2">
                    <button
                      onClick={() => setEditingStation(station)}
                      className="text-primary hover:text-primary/80 transition-colors duration-200">
                      Edit
                    </button>
                    <button
                      onClick={() => handleDeleteStation(station.id)}
                      className="text-destructive hover:text-destructive/80 transition-colors duration-200">
                      Delete
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      {totalPages > 1 && (
        <div className="flex justify-center space-x-2 mt-6">
          <button
            onClick={() => setCurrentPage((prev) => Math.max(1, prev - 1))}
            disabled={currentPage === 1}
            className="px-3 py-2 text-sm border border-border rounded bg-card text-card-foreground hover:bg-accent disabled:opacity-50 disabled:cursor-not-allowed transition-colors duration-200">
            Previous
          </button>
          <span className="px-3 py-2 text-sm text-muted-foreground">
            Page {currentPage} of {totalPages}
          </span>
          <button
            onClick={() =>
              setCurrentPage((prev) => Math.min(totalPages, prev + 1))
            }
            disabled={currentPage === totalPages}
            className="px-3 py-2 text-sm border border-border rounded bg-card text-card-foreground hover:bg-accent disabled:opacity-50 disabled:cursor-not-allowed transition-colors duration-200">
            Next
          </button>
        </div>
      )}

      {showCreateModal && (
        <StationModal
          onSubmit={handleCreateStation}
          onClose={() => setShowCreateModal(false)}
        />
      )}

      {editingStation && (
        <StationModal
          station={editingStation}
          onSubmit={(data) => handleUpdateStation(editingStation.id, data)}
          onClose={() => setEditingStation(null)}
        />
      )}
    </div>
  );
}

interface StationModalProps {
  station?: Station;
  onSubmit: (data: StationCreate) => void;
  onClose: () => void;
}

function StationModal({ station, onSubmit, onClose }: StationModalProps) {
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
    <div className="fixed inset-0 bg-background/80 backdrop-blur-sm flex items-center justify-center p-4 z-50">
      <div className="bg-card rounded-lg max-w-md w-full p-6 border border-border shadow-lg">
        <h2 className="text-lg font-medium mb-4 text-card-foreground">
          {station ? "Edit Station" : "Create Station"}
        </h2>
        <form onSubmit={handleSubmit} className="space-y-4">
          <div>
            <label className="block text-sm font-medium text-card-foreground mb-1">
              Name
            </label>
            <input
              type="text"
              required
              value={formData.name}
              onChange={(e) =>
                setFormData({ ...formData, name: e.target.value })
              }
              className="w-full px-3 py-2 bg-input border border-border rounded-md focus:outline-none focus:ring-2 focus:ring-primary text-foreground transition-colors duration-200"
            />
          </div>
          <div>
            <label className="block text-sm font-medium text-card-foreground mb-1">
              Address
            </label>
            <input
              type="text"
              required
              value={formData.address}
              onChange={(e) =>
                setFormData({ ...formData, address: e.target.value })
              }
              className="w-full px-3 py-2 bg-input border border-border rounded-md focus:outline-none focus:ring-2 focus:ring-primary text-foreground transition-colors duration-200"
            />
          </div>
          <div className="grid grid-cols-2 gap-4">
            <div>
              <label className="block text-sm font-medium text-card-foreground mb-1">
                Latitude
              </label>
              <input
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
                className="w-full px-3 py-2 bg-input border border-border rounded-md focus:outline-none focus:ring-2 focus:ring-primary text-foreground transition-colors duration-200"
              />
            </div>
            <div>
              <label className="block text-sm font-medium text-card-foreground mb-1">
                Longitude
              </label>
              <input
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
                className="w-full px-3 py-2 bg-input border border-border rounded-md focus:outline-none focus:ring-2 focus:ring-primary text-foreground transition-colors duration-200"
              />
            </div>
          </div>
          <div className="flex justify-end space-x-3 pt-4">
            <button
              type="button"
              onClick={onClose}
              className="px-4 py-2 text-sm font-medium text-muted-foreground bg-secondary rounded-md hover:bg-secondary/80 transition-colors duration-200">
              Cancel
            </button>
            <button
              type="submit"
              className="px-4 py-2 text-sm font-medium text-primary-foreground bg-primary rounded-md hover:bg-primary/90 transition-colors duration-200">
              {station ? "Update" : "Create"}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}
