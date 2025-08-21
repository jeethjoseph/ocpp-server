"use client";

import { useState } from "react";
import { Zap, Plus, ExternalLink } from "lucide-react";
import Link from "next/link";

import { AdminOnly } from "@/components/RoleWrapper";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Table } from "@/components/ui/table";

import { ChargerCreate, Station } from "@/types/api";
import { 
  useChargers, 
  useStations, 
  useChangeAvailability, 
  useDeleteCharger 
} from "@/lib/queries/chargers";

export default function AdminChargersPage() {
  const [showCreateModal, setShowCreateModal] = useState(false);
  const [searchTerm, setSearchTerm] = useState("");
  const [statusFilter, setStatusFilter] = useState("");
  const [stationFilter, setStationFilter] = useState("");
  const [currentPage, setCurrentPage] = useState(1);

  // TanStack Query hooks
  const {
    data: chargersData,
    isLoading: loadingChargers,
    error: chargersError,
  } = useChargers({
    page: currentPage,
    limit: 10,
    search: searchTerm || undefined,
    status: statusFilter || undefined,
    station_id: stationFilter ? parseInt(stationFilter) : undefined,
  });

  const {
    data: stationsData,
    isLoading: loadingStations,
  } = useStations({ limit: 100 });

  const changeAvailabilityMutation = useChangeAvailability();
  const deleteChargerMutation = useDeleteCharger();
  
  // Track loading state per charger
  const [toggleLoadingChargers, setToggleLoadingChargers] = useState<Set<number>>(new Set());

  // Extract data from queries
  const chargers = chargersData?.data || [];
  const stations = stationsData?.data || [];
  const totalPages = chargersData ? Math.ceil(chargersData.total / 10) : 1;
  const loading = loadingChargers || loadingStations;
  const error = chargersError ? "Failed to load chargers" : null;

  const handleCreateCharger = async (chargerData: ChargerCreate) => {
    // TODO: Add mutation for create charger
    console.log('Creating charger:', chargerData);
    setShowCreateModal(false);
  };

  const handleDeleteCharger = async (id: number) => {
    if (!confirm("Are you sure you want to delete this charger?")) return;
    deleteChargerMutation.mutate(id);
  };

  const canChangeAvailability = (status: string) => {
    // Only allow availability changes for Available and Unavailable statuses
    return status === "Available" || status === "Unavailable";
  };

  const getAvailabilityToggleState = (status: string) => {
    // Green/ON for Available, Gray/OFF for all others
    return status === "Available";
  };

  const handleChangeAvailability = async (
    chargerId: number,
    currentStatus: string
  ) => {
    // OCPP 1.6 compliant logic: only allow toggle between Available <-> Unavailable
    let newType: "Inoperative" | "Operative" | null = null;
    
    if (currentStatus === "Available") {
      newType = "Inoperative"; // Available -> Unavailable
    } else if (currentStatus === "Unavailable") {
      newType = "Operative"; // Unavailable -> Available
    }
    
    // Don't proceed if status change isn't allowed
    if (!newType) {
      console.warn(`Cannot change availability for charger with status: ${currentStatus}`);
      return;
    }
    
    // Add charger to loading set
    setToggleLoadingChargers(prev => new Set(prev).add(chargerId));
    
    changeAvailabilityMutation.mutate(
      { id: chargerId, type: newType, connectorId: 0 },
      {
        onSettled: () => {
          // Remove charger from loading set when done (success or error)
          setToggleLoadingChargers(prev => {
            const newSet = new Set(prev);
            newSet.delete(chargerId);
            return newSet;
          });
        }
      }
    );
  };

  const getStatusColor = (status: string) => {
    switch (status) {
      case "Available":
        return "bg-green-100 text-green-800 dark:bg-green-900/20 dark:text-green-400";
      case "Preparing":
        return "bg-yellow-100 text-yellow-800 dark:bg-yellow-900/20 dark:text-yellow-400";
      case "Charging":
        return "bg-blue-100 text-blue-800 dark:bg-blue-900/20 dark:text-blue-400";
      case "SuspendedEVSE":
        return "bg-orange-100 text-orange-800 dark:bg-orange-900/20 dark:text-orange-400";
      case "SuspendedEV":
        return "bg-orange-100 text-orange-800 dark:bg-orange-900/20 dark:text-orange-400";
      case "Finishing":
        return "bg-purple-100 text-purple-800 dark:bg-purple-900/20 dark:text-purple-400";
      case "Reserved":
        return "bg-indigo-100 text-indigo-800 dark:bg-indigo-900/20 dark:text-indigo-400";
      case "Unavailable":
        return "bg-red-100 text-red-800 dark:bg-red-900/20 dark:text-red-400";
      case "Faulted":
        return "bg-destructive/10 text-destructive";
      default:
        return "bg-muted text-muted-foreground";
    }
  };

  const getConnectionStatusColor = (connected: boolean) => {
    return connected
      ? "bg-green-100 text-green-800 dark:bg-green-900/20 dark:text-green-400"
      : "bg-red-100 text-red-800 dark:bg-red-900/20 dark:text-red-400";
  };

  return (
    <AdminOnly fallback={
      <div className="flex items-center justify-center min-h-[400px]">
        <div className="text-center">
          <h2 className="text-2xl font-bold text-gray-900 mb-2">Access Denied</h2>
          <p className="text-gray-600 mb-4">You need administrator privileges to manage chargers.</p>
          <Link href="/" className="text-blue-600 hover:text-blue-800">
            Go to Dashboard →
          </Link>
        </div>
      </div>
    }>
      {loading ? (
        <div className="flex items-center justify-center py-8">
          <div className="text-center">
            <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-primary mx-auto"></div>
            <p className="text-muted-foreground mt-2">Loading chargers...</p>
          </div>
        </div>
      ) : error ? (
        <div className="text-center py-8">
          <p className="text-destructive">Failed to load chargers</p>
          <p className="text-muted-foreground text-sm mt-1">Please try refreshing the page</p>
        </div>
      ) : (
        <div className="space-y-6">
          <div className="flex justify-between items-center">
            <div>
              <h1 className="text-3xl font-bold">Charger Management</h1>
              <p className="text-muted-foreground">Manage your charging devices</p>
            </div>
            <Button onClick={() => setShowCreateModal(true)}>
              <Plus className="h-4 w-4 mr-2" />
              Add Charger
            </Button>
          </div>

          <Card>
            <CardHeader>
              <CardTitle className="flex items-center gap-2">
                <Zap className="h-5 w-5" />
                Chargers
              </CardTitle>
            </CardHeader>
            <CardContent>
              <div className="grid grid-cols-1 md:grid-cols-4 gap-4 mb-6">
                <Input
                  placeholder="Search chargers..."
                  value={searchTerm}
                  onChange={(e) => setSearchTerm(e.target.value)}
                />
                <select
                  value={statusFilter}
                  onChange={(e) => setStatusFilter(e.target.value)}
                  className="px-4 py-2 border border-border bg-input text-foreground rounded-lg focus:outline-none focus:ring-2 focus:ring-primary focus:ring-offset-2 transition-colors">
                  <option value="">All Statuses</option>
                  <option value="Available">Available</option>
                  <option value="Preparing">Preparing</option>
                  <option value="Charging">Charging</option>
                  <option value="SuspendedEVSE">Suspended EVSE</option>
                  <option value="SuspendedEV">Suspended EV</option>
                  <option value="Finishing">Finishing</option>
                  <option value="Reserved">Reserved</option>
                  <option value="Unavailable">Unavailable</option>
                  <option value="Faulted">Faulted</option>
                </select>
                <select
                  value={stationFilter}
                  onChange={(e) => setStationFilter(e.target.value)}
                  className="px-4 py-2 border border-border bg-input text-foreground rounded-lg focus:outline-none focus:ring-2 focus:ring-primary focus:ring-offset-2 transition-colors">
                  <option value="">All Stations</option>
                  {stations.map((station) => (
                    <option key={station.id} value={station.id}>
                      {station.name}
                    </option>
                  ))}
                </select>
              </div>

              <Table>
                <thead className="bg-muted">
                  <tr>
                    <th className="px-6 py-3 text-left text-xs font-medium text-muted-foreground uppercase tracking-wider whitespace-nowrap">
                      Name
                    </th>
                    <th className="px-6 py-3 text-left text-xs font-medium text-muted-foreground uppercase tracking-wider whitespace-nowrap">
                      Charge Point ID
                    </th>
                    <th className="px-6 py-3 text-left text-xs font-medium text-muted-foreground uppercase tracking-wider whitespace-nowrap">
                      Status
                    </th>
                    <th className="px-6 py-3 text-left text-xs font-medium text-muted-foreground uppercase tracking-wider whitespace-nowrap">
                      Connection
                    </th>
                    <th className="px-6 py-3 text-left text-xs font-medium text-muted-foreground uppercase tracking-wider whitespace-nowrap">
                      Station
                    </th>
                    <th className="px-6 py-3 text-left text-xs font-medium text-muted-foreground uppercase tracking-wider whitespace-nowrap">
                      Last Heartbeat
                    </th>
                    <th className="px-6 py-3 text-left text-xs font-medium text-muted-foreground uppercase tracking-wider whitespace-nowrap">
                      Availability
                    </th>
                    <th className="px-6 py-3 text-right text-xs font-medium text-muted-foreground uppercase tracking-wider whitespace-nowrap">
                      Actions
                    </th>
                  </tr>
                </thead>
                <tbody className="bg-card divide-y divide-border">
                  {chargers.map((charger) => {
                    const station = stations.find(
                      (s) => s.id === charger.station_id
                    );
                    return (
                      <tr
                        key={charger.id}
                        className="hover:bg-accent/50 transition-colors">
                        <td className="px-6 py-4 whitespace-nowrap text-sm font-medium text-card-foreground">
                          {charger.name}
                        </td>
                        <td className="px-6 py-4 whitespace-nowrap text-sm text-muted-foreground font-mono">
                          {charger.charge_point_string_id}
                        </td>
                        <td className="px-6 py-4 whitespace-nowrap">
                          <span
                            className={`px-2 py-1 text-xs font-medium rounded-full ${getStatusColor(
                              charger.latest_status
                            )}`}>
                            {charger.latest_status}
                          </span>
                        </td>
                        <td className="px-6 py-4 whitespace-nowrap">
                          <span
                            className={`px-2 py-1 text-xs font-medium rounded-full ${getConnectionStatusColor(
                              charger.connection_status
                            )}`}>
                            {charger.connection_status
                              ? "Connected"
                              : "Disconnected"}
                          </span>
                        </td>
                        <td className="px-6 py-4 whitespace-nowrap text-sm text-muted-foreground">
                          {station?.name || "Unknown"}
                        </td>
                        <td className="px-6 py-4 whitespace-nowrap text-sm text-muted-foreground">
                          {charger.last_heart_beat_time
                            ? new Date(
                                charger.last_heart_beat_time
                              ).toLocaleString()
                            : "Never"}
                        </td>
                        <td className="px-6 py-4 whitespace-nowrap">
                          <button
                            onClick={() =>
                              handleChangeAvailability(
                                charger.id,
                                charger.latest_status
                              )
                            }
                            disabled={
                              toggleLoadingChargers.has(charger.id) ||
                              !canChangeAvailability(charger.latest_status)
                            }
                            className={`relative inline-flex h-6 w-11 items-center rounded-full transition-colors focus:outline-none focus:ring-2 focus:ring-primary focus:ring-offset-2 disabled:opacity-50 disabled:cursor-not-allowed ${
                              getAvailabilityToggleState(charger.latest_status)
                                ? "bg-green-600"
                                : "bg-muted"
                            }`}
                            title={
                              toggleLoadingChargers.has(charger.id)
                                ? "Changing availability..."
                                : !canChangeAvailability(charger.latest_status)
                                ? `Cannot toggle availability for ${charger.latest_status} status`
                                : "Toggle charger availability (Available ↔ Unavailable)"
                            }>
                            {toggleLoadingChargers.has(charger.id) ? (
                              <div className="inline-block h-4 w-4 animate-spin rounded-full border-2 border-background border-t-transparent mx-auto" />
                            ) : (
                              <span
                                className={`inline-block h-4 w-4 transform rounded-full bg-background transition-transform ${
                                  getAvailabilityToggleState(charger.latest_status)
                                    ? "translate-x-6"
                                    : "translate-x-1"
                                }`}
                              />
                            )}
                          </button>
                        </td>
                        <td className="px-6 py-4 whitespace-nowrap text-right text-sm font-medium space-x-2">
                          <Link
                            href={`/admin/chargers/${charger.id}`}
                            className="text-primary hover:text-primary/80 transition-colors">
                            <ExternalLink className="h-4 w-4 inline mr-1" />
                            View
                          </Link>
                          <button
                            onClick={() => handleDeleteCharger(charger.id)}
                            className="text-destructive hover:text-destructive/80 transition-colors ml-2">
                            Delete
                          </button>
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </Table>
            </CardContent>
          </Card>

          {totalPages > 1 && (
            <div className="flex justify-center space-x-2 mt-6">
              <button
                onClick={() => setCurrentPage((prev) => Math.max(1, prev - 1))}
                disabled={currentPage === 1}
                className="px-3 py-2 text-sm border border-border bg-background text-foreground rounded disabled:opacity-50 hover:bg-accent hover:text-accent-foreground transition-colors">
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
                className="px-3 py-2 text-sm border border-border bg-background text-foreground rounded disabled:opacity-50 hover:bg-accent hover:text-accent-foreground transition-colors">
                Next
              </button>
            </div>
          )}

          {showCreateModal && (
            <ChargerModal
              stations={stations}
              onSubmit={handleCreateCharger}
              onClose={() => setShowCreateModal(false)}
            />
          )}
        </div>
      )}
    </AdminOnly>
  );
}

interface ChargerModalProps {
  stations: Station[];
  onSubmit: (data: ChargerCreate) => void;
  onClose: () => void;
}

function ChargerModal({ stations, onSubmit, onClose }: ChargerModalProps) {
  const [formData, setFormData] = useState({
    name: "",
    station_id: "",
    model: "",
    vendor: "",
    serial_number: "",
    connectors: [
      { connector_id: 1, connector_type: "Type2", max_power_kw: 22 },
    ],
  });

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    onSubmit({
      ...formData,
      station_id: parseInt(formData.station_id),
      model: formData.model || undefined,
      vendor: formData.vendor || undefined,
      serial_number: formData.serial_number || undefined,
    });
  };

  const addConnector = () => {
    setFormData({
      ...formData,
      connectors: [
        ...formData.connectors,
        {
          connector_id: formData.connectors.length + 1,
          connector_type: "Type2",
          max_power_kw: 22,
        },
      ],
    });
  };

  const removeConnector = (index: number) => {
    setFormData({
      ...formData,
      connectors: formData.connectors.filter((_, i) => i !== index),
    });
  };

  const updateConnector = (
    index: number,
    field: string,
    value: string | number
  ) => {
    const newConnectors = [...formData.connectors];
    newConnectors[index] = { ...newConnectors[index], [field]: value };
    setFormData({ ...formData, connectors: newConnectors });
  };

  return (
    <div className="fixed inset-0 bg-background/80 backdrop-blur-sm flex items-center justify-center p-4 z-50">
      <div className="bg-card rounded-lg max-w-2xl w-full p-6 max-h-[90vh] overflow-y-auto border border-border shadow-lg">
        <h2 className="text-lg font-medium mb-4 text-card-foreground">
          Create Charger
        </h2>
        <form onSubmit={handleSubmit} className="space-y-4">
          <div className="grid grid-cols-2 gap-4">
            <div>
              <label className="block text-sm font-medium text-card-foreground mb-1">
                Name *
              </label>
              <input
                type="text"
                required
                value={formData.name}
                onChange={(e) =>
                  setFormData({ ...formData, name: e.target.value })
                }
                className="w-full px-3 py-2 border border-border bg-input text-foreground rounded-md focus:outline-none focus:ring-2 focus:ring-primary focus:ring-offset-2 transition-colors"
              />
            </div>
            <div>
              <label className="block text-sm font-medium text-card-foreground mb-1">
                Station *
              </label>
              <select
                required
                value={formData.station_id}
                onChange={(e) =>
                  setFormData({ ...formData, station_id: e.target.value })
                }
                className="w-full px-3 py-2 border border-border bg-input text-foreground rounded-md focus:outline-none focus:ring-2 focus:ring-primary focus:ring-offset-2 transition-colors">
                <option value="">Select Station</option>
                {stations.map((station) => (
                  <option key={station.id} value={station.id}>
                    {station.name}
                  </option>
                ))}
              </select>
            </div>
          </div>

          <div className="grid grid-cols-2 gap-4">
            <div>
              <label className="block text-sm font-medium text-card-foreground mb-1">
                Model
              </label>
              <input
                type="text"
                value={formData.model}
                onChange={(e) =>
                  setFormData({ ...formData, model: e.target.value })
                }
                className="w-full px-3 py-2 border border-border bg-input text-foreground rounded-md focus:outline-none focus:ring-2 focus:ring-primary focus:ring-offset-2 transition-colors"
              />
            </div>
            <div>
              <label className="block text-sm font-medium text-card-foreground mb-1">
                Vendor
              </label>
              <input
                type="text"
                value={formData.vendor}
                onChange={(e) =>
                  setFormData({ ...formData, vendor: e.target.value })
                }
                className="w-full px-3 py-2 border border-border bg-input text-foreground rounded-md focus:outline-none focus:ring-2 focus:ring-primary focus:ring-offset-2 transition-colors"
              />
            </div>
          </div>

          <div>
            <label className="block text-sm font-medium text-card-foreground mb-1">
              Serial Number
            </label>
            <input
              type="text"
              value={formData.serial_number}
              onChange={(e) =>
                setFormData({ ...formData, serial_number: e.target.value })
              }
              className="w-full px-3 py-2 border border-border bg-input text-foreground rounded-md focus:outline-none focus:ring-2 focus:ring-primary focus:ring-offset-2 transition-colors"
            />
          </div>

          <div>
            <div className="flex justify-between items-center mb-2">
              <label className="block text-sm font-medium text-card-foreground">
                Connectors
              </label>
              <button
                type="button"
                onClick={addConnector}
                className="text-primary hover:text-primary/80 text-sm transition-colors">
                + Add Connector
              </button>
            </div>
            {formData.connectors.map((connector, index) => (
              <div
                key={index}
                className="border border-border rounded p-3 mb-2 bg-muted/30">
                <div className="flex justify-between items-center mb-2">
                  <span className="text-sm font-medium text-card-foreground">
                    Connector {index + 1}
                  </span>
                  {formData.connectors.length > 1 && (
                    <button
                      type="button"
                      onClick={() => removeConnector(index)}
                      className="text-destructive hover:text-destructive/80 text-sm transition-colors">
                      Remove
                    </button>
                  )}
                </div>
                <div className="grid grid-cols-3 gap-2">
                  <div>
                    <label className="block text-xs text-muted-foreground mb-1">
                      ID
                    </label>
                    <input
                      type="number"
                      value={connector.connector_id}
                      onChange={(e) =>
                        updateConnector(
                          index,
                          "connector_id",
                          parseInt(e.target.value)
                        )
                      }
                      className="w-full px-2 py-1 text-sm border border-border bg-input text-foreground rounded focus:outline-none focus:ring-1 focus:ring-primary transition-colors"
                    />
                  </div>
                  <div>
                    <label className="block text-xs text-muted-foreground mb-1">
                      Type
                    </label>
                    <select
                      value={connector.connector_type}
                      onChange={(e) =>
                        updateConnector(index, "connector_type", e.target.value)
                      }
                      className="w-full px-2 py-1 text-sm border border-border bg-input text-foreground rounded focus:outline-none focus:ring-1 focus:ring-primary transition-colors">
                      <option value="Type2">Type 2</option>
                      <option value="CCS">CCS</option>
                      <option value="CHAdeMO">CHAdeMO</option>
                    </select>
                  </div>
                  <div>
                    <label className="block text-xs text-muted-foreground mb-1">
                      Power (kW)
                    </label>
                    <input
                      type="number"
                      value={connector.max_power_kw}
                      onChange={(e) =>
                        updateConnector(
                          index,
                          "max_power_kw",
                          parseFloat(e.target.value)
                        )
                      }
                      className="w-full px-2 py-1 text-sm border border-border bg-input text-foreground rounded focus:outline-none focus:ring-1 focus:ring-primary transition-colors"
                    />
                  </div>
                </div>
              </div>
            ))}
          </div>

          <div className="flex justify-end space-x-3 pt-4">
            <button
              type="button"
              onClick={onClose}
              className="px-4 py-2 text-sm font-medium text-secondary-foreground bg-secondary rounded-md hover:bg-secondary/80 transition-colors">
              Cancel
            </button>
            <button
              type="submit"
              className="px-4 py-2 text-sm font-medium text-primary-foreground bg-primary rounded-md hover:bg-primary/90 transition-colors">
              Create
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}