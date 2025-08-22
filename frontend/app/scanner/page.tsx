"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import QRScanner from "@/components/QRScanner";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { QrCode, Keyboard, CheckCircle, AlertTriangle } from "lucide-react";
import { toast } from "sonner";

export default function ScannerPage() {
  const router = useRouter();
  const [manualInput, setManualInput] = useState("");
  const [showManualInput, setShowManualInput] = useState(false);
  const [lastScannedCode, setLastScannedCode] = useState<string | null>(null);

  const extractChargerIdFromQR = (qrData: string): string | null => {
    // Parse URL and extract charger ID from /charge/[id] pattern
    // Supports any base URL: localhost, production domain, etc.
    try {
      const url = new URL(qrData);
      
      // Extract from pathname: /charge/123 (any domain)
      const pathPattern = /\/charge\/(\d+)$/i;
      const pathMatch = url.pathname.match(pathPattern);
      if (pathMatch) {
        return pathMatch[1];
      }
    } catch {
      // Not a valid URL
    }

    return null;
  };

  const navigateToCharger = (chargerId: string) => {
    // Validate that chargerId is numeric
    if (!/^\d+$/.test(chargerId)) {
      toast.error("Invalid charger ID format. Please enter a numeric ID.");
      return;
    }

    toast.success(`Navigating to charger ${chargerId}`);
    router.push(`/charge/${chargerId}`);
  };

  const handleQRScan = (qrData: string) => {
    setLastScannedCode(qrData);
    
    const chargerId = extractChargerIdFromQR(qrData);
    
    if (chargerId) {
      toast.success(`Found charger ID: ${chargerId}`);
      navigateToCharger(chargerId);
    } else {
      toast.error("Could not extract charger ID from QR code. Try manual input.");
      setShowManualInput(true);
    }
  };

  const handleManualSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (manualInput.trim()) {
      navigateToCharger(manualInput.trim());
    }
  };

  const handleScanError = (error: string) => {
    toast.error(`Scanner error: ${error}`);
  };

  return (
    <div className="min-h-[80vh] flex flex-col items-center justify-center space-y-6 p-4">
      <div className="text-center space-y-2">
        <h1 className="text-3xl font-bold">Charger Scanner</h1>
        <p className="text-muted-foreground max-w-md">
          Scan the QR code on your EV charger to quickly access charging controls and monitor your session.
        </p>
      </div>

      <div className="w-full max-w-md space-y-4">
        {/* QR Scanner */}
        <QRScanner onScan={handleQRScan} onError={handleScanError} />

        {/* Last Scanned Code Display */}
        {lastScannedCode && (
          <Card>
            <CardHeader className="pb-3">
              <CardTitle className="text-sm flex items-center gap-2">
                {extractChargerIdFromQR(lastScannedCode) ? (
                  <>
                    <CheckCircle className="h-4 w-4 text-green-500" />
                    Scan Successful
                  </>
                ) : (
                  <>
                    <AlertTriangle className="h-4 w-4 text-orange-500" />
                    Scan Detected
                  </>
                )}
              </CardTitle>
            </CardHeader>
            <CardContent className="pt-0">
              <div className="text-xs font-mono bg-muted p-2 rounded break-all">
                {lastScannedCode}
              </div>
              {extractChargerIdFromQR(lastScannedCode) && (
                <div className="mt-2 text-sm">
                  <strong>Charger ID:</strong> {extractChargerIdFromQR(lastScannedCode)}
                </div>
              )}
            </CardContent>
          </Card>
        )}

        {/* Manual Input Toggle */}
        <div className="text-center">
          <Button
            variant="outline"
            onClick={() => setShowManualInput(!showManualInput)}
            className="w-full"
          >
            <Keyboard className="h-4 w-4 mr-2" />
            {showManualInput ? "Hide Manual Input" : "Enter Charger ID Manually"}
          </Button>
        </div>

        {/* Manual Input Form */}
        {showManualInput && (
          <Card>
            <CardHeader>
              <CardTitle className="text-sm">Manual Entry</CardTitle>
            </CardHeader>
            <CardContent>
              <form onSubmit={handleManualSubmit} className="space-y-4">
                <div>
                  <Label htmlFor="charger-id">Charger ID</Label>
                  <Input
                    id="charger-id"
                    type="number"
                    placeholder="e.g. 123"
                    value={manualInput}
                    onChange={(e) => setManualInput(e.target.value)}
                    className="mt-1"
                  />
                </div>
                <Button type="submit" className="w-full" disabled={!manualInput.trim()}>
                  Go to Charger
                </Button>
              </form>
            </CardContent>
          </Card>
        )}

        {/* Instructions */}
        <Card className="bg-muted/50">
          <CardContent className="pt-6">
            <div className="space-y-3 text-sm">
              <div className="flex items-start gap-3">
                <QrCode className="h-4 w-4 mt-0.5 text-muted-foreground flex-shrink-0" />
                <div>
                  <strong>QR Code Scanning:</strong> Position the QR code within the camera viewfinder. The app will automatically detect and extract the charger ID.
                </div>
              </div>
              <div className="flex items-start gap-3">
                <Keyboard className="h-4 w-4 mt-0.5 text-muted-foreground flex-shrink-0" />
                <div>
                  <strong>Manual Entry:</strong> If scanning fails, you can manually enter the charger ID number found on the charger unit.
                </div>
              </div>
            </div>
          </CardContent>
        </Card>
      </div>
    </div>
  );
}