"use client";

import { useEffect, useState } from "react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Download, KeyRound, AlertTriangle, FileText } from "lucide-react";
import { toast } from "sonner";
import {
  diagnosticBundleService,
  type DiagnosticBundle,
} from "@/lib/api-services";

/**
 * Diagnostic Bundles panel (ADR 0029).
 *
 * Deliberately NOT a log viewer. Trace content is searched in New Relic under
 * the VoltLync-Charger-Logs-{env} entity; this panel answers delivery questions
 * — did every bundle arrive, and did the charger lose anything — and hands back
 * the raw archive for anything older than New Relic's 30-day window.
 */
export default function DiagnosticBundles({ chargerId }: { chargerId: number }) {
  const [bundles, setBundles] = useState<DiagnosticBundle[]>([]);
  const [loading, setLoading] = useState(true);
  const [provisioning, setProvisioning] = useState(false);
  const [revealedKey, setRevealedKey] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    diagnosticBundleService
      .list(chargerId)
      .then((data) => {
        if (!cancelled) setBundles(data);
      })
      .catch(() => {
        if (!cancelled) toast.error("Could not load diagnostic bundles");
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [chargerId]);

  const handleDownload = async (bundle: DiagnosticBundle) => {
    try {
      const { url } = await diagnosticBundleService.downloadUrl(bundle.id);
      window.open(url, "_blank", "noopener,noreferrer");
    } catch {
      toast.error("Could not generate download link");
    }
  };

  const handleProvision = async () => {
    setProvisioning(true);
    try {
      const result = await diagnosticBundleService.provisionAuthKey(chargerId);
      setRevealedKey(result.auth_key);
      toast.success(
        result.rotated ? "Auth key rotated" : "Auth key generated"
      );
    } catch {
      toast.error("Could not generate auth key");
    } finally {
      setProvisioning(false);
    }
  };

  const formatBytes = (bytes: number) =>
    bytes >= 1024 * 1024
      ? `${(bytes / 1024 / 1024).toFixed(1)} MB`
      : `${(bytes / 1024).toFixed(1)} KB`;

  return (
    <Card>
      <CardHeader className="flex flex-row items-center justify-between space-y-0">
        <CardTitle className="flex items-center gap-2">
          <FileText className="h-5 w-5" />
          Diagnostic Bundles
        </CardTitle>
        <Button
          variant="outline"
          size="sm"
          onClick={handleProvision}
          disabled={provisioning}
        >
          <KeyRound className="mr-2 h-4 w-4" />
          {provisioning ? "Generating…" : "Generate auth key"}
        </Button>
      </CardHeader>

      <CardContent>
        {revealedKey && (
          <div className="mb-4 rounded-md border border-amber-300 bg-amber-50 p-3 dark:border-amber-800 dark:bg-amber-950">
            <p className="mb-2 text-sm font-medium text-amber-900 dark:text-amber-200">
              Copy this key now — it is shown once and cannot be retrieved again.
            </p>
            <code className="block break-all rounded bg-white p-2 font-mono text-sm dark:bg-black">
              {revealedKey}
            </code>
            <Button
              variant="ghost"
              size="sm"
              className="mt-2"
              onClick={() => {
                navigator.clipboard.writeText(revealedKey);
                toast.success("Copied");
              }}
            >
              Copy
            </Button>
          </div>
        )}

        {loading ? (
          <p className="py-6 text-center text-sm text-muted-foreground">
            Loading…
          </p>
        ) : bundles.length === 0 ? (
          <p className="py-6 text-center text-sm text-muted-foreground">
            No bundles uploaded yet. The charger uploads every 6 hours and after
            a fault.
          </p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b text-left text-xs uppercase text-muted-foreground">
                  <th className="py-2 pr-4">Received (IST)</th>
                  <th className="py-2 pr-4">Seq</th>
                  <th className="py-2 pr-4">Records</th>
                  <th className="py-2 pr-4">Size</th>
                  <th className="py-2 pr-4">Loss</th>
                  <th className="py-2" />
                </tr>
              </thead>
              <tbody>
                {bundles.map((bundle) => (
                  <tr key={bundle.id} className="border-b last:border-0">
                    <td className="py-2 pr-4 font-mono text-xs">
                      {new Date(bundle.received_at_ist).toLocaleString("en-IN", {
                        timeZone: "Asia/Kolkata",
                      })}
                    </td>
                    <td className="py-2 pr-4 font-mono text-xs tabular-nums">
                      {bundle.epoch > 0 && (
                        <span className="text-muted-foreground">
                          e{bundle.epoch}/
                        </span>
                      )}
                      {bundle.bundle_seq}
                    </td>
                    <td className="py-2 pr-4 tabular-nums">
                      {bundle.first_record ?? "?"}–{bundle.last_record ?? "?"}
                    </td>
                    <td className="py-2 pr-4 tabular-nums">
                      {formatBytes(bundle.size_bytes)}
                    </td>
                    <td className="py-2 pr-4">
                      {bundle.lossy ? (
                        // The two causes need different remedies, so they are
                        // labelled rather than merged into one "missing" count.
                        <Badge variant="destructive" className="gap-1">
                          <AlertTriangle className="h-3 w-3" />
                          {bundle.overflow_delta > 0
                            ? `${bundle.overflow_delta} overwritten`
                            : `${bundle.gap_records} missing`}
                        </Badge>
                      ) : (
                        <Badge variant="outline">Complete</Badge>
                      )}
                    </td>
                    <td className="py-2 text-right">
                      <Button
                        variant="ghost"
                        size="sm"
                        onClick={() => handleDownload(bundle)}
                      >
                        <Download className="h-4 w-4" />
                      </Button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </CardContent>
    </Card>
  );
}
