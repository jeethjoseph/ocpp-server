import { Routes, Route, Navigate } from 'react-router-dom';
import { Layout } from './components/Layout';
import { HomeScreen } from './screens/HomeScreen';
import { StationsScreen } from './screens/StationsScreen';
import { ScannerScreen } from './screens/ScannerScreen';
import { ChargeScreen } from './screens/ChargeScreen';
import { SessionsScreen } from './screens/SessionsScreen';

export const AppRoutes = () => {
  return (
    <Routes>
      <Route path="/" element={<Layout />}>
        <Route index element={<HomeScreen />} />
        <Route path="stations" element={<StationsScreen />} />
        <Route path="scanner" element={<ScannerScreen />} />
        <Route path="charge/:chargerId" element={<ChargeScreen />} />
        <Route path="sessions" element={<SessionsScreen />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Route>
    </Routes>
  );
};
