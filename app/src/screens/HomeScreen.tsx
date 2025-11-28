import { useUser } from '@clerk/clerk-react';
import { Zap, MapPin, Clock } from 'lucide-react';
import { useNavigate } from 'react-router-dom';

export const HomeScreen = () => {
  const { user } = useUser();
  const navigate = useNavigate();

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
