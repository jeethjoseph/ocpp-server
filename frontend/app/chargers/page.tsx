'use client';

import { useState, useEffect } from 'react';
import { Charger, ChargerCreate, Station } from '@/types/api';
import { chargerService, stationService } from '@/lib/api-services';

export default function ChargersPage() {
  const [chargers, setChargers] = useState<Charger[]>([]);
  const [stations, setStations] = useState<Station[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [showCreateModal, setShowCreateModal] = useState(false);
  const [searchTerm, setSearchTerm] = useState('');
  const [statusFilter, setStatusFilter] = useState('');
  const [stationFilter, setStationFilter] = useState('');
  const [currentPage, setCurrentPage] = useState(1);
  const [totalPages, setTotalPages] = useState(1);

  const loadChargers = async () => {
    try {
      setLoading(true);
      const response = await chargerService.getAll({
        page: currentPage,
        limit: 10,
        search: searchTerm || undefined,
        status: statusFilter || undefined,
        station_id: stationFilter ? parseInt(stationFilter) : undefined,
      });
      setChargers(response.data);
      setTotalPages(Math.ceil(response.total / 10));
    } catch (err) {
      setError('Failed to load chargers');
      console.error(err);
    } finally {
      setLoading(false);
    }
  };

  const loadStations = async () => {
    try {
      const response = await stationService.getAll({ limit: 100 });
      setStations(response.data);
    } catch (err) {
      console.error('Failed to load stations:', err);
    }
  };

  useEffect(() => {
    loadStations();
  }, []);

  useEffect(() => {
    loadChargers();
  }, [currentPage, searchTerm, statusFilter, stationFilter]); // eslint-disable-line react-hooks/exhaustive-deps

  const handleCreateCharger = async (data: ChargerCreate) => {
    try {
      await chargerService.create(data);
      setShowCreateModal(false);
      loadChargers();
    } catch (err) {
      setError('Failed to create charger');
      console.error(err);
    }
  };

  const handleDeleteCharger = async (id: number) => {
    if (!confirm('Are you sure you want to delete this charger?')) return;
    
    try {
      await chargerService.delete(id);
      loadChargers();
    } catch (err) {
      setError('Failed to delete charger');
      console.error(err);
    }
  };

  const handleChangeAvailability = async (chargerId: number, currentStatus: string) => {
    try {
      const newType = currentStatus === 'AVAILABLE' ? 'Inoperative' : 'Operative';
      await chargerService.changeAvailability(chargerId, newType, 0);
      loadChargers();
    } catch (err: unknown) {
      const errorMessage = err instanceof Error ? err.message : String(err);
      if (errorMessage.includes('409') || errorMessage.includes('not connected')) {
        setError('Cannot change availability: Charger is not connected. Please ensure the charger is online and try again.');
      } else {
        setError('Failed to change availability: ' + errorMessage);
      }
      console.error(err);
    }
  };

  const getStatusColor = (status: string) => {
    switch (status) {
      case 'AVAILABLE':
        return 'bg-green-100 text-green-800 dark:bg-green-900/20 dark:text-green-400';
      case 'OCCUPIED':
        return 'bg-blue-100 text-blue-800 dark:bg-blue-900/20 dark:text-blue-400';
      case 'UNAVAILABLE':
        return 'bg-destructive/10 text-destructive';
      case 'FAULTED':
        return 'bg-orange-100 text-orange-800 dark:bg-orange-900/20 dark:text-orange-400';
      default:
        return 'bg-muted text-muted-foreground';
    }
  };

  const getConnectionStatusColor = (connected: boolean) => {
    return connected 
      ? 'bg-green-100 text-green-800 dark:bg-green-900/20 dark:text-green-400'
      : 'bg-red-100 text-red-800 dark:bg-red-900/20 dark:text-red-400';
  };

  if (loading && chargers.length === 0) {
    return <div className="text-center py-8 text-muted-foreground">Loading chargers...</div>;
  }

  return (
    <div className="space-y-6">
      <div className="flex justify-between items-center">
        <h1 className="text-3xl font-bold text-foreground">Chargers</h1>
        <button
          onClick={() => setShowCreateModal(true)}
          className="bg-primary text-primary-foreground px-4 py-2 rounded-lg hover:bg-primary/90 focus:outline-none focus:ring-2 focus:ring-primary focus:ring-offset-2 transition-colors"
        >
          Add Charger
        </button>
      </div>

      {error && (
        <div className="bg-destructive/10 border border-destructive/20 text-destructive px-4 py-3 rounded">
          {error}
        </div>
      )}

      <div className="grid grid-cols-1 md:grid-cols-4 gap-4 mb-6">
        <input
          type="text"
          placeholder="Search chargers..."
          value={searchTerm}
          onChange={(e) => setSearchTerm(e.target.value)}
          className="px-4 py-2 border border-border bg-input text-foreground rounded-lg focus:outline-none focus:ring-2 focus:ring-primary focus:ring-offset-2 transition-colors"
        />
        <select
          value={statusFilter}
          onChange={(e) => setStatusFilter(e.target.value)}
          className="px-4 py-2 border border-border bg-input text-foreground rounded-lg focus:outline-none focus:ring-2 focus:ring-primary focus:ring-offset-2 transition-colors"
        >
          <option value="">All Statuses</option>
          <option value="AVAILABLE">Available</option>
          <option value="OCCUPIED">Occupied</option>
          <option value="UNAVAILABLE">Unavailable</option>
          <option value="FAULTED">Faulted</option>
        </select>
        <select
          value={stationFilter}
          onChange={(e) => setStationFilter(e.target.value)}
          className="px-4 py-2 border border-border bg-input text-foreground rounded-lg focus:outline-none focus:ring-2 focus:ring-primary focus:ring-offset-2 transition-colors"
        >
          <option value="">All Stations</option>
          {stations.map((station) => (
            <option key={station.id} value={station.id}>
              {station.name}
            </option>
          ))}
        </select>
      </div>

      <div className="bg-card shadow-md border border-border overflow-hidden sm:rounded-lg">
        <div className="overflow-x-auto">
          <table className="w-full min-w-[800px] divide-y divide-border">
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
              const station = stations.find(s => s.id === charger.station_id);
              return (
                <tr key={charger.id} className="hover:bg-accent/50 transition-colors">
                  <td className="px-6 py-4 whitespace-nowrap text-sm font-medium text-card-foreground">
                    {charger.name}
                  </td>
                  <td className="px-6 py-4 whitespace-nowrap text-sm text-muted-foreground font-mono">
                    {charger.charge_point_string_id}
                  </td>
                  <td className="px-6 py-4 whitespace-nowrap">
                    <span className={`px-2 py-1 text-xs font-medium rounded-full ${getStatusColor(charger.latest_status)}`}>
                      {charger.latest_status}
                    </span>
                  </td>
                  <td className="px-6 py-4 whitespace-nowrap">
                    <span className={`px-2 py-1 text-xs font-medium rounded-full ${getConnectionStatusColor(charger.connection_status)}`}>
                      {charger.connection_status ? 'Connected' : 'Disconnected'}
                    </span>
                  </td>
                  <td className="px-6 py-4 whitespace-nowrap text-sm text-muted-foreground">
                    {station?.name || 'Unknown'}
                  </td>
                  <td className="px-6 py-4 whitespace-nowrap text-sm text-muted-foreground">
                    {charger.last_heart_beat_time 
                      ? new Date(charger.last_heart_beat_time).toLocaleString()
                      : 'Never'}
                  </td>
                  <td className="px-6 py-4 whitespace-nowrap">
                    <button
                      onClick={() => handleChangeAvailability(charger.id, charger.latest_status)}
                      className={`relative inline-flex h-6 w-11 items-center rounded-full transition-colors focus:outline-none focus:ring-2 focus:ring-primary focus:ring-offset-2 ${
                        charger.latest_status === 'AVAILABLE' ? 'bg-green-600' : 'bg-muted'
                      }`}
                      title="Toggle charger availability"
                    >
                      <span
                        className={`inline-block h-4 w-4 transform rounded-full bg-background transition-transform ${
                          charger.latest_status === 'AVAILABLE' ? 'translate-x-6' : 'translate-x-1'
                        }`}
                      />
                    </button>
                  </td>
                  <td className="px-6 py-4 whitespace-nowrap text-right text-sm font-medium space-x-2">
                    <button
                      onClick={() => handleDeleteCharger(charger.id)}
                      className="text-destructive hover:text-destructive/80 transition-colors"
                    >
                      Delete
                    </button>
                  </td>
                </tr>
              );
            })}
            </tbody>
          </table>
        </div>
      </div>

      {totalPages > 1 && (
        <div className="flex justify-center space-x-2 mt-6">
          <button
            onClick={() => setCurrentPage(prev => Math.max(1, prev - 1))}
            disabled={currentPage === 1}
            className="px-3 py-2 text-sm border border-border bg-background text-foreground rounded disabled:opacity-50 hover:bg-accent hover:text-accent-foreground transition-colors"
          >
            Previous
          </button>
          <span className="px-3 py-2 text-sm text-muted-foreground">
            Page {currentPage} of {totalPages}
          </span>
          <button
            onClick={() => setCurrentPage(prev => Math.min(totalPages, prev + 1))}
            disabled={currentPage === totalPages}
            className="px-3 py-2 text-sm border border-border bg-background text-foreground rounded disabled:opacity-50 hover:bg-accent hover:text-accent-foreground transition-colors"
          >
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
  );
}

interface ChargerModalProps {
  stations: Station[];
  onSubmit: (data: ChargerCreate) => void;
  onClose: () => void;
}

function ChargerModal({ stations, onSubmit, onClose }: ChargerModalProps) {
  const [formData, setFormData] = useState({
    name: '',
    station_id: '',
    model: '',
    vendor: '',
    serial_number: '',
    connectors: [{ connector_id: 1, connector_type: 'Type2', max_power_kw: 22 }],
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
        { connector_id: formData.connectors.length + 1, connector_type: 'Type2', max_power_kw: 22 }
      ]
    });
  };

  const removeConnector = (index: number) => {
    setFormData({
      ...formData,
      connectors: formData.connectors.filter((_, i) => i !== index)
    });
  };

  const updateConnector = (index: number, field: string, value: string | number) => {
    const newConnectors = [...formData.connectors];
    newConnectors[index] = { ...newConnectors[index], [field]: value };
    setFormData({ ...formData, connectors: newConnectors });
  };

  return (
    <div className="fixed inset-0 bg-background/80 backdrop-blur-sm flex items-center justify-center p-4 z-50">
      <div className="bg-card rounded-lg max-w-2xl w-full p-6 max-h-[90vh] overflow-y-auto border border-border shadow-lg">
        <h2 className="text-lg font-medium mb-4 text-card-foreground">Create Charger</h2>
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
                onChange={(e) => setFormData({ ...formData, name: e.target.value })}
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
                onChange={(e) => setFormData({ ...formData, station_id: e.target.value })}
                className="w-full px-3 py-2 border border-border bg-input text-foreground rounded-md focus:outline-none focus:ring-2 focus:ring-primary focus:ring-offset-2 transition-colors"
              >
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
                onChange={(e) => setFormData({ ...formData, model: e.target.value })}
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
                onChange={(e) => setFormData({ ...formData, vendor: e.target.value })}
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
              onChange={(e) => setFormData({ ...formData, serial_number: e.target.value })}
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
                className="text-primary hover:text-primary/80 text-sm transition-colors"
              >
                + Add Connector
              </button>
            </div>
            {formData.connectors.map((connector, index) => (
              <div key={index} className="border border-border rounded p-3 mb-2 bg-muted/30">
                <div className="flex justify-between items-center mb-2">
                  <span className="text-sm font-medium text-card-foreground">Connector {index + 1}</span>
                  {formData.connectors.length > 1 && (
                    <button
                      type="button"
                      onClick={() => removeConnector(index)}
                      className="text-destructive hover:text-destructive/80 text-sm transition-colors"
                    >
                      Remove
                    </button>
                  )}
                </div>
                <div className="grid grid-cols-3 gap-2">
                  <div>
                    <label className="block text-xs text-muted-foreground mb-1">ID</label>
                    <input
                      type="number"
                      value={connector.connector_id}
                      onChange={(e) => updateConnector(index, 'connector_id', parseInt(e.target.value))}
                      className="w-full px-2 py-1 text-sm border border-border bg-input text-foreground rounded focus:outline-none focus:ring-1 focus:ring-primary transition-colors"
                    />
                  </div>
                  <div>
                    <label className="block text-xs text-muted-foreground mb-1">Type</label>
                    <select
                      value={connector.connector_type}
                      onChange={(e) => updateConnector(index, 'connector_type', e.target.value)}
                      className="w-full px-2 py-1 text-sm border border-border bg-input text-foreground rounded focus:outline-none focus:ring-1 focus:ring-primary transition-colors"
                    >
                      <option value="Type2">Type 2</option>
                      <option value="CCS">CCS</option>
                      <option value="CHAdeMO">CHAdeMO</option>
                    </select>
                  </div>
                  <div>
                    <label className="block text-xs text-muted-foreground mb-1">Power (kW)</label>
                    <input
                      type="number"
                      value={connector.max_power_kw}
                      onChange={(e) => updateConnector(index, 'max_power_kw', parseFloat(e.target.value))}
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
              className="px-4 py-2 text-sm font-medium text-secondary-foreground bg-secondary rounded-md hover:bg-secondary/80 transition-colors"
            >
              Cancel
            </button>
            <button
              type="submit"
              className="px-4 py-2 text-sm font-medium text-primary-foreground bg-primary rounded-md hover:bg-primary/90 transition-colors"
            >
              Create
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}