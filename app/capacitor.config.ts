import type { CapacitorConfig } from '@capacitor/cli';

const config: CapacitorConfig = {
  appId: 'com.lyncpower.user',
  appName: 'LyncPower User',
  webDir: 'dist',
  plugins: {
    StatusBar: {
      // Prevent status bar from overlaying the app
      overlay: false,
      // Set background color to white to match app header
      backgroundColor: '#ffffff',
      // Use light style (dark text/icons) since background is white
      style: 'LIGHT',
    },
  },
};

export default config;
