import { useEffect } from 'react';
import { StatusBar, Style } from '@capacitor/status-bar';
import { Capacitor } from '@capacitor/core';

export const useStatusBar = () => {
  useEffect(() => {
    if (!Capacitor.isNativePlatform()) return;

    const setupStatusBar = async () => {
      try {
        // Make sure status bar doesn't overlay content
        await StatusBar.setOverlaysWebView({ overlay: false });

        // Set status bar to default style (dark icons/text on white background)
        await StatusBar.setStyle({ style: Style.Default });

        // Set background color to white to match app header
        await StatusBar.setBackgroundColor({ color: '#ffffff' });

        // Show the status bar
        await StatusBar.show();
      } catch (error) {
        console.error('Error setting up status bar:', error);
      }
    };

    setupStatusBar();
  }, []);
};
