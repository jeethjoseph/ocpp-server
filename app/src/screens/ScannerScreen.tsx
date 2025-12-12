import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  CapacitorBarcodeScanner,
  CapacitorBarcodeScannerTypeHint
} from '@capacitor/barcode-scanner';
import { Camera, AlertCircle, Keyboard } from 'lucide-react';

export const ScannerScreen = () => {
  const navigate = useNavigate();
  const [isScanning, setIsScanning] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [manualInput, setManualInput] = useState('');

  const startScan = async () => {
    setError(null);
    setIsScanning(true);

    try {
      const result = await CapacitorBarcodeScanner.scanBarcode({
        hint: CapacitorBarcodeScannerTypeHint.QR_CODE,
        scanInstructions: 'Align QR code within the frame',
        scanButton: false,
      });

      setIsScanning(false);

      if (result.ScanResult) {
        handleScannedCode(result.ScanResult);
      }
    } catch (err) {
      console.error('Scan error:', err);
      setError('Failed to scan QR code. Please try again.');
      setIsScanning(false);
    }
  };

  const handleScannedCode = (code: string) => {
    // Expected format: https://domain.com/charge/{chargerId}
    // Or just the charger ID (alphanumeric with underscores)

    console.log('Scanned code:', code);
    let chargerId: string | null = null;

    // Try to extract from URL (supports alphanumeric IDs with underscores)
    const urlMatch = code.match(/\/charge\/([A-Za-z0-9_-]+)/i);
    if (urlMatch) {
      chargerId = urlMatch[1];
      console.log('Extracted charger ID from URL:', chargerId);
    } else if (/^[A-Za-z0-9_-]+$/.test(code)) {
      // Just an alphanumeric ID
      chargerId = code;
      console.log('Using direct charger ID:', chargerId);
    }

    if (chargerId) {
      console.log('Navigating to:', `/charge/${chargerId}`);
      navigate(`/charge/${chargerId}`);
    } else {
      setError(`Invalid QR code format: ${code}`);
    }
  };

  const handleManualInput = () => {
    if (!manualInput.trim()) {
      setError('Please enter a charger ID');
      return;
    }

    // Try to extract from URL first, otherwise use as-is
    const urlMatch = manualInput.match(/\/charge\/([A-Za-z0-9_-]+)/i);
    let chargerId: string;

    if (urlMatch) {
      chargerId = urlMatch[1];
    } else {
      chargerId = manualInput.trim();
    }

    if (!/^[A-Za-z0-9_-]+$/.test(chargerId)) {
      setError('Charger ID can only contain letters, numbers, underscores, and hyphens');
      return;
    }

    navigate(`/charge/${chargerId}`);
  };

  return (
    <div className="p-4 space-y-6">
      <div>
        <h2 className="text-2xl font-bold text-gray-900">QR Code Scanner</h2>
        <p className="text-gray-600 mt-1">
          Scan the QR code on the charger to start charging
        </p>
      </div>

      {/* Error message */}
      {error && (
        <div className="bg-red-50 border border-red-200 rounded-lg p-4 flex items-start space-x-3">
          <AlertCircle className="w-5 h-5 text-red-600 flex-shrink-0 mt-0.5" />
          <p className="text-red-800 text-sm">{error}</p>
        </div>
      )}

      {/* Scan button */}
      <button
        onClick={startScan}
        disabled={isScanning}
        className="w-full bg-blue-600 text-white rounded-lg p-6 shadow-lg hover:bg-blue-700 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
      >
        <div className="flex flex-col items-center space-y-3">
          <div className="bg-blue-500 p-4 rounded-full">
            <Camera className="w-12 h-12" />
          </div>
          <div>
            <h3 className="text-xl font-semibold">
              {isScanning ? 'Scanning...' : 'Scan QR Code'}
            </h3>
            <p className="text-blue-100 text-sm mt-1">
              {isScanning
                ? 'Point your camera at the QR code'
                : 'Point your camera at the charger\'s QR code'}
            </p>
          </div>
        </div>
      </button>

      {/* Divider */}
      <div className="flex items-center space-x-4">
        <div className="flex-1 border-t border-gray-300"></div>
        <span className="text-gray-500 text-sm font-medium">OR</span>
        <div className="flex-1 border-t border-gray-300"></div>
      </div>

      {/* Manual input */}
      <div className="bg-white rounded-lg p-6 shadow-sm space-y-4">
        <div className="flex items-center space-x-2">
          <Keyboard className="w-5 h-5 text-gray-600" />
          <h3 className="font-semibold text-gray-900">Enter Charger ID</h3>
        </div>

        <div className="space-y-3">
          <input
            type="text"
            placeholder="e.g., DOWNTOWN_PLAZA_STATION_03 or URL"
            value={manualInput}
            onChange={(e) => setManualInput(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Enter') {
                handleManualInput();
              }
            }}
            className="w-full px-4 py-3 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-transparent"
          />

          <button
            onClick={handleManualInput}
            className="w-full bg-gray-800 text-white py-3 rounded-lg font-semibold hover:bg-gray-900 transition-colors"
          >
            Continue
          </button>
        </div>
      </div>

      {/* Info section */}
      <div className="bg-blue-50 rounded-lg p-4 border border-blue-200">
        <h4 className="font-semibold text-blue-900 mb-2">How to scan</h4>
        <ol className="text-sm text-blue-800 space-y-2 list-decimal list-inside">
          <li>Tap "Scan QR Code" button</li>
          <li>Allow camera access when prompted</li>
          <li>Point camera at the QR code on the charger</li>
          <li>QR code will be detected automatically</li>
        </ol>
      </div>
    </div>
  );
};
