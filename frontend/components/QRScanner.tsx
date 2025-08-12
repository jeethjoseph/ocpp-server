"use client";

import { useEffect, useRef, useState } from "react";
import { BrowserMultiFormatReader } from "@zxing/library";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Camera, CameraOff, RotateCcw } from "lucide-react";

interface QRScannerProps {
  onScan: (result: string) => void;
  onError?: (error: string) => void;
}

export default function QRScanner({ onScan, onError }: QRScannerProps) {
  const videoRef = useRef<HTMLVideoElement>(null);
  const [isScanning, setIsScanning] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [codeReader] = useState(new BrowserMultiFormatReader());

  const startScanning = async () => {
    try {
      setError(null);
      setIsScanning(true);

      if (!videoRef.current) {
        throw new Error("Video element not found");
      }

      await codeReader.decodeFromVideoDevice(
        null,
        videoRef.current,
        (result) => {
          if (result) {
            const scannedText = result.getText();
            onScan(scannedText);
            stopScanning();
          }
        }
      );
    } catch (err) {
      const errorMessage = err instanceof Error ? err.message : "Failed to access camera";
      setError(errorMessage);
      onError?.(errorMessage);
      setIsScanning(false);
    }
  };

  const stopScanning = () => {
    try {
      codeReader.reset();
      setIsScanning(false);
    } catch (err) {
      console.error("Error stopping scanner:", err);
    }
  };

  const resetScanner = () => {
    stopScanning();
    setError(null);
  };

  useEffect(() => {
    return () => {
      codeReader.reset();
    };
  }, [codeReader]);

  return (
    <Card className="w-full max-w-md mx-auto">
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <Camera className="h-5 w-5" />
          QR Code Scanner
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-4">
        <div className="relative">
          <video
            ref={videoRef}
            className="w-full aspect-square object-cover rounded-lg bg-muted"
            playsInline
            muted
          />
          {!isScanning && (
            <div className="absolute inset-0 flex items-center justify-center bg-muted rounded-lg">
              <div className="text-center">
                <Camera className="h-12 w-12 mx-auto text-muted-foreground mb-2" />
                <p className="text-sm text-muted-foreground">
                  Click &quot;Start Scanning&quot; to begin
                </p>
              </div>
            </div>
          )}
        </div>

        {error && (
          <div className="text-sm text-destructive bg-destructive/10 p-3 rounded-lg">
            {error}
          </div>
        )}

        <div className="flex gap-2">
          {!isScanning ? (
            <Button onClick={startScanning} className="flex-1">
              <Camera className="h-4 w-4 mr-2" />
              Start Scanning
            </Button>
          ) : (
            <Button onClick={stopScanning} variant="destructive" className="flex-1">
              <CameraOff className="h-4 w-4 mr-2" />
              Stop Scanning
            </Button>
          )}
          
          {error && (
            <Button onClick={resetScanner} variant="outline" size="icon">
              <RotateCcw className="h-4 w-4" />
            </Button>
          )}
        </div>

        <p className="text-xs text-muted-foreground text-center">
          Position the QR code within the camera view. Make sure the QR code contains a charger ID.
        </p>
      </CardContent>
    </Card>
  );
}