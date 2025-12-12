import { useEffect, useState } from 'react';
import { Network } from '@capacitor/network';

export const useNetworkStatus = () => {
  const [isOnline, setIsOnline] = useState(true);
  const [networkType, setNetworkType] = useState<string>('unknown');

  useEffect(() => {
    // Get initial network status
    const getInitialStatus = async () => {
      const status = await Network.getStatus();
      setIsOnline(status.connected);
      setNetworkType(status.connectionType);
    };

    getInitialStatus();

    // Listen for network status changes
    const handler = Network.addListener('networkStatusChange', (status) => {
      setIsOnline(status.connected);
      setNetworkType(status.connectionType);
    });

    return () => {
      handler.then(h => h.remove());
    };
  }, []);

  return {
    isOnline,
    networkType,
    isOffline: !isOnline,
  };
};
