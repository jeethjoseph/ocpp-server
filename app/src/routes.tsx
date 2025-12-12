import { Routes, Route, Navigate } from 'react-router-dom';
import { useEffect } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import { Geolocation } from '@capacitor/geolocation';
import { Layout } from './components/Layout';
import { HomeScreen } from './screens/HomeScreen';
import { StationsScreen } from './screens/StationsScreen';
import { ScannerScreen } from './screens/ScannerScreen';
import { ChargeScreen } from './screens/ChargeScreen';
import { SessionsScreen } from './screens/SessionsScreen';
import { useApi } from './lib/api-client';
import { publicStationService, userSessionService } from './lib/api-services';

export const AppRoutes = () => {
  const queryClient = useQueryClient();
  const api = useApi();

  // Prefetch common screens data on app mount for instant navigation
  useEffect(() => {
    const prefetchData = async () => {
      console.log('🚀 Prefetching data for instant navigation...');

      // Prefetch stations data
      queryClient.prefetchQuery({
        queryKey: ['public-stations'],
        queryFn: () => publicStationService(api).getAll(),
        staleTime: 2 * 60 * 1000,
      });

      // Prefetch user sessions and wallet
      queryClient.prefetchQuery({
        queryKey: ['my-sessions'],
        queryFn: () => userSessionService(api).getMySessions(1, 100),
        staleTime: 30 * 1000,
      });

      queryClient.prefetchQuery({
        queryKey: ['my-wallet'],
        queryFn: () => userSessionService(api).getMyWallet(),
        staleTime: 30 * 1000,
      });

      // Prefetch user location (if permission already granted)
      queryClient.prefetchQuery({
        queryKey: ['user-location'],
        queryFn: async () => {
          try {
            const permissionStatus = await Geolocation.checkPermissions();
            if (permissionStatus.location !== 'granted') {
              return null; // Don't request permission during prefetch
            }

            const position = await Geolocation.getCurrentPosition({
              enableHighAccuracy: false,
              timeout: 10000,
              maximumAge: 60000, // Accept cached location up to 1 minute old
            });

            return {
              lat: position.coords.latitude,
              lng: position.coords.longitude,
            };
          } catch {
            return null; // Silently fail, user can manually request location later
          }
        },
        staleTime: 5 * 60 * 1000,
      });

      console.log('✅ Data prefetch complete');
    };

    prefetchData();
  }, [queryClient, api]);

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
