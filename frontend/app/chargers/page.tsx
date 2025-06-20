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
  }, [currentPage, searchTerm, statusFilter, stationFilter]);

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
    } catch (err) {
      setError('Failed to change availability');
      console.error(err);
    }
  };

  const getStatusColor = (status: string) => {
    switch (status) {
      case 'AVAILABLE':
        return 'bg-green-100 text-green-800';
      case 'OCCUPIED':
        return 'bg-blue-100 text-blue-800';
      case 'UNAVAILABLE':
        return 'bg-red-100 text-red-800';
      case 'FAULTED':
        return 'bg-orange-100 text-orange-800';
      default:
        return 'bg-gray-100 text-gray-800';
    }
  };

  if (loading && chargers.length === 0) {
    return <div className="text-center py-8">Loading chargers...</div>;
  }

  return (
    <div className="space-y-6">
      <div className="flex justify-between items-center">
        <h1 className="text-3xl font-bold text-gray-900">Chargers</h1>
        <button
          onClick={() => setShowCreateModal(true)}
          className="bg-blue-600 text-white px-4 py-2 rounded-lg hover:bg-blue-700 focus:outline-none focus:ring-2 focus:ring-blue-500"
        >
          Add Charger
        </button>
      </div>

      {error && (
        <div className="bg-red-50 border border-red-200 text-red-700 px-4 py-3 rounded">
          {error}
        </div>
      )}

      <div className="grid grid-cols-1 md:grid-cols-4 gap-4 mb-6">
        <input
          type="text"
          placeholder="Search chargers..."
          value={searchTerm}
          onChange={(e) => setSearchTerm(e.target.value)}
          className="px-4 py-2 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500"
        />
        <select
          value={statusFilter}
          onChange={(e) => setStatusFilter(e.target.value)}
          className="px-4 py-2 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500"
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
          className="px-4 py-2 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500"
        >
          <option value="">All Stations</option>
          {stations.map((station) => (
            <option key={station.id} value={station.id}>
              {station.name}
            </option>
          ))}
        </select>
      </div>

      <div className="bg-white shadow overflow-hidden sm:rounded-lg">
        <table className="min-w-full divide-y divide-gray-200">
          <thead className="bg-gray-50">
            <tr>
              <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                Name
              </th>
              <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                Charge Point ID
              </th>
              <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                Status
              </th>
              <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                Station
              </th>
              <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                Last Heartbeat
              </th>
              <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                Availability
              </th>
              <th className="px-6 py-3 text-right text-xs font-medium text-gray-500 uppercase tracking-wider">
                Actions
              </th>
            </tr>
          </thead>
          <tbody className="bg-white divide-y divide-gray-200">
            {chargers.map((charger) => {
              const station = stations.find(s => s.id === charger.station_id);
              return (
                <tr key={charger.id} className="hover:bg-gray-50">
                  <td className="px-6 py-4 whitespace-nowrap text-sm font-medium text-gray-900">
                    {charger.name}
                  </td>
                  <td className="px-6 py-4 whitespace-nowrap text-sm text-gray-500 font-mono">
                    {charger.charge_point_string_id}
                  </td>
                  <td className="px-6 py-4 whitespace-nowrap">
                    <span className={`px-2 py-1 text-xs font-medium rounded-full ${getStatusColor(charger.latest_status)}`}>
                      {charger.latest_status}
                    </span>
                  </td>
                  <td className="px-6 py-4 whitespace-nowrap text-sm text-gray-500">
                    {station?.name || 'Unknown'}
                  </td>
                  <td className="px-6 py-4 whitespace-nowrap text-sm text-gray-500">
                    {charger.last_heart_beat_time 
                      ? new Date(charger.last_heart_beat_time).toLocaleString()
                      : 'Never'}
                  </td>
                  <td className="px-6 py-4 whitespace-nowrap">
                    <button
                      onClick={() => handleChangeAvailability(charger.id, charger.latest_status)}
                      className={`relative inline-flex h-6 w-11 items-center rounded-full transition-colors focus:outline-none focus:ring-2 focus:ring-blue-500 focus:ring-offset-2 ${
                        charger.latest_status === 'AVAILABLE' ? 'bg-green-600' : 'bg-gray-200'
                      }`}
                    >
                      <span
                        className={`inline-block h-4 w-4 transform rounded-full bg-white transition-transform ${
                          charger.latest_status === 'AVAILABLE' ? 'translate-x-6' : 'translate-x-1'
                        }`}
                      />
                    </button>
                  </td>
                  <td className="px-6 py-4 whitespace-nowrap text-right text-sm font-medium space-x-2">
                    <button
                      onClick={() => handleDeleteCharger(charger.id)}
                      className="text-red-600 hover:text-red-900"
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

      {totalPages > 1 && (
        <div className="flex justify-center space-x-2 mt-6">
          <button
            onClick={() => setCurrentPage(prev => Math.max(1, prev - 1))}
            disabled={currentPage === 1}
            className="px-3 py-2 text-sm border border-gray-300 rounded disabled:opacity-50"
          >
            Previous
          </button>
          <span className="px-3 py-2 text-sm">
            Page {currentPage} of {totalPages}
          </span>
          <button
            onClick={() => setCurrentPage(prev => Math.min(totalPages, prev + 1))}
            disabled={currentPage === totalPages}
            className="px-3 py-2 text-sm border border-gray-300 rounded disabled:opacity-50"
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

  const updateConnector = (index: number, field: string, value: any) => {
    const newConnectors = [...formData.connectors];
    newConnectors[index] = { ...newConnectors[index], [field]: value };
    setFormData({ ...formData, connectors: newConnectors });
  };

  return (
    <div className="fixed inset-0 bg-gray-600 bg-opacity-50 flex items-center justify-center p-4 z-50">
      <div className="bg-white rounded-lg max-w-2xl w-full p-6 max-h-[90vh] overflow-y-auto">
        <h2 className="text-lg font-medium mb-4">Create Charger</h2>
        <form onSubmit={handleSubmit} className="space-y-4">
          <div className="grid grid-cols-2 gap-4">
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">
                Name *
              </label>
              <input
                type="text"
                required
                value={formData.name}
                onChange={(e) => setFormData({ ...formData, name: e.target.value })}
                className="w-full px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500"
              />
            </div>
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">
                Station *
              </label>
              <select
                required
                value={formData.station_id}
                onChange={(e) => setFormData({ ...formData, station_id: e.target.value })}
                className="w-full px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500"
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
              <label className="block text-sm font-medium text-gray-700 mb-1">
                Model
              </label>
              <input
                type="text"
                value={formData.model}
                onChange={(e) => setFormData({ ...formData, model: e.target.value })}
                className="w-full px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500"
              />
            </div>
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">
                Vendor
              </label>
              <input
                type="text"
                value={formData.vendor}
                onChange={(e) => setFormData({ ...formData, vendor: e.target.value })}
                className="w-full px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500"
              />
            </div>
          </div>

          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">
              Serial Number
            </label>
            <input
              type="text"
              value={formData.serial_number}
              onChange={(e) => setFormData({ ...formData, serial_number: e.target.value })}
              className="w-full px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500"
            />
          </div>

          <div>
            <div className="flex justify-between items-center mb-2">
              <label className="block text-sm font-medium text-gray-700">
                Connectors
              </label>
              <button
                type="button"
                onClick={addConnector}
                className="text-blue-600 hover:text-blue-800 text-sm"
              >
                + Add Connector
              </button>
            </div>
            {formData.connectors.map((connector, index) => (
              <div key={index} className="border border-gray-200 rounded p-3 mb-2">
                <div className="flex justify-between items-center mb-2">
                  <span className="text-sm font-medium">Connector {index + 1}</span>
                  {formData.connectors.length > 1 && (
                    <button
                      type="button"
                      onClick={() => removeConnector(index)}
                      className="text-red-600 hover:text-red-800 text-sm"
                    >
                      Remove
                    </button>
                  )}
                </div>
                <div className="grid grid-cols-3 gap-2">
                  <div>
                    <label className="block text-xs text-gray-600 mb-1">ID</label>
                    <input
                      type="number"
                      value={connector.connector_id}
                      onChange={(e) => updateConnector(index, 'connector_id', parseInt(e.target.value))}
                      className="w-full px-2 py-1 text-sm border border-gray-300 rounded"
                    />
                  </div>
                  <div>
                    <label className="block text-xs text-gray-600 mb-1">Type</label>
                    <select
                      value={connector.connector_type}
                      onChange={(e) => updateConnector(index, 'connector_type', e.target.value)}
                      className="w-full px-2 py-1 text-sm border border-gray-300 rounded"
                    >
                      <option value="Type2">Type 2</option>
                      <option value="CCS">CCS</option>
                      <option value="CHAdeMO">CHAdeMO</option>
                    </select>
                  </div>
                  <div>
                    <label className="block text-xs text-gray-600 mb-1">Power (kW)</label>
                    <input
                      type="number"
                      value={connector.max_power_kw}
                      onChange={(e) => updateConnector(index, 'max_power_kw', parseFloat(e.target.value))}
                      className="w-full px-2 py-1 text-sm border border-gray-300 rounded"
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
              className="px-4 py-2 text-sm font-medium text-gray-700 bg-gray-100 rounded-md hover:bg-gray-200"
            >
              Cancel
            </button>
            <button
              type="submit"
              className="px-4 py-2 text-sm font-medium text-white bg-blue-600 rounded-md hover:bg-blue-700"
            >
              Create
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}