import { Outlet, useLocation, useNavigate } from 'react-router-dom';
import { Home, Map, ScanLine, Receipt } from 'lucide-react';
import { UserButton } from '@clerk/clerk-react';
import { NetworkStatus } from './NetworkStatus';
import { useStatusBar } from '../hooks/useStatusBar';

export const Layout = () => {
  const location = useLocation();
  const navigate = useNavigate();

  // Configure status bar for mobile
  useStatusBar();

  const navItems = [
    { path: '/', icon: Home, label: 'Home' },
    { path: '/stations', icon: Map, label: 'Stations' },
    { path: '/scanner', icon: ScanLine, label: 'Scanner' },
    { path: '/sessions', icon: Receipt, label: 'Sessions' },
  ];

  return (
    <div className="h-screen flex flex-col bg-gray-50">
      {/* Network Status Indicator - with safe area for status bar */}
      <div style={{ paddingTop: 'env(safe-area-inset-top)' }}>
        <NetworkStatus />
      </div>

      {/* Header */}
      <header className="bg-white shadow-sm px-4 py-3 flex items-center justify-between">
        <h1 className="text-xl font-bold text-gray-900">LyncPower</h1>
        <UserButton />
      </header>

      {/* Main Content */}
      <main className="flex-1 overflow-y-auto">
        <Outlet />
      </main>

      {/* Bottom Navigation */}
      <nav
        className="bg-white border-t border-gray-200 px-4 py-2"
        style={{ paddingBottom: 'max(0.5rem, env(safe-area-inset-bottom))' }}
      >
        <div className="flex justify-around items-center">
          {navItems.map((item) => {
            const isActive = location.pathname === item.path;
            const Icon = item.icon;

            return (
              <button
                key={item.path}
                onClick={() => navigate(item.path)}
                className={`flex flex-col items-center justify-center py-2 px-3 rounded-lg transition-colors ${
                  isActive
                    ? 'text-blue-600 bg-blue-50'
                    : 'text-gray-600 hover:text-gray-900'
                }`}
              >
                <Icon className="w-6 h-6" />
                <span className="text-xs mt-1 font-medium">{item.label}</span>
              </button>
            );
          })}
        </div>
      </nav>
    </div>
  );
};
