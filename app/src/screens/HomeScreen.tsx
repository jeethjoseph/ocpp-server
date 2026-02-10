import { useUser } from '@clerk/clerk-react';
import { Zap, MapPin, Clock, ChevronRight } from 'lucide-react';
import { useNavigate } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import { useApi } from '../lib/api-client';
import { userSessionService } from '../lib/api-services';
import { useState, useEffect } from 'react';
import { recentChargersStorage, type RecentCharger } from '../lib/recent-chargers';

export const HomeScreen = () => {
  const { user } = useUser();
  const navigate = useNavigate();
  const api = useApi();

  // Fetch active session only (lightweight endpoint)
  const { data: activeSessionData } = useQuery({
    queryKey: ['active-session'],
    queryFn: () => userSessionService(api).getActiveSession(),
    staleTime: 10 * 1000,
    refetchInterval: (query) => {
      return (query.state.data?.count ?? 0) > 0 ? 5000 : false;
    },
  });

  const activeSessions = activeSessionData?.data ?? [];

  // Live timer for active sessions
  const [now, setNow] = useState(Date.now());
  useEffect(() => {
    if (activeSessions.length === 0) return;
    const interval = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(interval);
  }, [activeSessions.length]);

  const formatDuration = (startTime: string) => {
    const seconds = Math.floor((now - new Date(startTime).getTime()) / 1000);
    if (seconds < 0) return '00:00:00';
    const hours = Math.floor(seconds / 3600);
    const minutes = Math.floor((seconds % 3600) / 60);
    const secs = seconds % 60;
    return `${hours.toString().padStart(2, '0')}:${minutes.toString().padStart(2, '0')}:${secs.toString().padStart(2, '0')}`;
  };

  // Recent chargers from persistent storage
  const [recentChargers, setRecentChargers] = useState<RecentCharger[]>([]);
  useEffect(() => {
    recentChargersStorage.getAll().then(setRecentChargers);
  }, []);

  const quickActions = [
    {
      icon: MapPin,
      label: 'Find Stations',
      description: 'Locate nearby charging stations',
      action: () => navigate('/stations'),
      color: 'bg-blue-500',
    },
    {
      icon: Zap,
      label: 'Scan QR Code',
      description: 'Start charging instantly',
      action: () => navigate('/scanner'),
      color: 'bg-green-500',
    },
    {
      icon: Clock,
      label: 'My Sessions',
      description: 'View charging history',
      action: () => navigate('/sessions'),
      color: 'bg-purple-500',
    },
  ];

  return (
    <div className="p-4 space-y-6">
      {/* Welcome Section */}
      <div className="bg-white rounded-lg p-6 shadow-sm">
        <h2 className="text-2xl font-bold text-gray-900">
          Welcome{user?.firstName ? `, ${user.firstName}` : ''}!
        </h2>
        <p className="text-gray-600 mt-1">
          Ready to charge your electric vehicle?
        </p>
      </div>

      {/* Active Session Card(s) */}
      {activeSessions.length > 0 && (
        <div className="space-y-3">
          <h3 className="text-lg font-semibold text-gray-900">Active Session</h3>
          {activeSessions.map((session) => (
            <button
              key={session.id}
              onClick={() => {
                if (session.charger_id) {
                  navigate(`/charge/${session.charger_id}`);
                }
              }}
              className="w-full bg-green-50 border-2 border-green-500 rounded-lg p-4 text-left hover:bg-green-100 transition-colors"
            >
              <div className="flex items-center justify-between mb-2">
                <div className="flex items-center space-x-3">
                  <div className="bg-green-500 p-2 rounded-lg">
                    <Zap className="w-5 h-5 text-white" />
                  </div>
                  <div>
                    <h4 className="font-semibold text-gray-900">{session.charger_name}</h4>
                    <p className="text-sm text-gray-600 flex items-center space-x-1">
                      <MapPin className="w-3 h-3" />
                      <span>{session.station_name}</span>
                    </p>
                  </div>
                </div>
                <div className="flex items-center space-x-2">
                  <span className="px-2 py-1 rounded text-xs font-medium bg-green-100 text-green-800 animate-pulse">
                    {session.status}
                  </span>
                  <ChevronRight className="w-5 h-5 text-gray-400" />
                </div>
              </div>
              {session.start_time && (
                <div className="flex items-center space-x-2 text-gray-700 mt-2">
                  <Clock className="w-4 h-4" />
                  <span className="text-lg font-mono font-bold">{formatDuration(session.start_time)}</span>
                </div>
              )}
            </button>
          ))}
        </div>
      )}

      {/* Quick Actions */}
      <div className="space-y-4">
        <h3 className="text-lg font-semibold text-gray-900">Quick Actions</h3>

        {quickActions.map((action) => {
          const Icon = action.icon;
          return (
            <button
              key={action.label}
              onClick={action.action}
              className="w-full bg-white rounded-lg p-4 shadow-sm flex items-center space-x-4 hover:shadow-md transition-shadow"
            >
              <div className={`${action.color} p-3 rounded-lg`}>
                <Icon className="w-6 h-6 text-white" />
              </div>
              <div className="flex-1 text-left">
                <h4 className="font-semibold text-gray-900">{action.label}</h4>
                <p className="text-sm text-gray-600">{action.description}</p>
              </div>
            </button>
          );
        })}
      </div>

      {/* Recent Chargers */}
      {recentChargers.length > 0 && (
        <div className="space-y-3">
          <h3 className="text-lg font-semibold text-gray-900">Recent Chargers</h3>
          {recentChargers.slice(0, 5).map((charger) => (
            <button
              key={charger.charge_point_string_id}
              onClick={() => navigate(`/charge/${charger.charge_point_string_id}`)}
              className="w-full bg-white rounded-lg p-4 shadow-sm flex items-center space-x-4 hover:shadow-md transition-shadow"
            >
              <div className="bg-yellow-500 p-3 rounded-lg">
                <Zap className="w-6 h-6 text-white" />
              </div>
              <div className="flex-1 text-left">
                <h4 className="font-semibold text-gray-900">{charger.charger_name}</h4>
                <p className="text-sm text-gray-600">{charger.station_name}</p>
              </div>
              <ChevronRight className="w-5 h-5 text-gray-400" />
            </button>
          ))}
        </div>
      )}

      {/* Info Section */}
      <div className="bg-blue-50 rounded-lg p-4 border border-blue-200">
        <h4 className="font-semibold text-blue-900 mb-2">How to Charge</h4>
        <ol className="text-sm text-blue-800 space-y-2 list-decimal list-inside">
          <li>Find a nearby charging station on the map</li>
          <li>Scan the QR code on the charger</li>
          <li>Start charging and monitor in real-time</li>
          <li>Stop when complete - payment is automatic</li>
        </ol>
      </div>
    </div>
  );
};
