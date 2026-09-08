"use client";

import { useEffect, useState } from "react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
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
export default function DiagnosticBundles({
  chargerId,
  chargerName,
  hasAuthKey,
}: {
  chargerId: number;
  chargerName: string;
  hasAuthKey: boolean;
}) {
  // Mirrored locally so the button flips from Generate to Rotate straight after
  // provisioning, without waiting for the parent to refetch the charger.
  const [keyExists, setKeyExists] = useState(hasAuthKey);
  const [rotateOpen, setRotateOpen] = useState(false);
  const [rotateConfirm, setRotateConfirm] = useState("");
  const [bundles, setBundles] = useState<DiagnosticBundle[]>([]);
  // Null once there is nothing older left to fetch.
  const [cursor, setCursor] = useState<number | null>(null);
  const [loadingMore, setLoadingMore] = useState(false);
  const [loading, setLoading] = useState(true);
  const [provisioning, setProvisioning] = useState(false);
  const [revealedKey, setRevealedKey] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    diagnosticBundleService
      .list(chargerId)
      .then((page) => {
        if (!cancelled) {
          setBundles(page.items);
          setCursor(page.next_cursor);
        }
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

  const handleLoadOlder = async () => {
    if (cursor === null) return;
    setLoadingMore(true);
    try {
      const page = await diagnosticBundleService.list(chargerId, 50, cursor);
      // Append: the archive reads oldest-downwards, and dropping the rows
      // already on screen would lose the reader's place mid-investigation.
      setBundles((prev) => [...prev, ...page.items]);
      setCursor(page.next_cursor);
    } catch {
      toast.error("Could not load older bundles");
    } finally {
      setLoadingMore(false);
    }
  };

  // A revealed key exists nowhere else — the server kept only its SHA-256, and
  // rotation has no grace overlap. Losing it here means the charger stays
  // unauthenticated until someone rotates again, so a reload must not be silent.
  useEffect(() => {
    if (!revealedKey) return;
    const warn = (e: BeforeUnloadEvent) => e.preventDefault();
    window.addEventListener("beforeunload", warn);
    return () => window.removeEventListener("beforeunload", warn);
  }, [revealedKey]);

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
      setKeyExists(true);
      toast.success("Auth key generated");
    } catch {
      // A 409 here means the charger already had a key — the endpoint refuses
      // to destroy it, so nothing has changed.
      toast.error("Could not generate auth key");
    } finally {
      setProvisioning(false);
    }
  };

  const handleRotate = async () => {
    setProvisioning(true);
    try {
      const result = await diagnosticBundleService.rotateAuthKey(
        chargerId,
        rotateConfirm
      );
      setRevealedKey(result.auth_key);
      setRotateOpen(false);
      setRotateConfirm("");
      toast.success("Auth key rotated — the charger is unauthenticated until reflashed");
    } catch {
      toast.error("Could not rotate auth key — the existing key is unchanged");
    } finally {
      setProvisioning(false);
    }
  };

  const formatBytes = (bytes: number) =>
    bytes >= 1024 * 1024
      ? `${(bytes / 1024 / 1024).toFixed(1)} MB`
      : `${(bytes / 1024).toFixed(1)} KB`;

  // The API already hands back IST-offset ISO strings, but the zone is passed
  // explicitly anyway: rendering without it would follow the viewer's browser,
  // which is not the same thing as IST (repo-wide rule, ADR 0012).
  const formatIst = (iso: string) =>
    new Date(iso).toLocaleString("en-IN", {
      timeZone: "Asia/Kolkata",
      hour12: false,
    });

  const formatIstTime = (iso: string) =>
    new Date(iso).toLocaleTimeString("en-IN", {
      timeZone: "Asia/Kolkata",
      hour12: false,
    });

  const formatDuration = (seconds: number) =>
    seconds >= 3600
      ? `${Math.floor(seconds / 3600)}h ${Math.floor((seconds % 3600) / 60)}m`
      : seconds >= 60
        ? `${Math.floor(seconds / 60)}m ${seconds % 60}s`
        : `${seconds}s`;

  return (
    <Card>
      <CardHeader className="flex flex-row items-center justify-between space-y-0">
        <CardTitle className="flex items-center gap-2">
          <FileText className="h-5 w-5" />
          Diagnostic Bundles
        </CardTitle>
        <Button
          variant={keyExists ? "destructive" : "outline"}
          size="sm"
          onClick={() => (keyExists ? setRotateOpen(true) : handleProvision())}
          disabled={provisioning}
        >
          <KeyRound className="mr-2 h-4 w-4" />
          {provisioning
            ? "Working…"
            : keyExists
              ? "Rotate auth key"
              : "Generate auth key"}
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
            <div className="mt-2 flex gap-2">
              <Button
                variant="ghost"
                size="sm"
                onClick={() => {
                  navigator.clipboard.writeText(revealedKey);
                  toast.success("Copied");
                }}
              >
                Copy
              </Button>
              {/* The only way to dismiss the panel. Clicking elsewhere must not
                  discard a secret that exists nowhere else. */}
              <Button
                variant="outline"
                size="sm"
                onClick={() => setRevealedKey(null)}
              >
                I have saved this key
              </Button>
            </div>
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
                  <th className="py-2 pr-4">Window (IST)</th>
                  <th className="py-2 pr-4">Size</th>
                  <th className="py-2 pr-4">Loss</th>
                  <th className="py-2" />
                </tr>
              </thead>
              <tbody>
                {bundles.map((bundle) => (
                  <tr key={bundle.id} className="border-b last:border-0">
                    <td className="py-2 pr-4 font-mono text-xs">
                      {formatIst(bundle.received_at_ist)}
                    </td>
                    <td className="py-2 pr-4 font-mono text-xs tabular-nums">
                      {/* When the records were written, not when they arrived.
                          Null is a real state — nothing in the body anchored —
                          so it is shown as such rather than as a zero. */}
                      {bundle.window_start_ist && bundle.window_end_ist ? (
                        <>
                          {formatIstTime(bundle.window_start_ist)}–
                          {formatIstTime(bundle.window_end_ist)}
                          {bundle.time_approximate && (
                            // Load-bearing: an approximate window fell back to
                            // receipt time, and must never be read as evidence
                            // of loss (ADR 0030).
                            <span
                              className="ml-1 text-muted-foreground"
                              title="Approximate — derived from receipt time or only some segments; not evidence of loss"
                            >
                              ~approx
                            </span>
                          )}
                        </>
                      ) : (
                        <span
                          className="text-muted-foreground"
                          title="No TIME_SYNC anchor in the body — the window is unknown, not empty"
                        >
                          —
                        </span>
                      )}
                    </td>
                    <td className="py-2 pr-4 tabular-nums">
                      {formatBytes(bundle.size_bytes)}
                    </td>
                    <td className="py-2 pr-4">
                      {bundle.lossy ? (
                        // Never a count of lost records: that number is not
                        // obtainable any more, because it needed a counter the
                        // charger cannot keep across a reboot (ADR 0030). A ring
                        // wrap says overwriting is happening *now*; a silence is
                        // measured time, not records. `lossy` is computed
                        // server-side against the gap threshold, so when there
                        // are no wraps the silence is definitionally the cause.
                        <div className="flex flex-wrap gap-1">
                          {bundle.ring_wrap_events > 0 && (
                            <Badge variant="destructive" className="gap-1">
                              <AlertTriangle className="h-3 w-3" />
                              {bundle.ring_wrap_events} ring wrap
                              {bundle.ring_wrap_events === 1 ? "" : "s"}
                            </Badge>
                          )}
                          {bundle.ring_wrap_events === 0 &&
                            bundle.gap_before_seconds !== null && (
                              <Badge variant="destructive" className="gap-1">
                                <AlertTriangle className="h-3 w-3" />
                                {formatDuration(bundle.gap_before_seconds)}{" "}
                                silence
                              </Badge>
                            )}
                        </div>
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
            {cursor !== null && (
              <div className="pt-3 text-center">
                <Button
                  variant="outline"
                  size="sm"
                  onClick={handleLoadOlder}
                  disabled={loadingMore}
                >
                  {loadingMore ? "Loading…" : "Load older"}
                </Button>
              </div>
            )}
          </div>
        )}
      </CardContent>

      <Dialog
        open={rotateOpen}
        onOpenChange={(o) => {
          setRotateOpen(o);
          if (!o) setRotateConfirm("");
        }}
      >
        <DialogContent className="max-w-md">
          <DialogHeader>
            <DialogTitle>Rotate auth key for {chargerName}?</DialogTitle>
            <DialogDescription asChild>
              <div className="space-y-2 text-sm">
                <p>
                  This replaces the key immediately. There is no overlap period —
                  the charger will fail authentication from the moment you
                  confirm, until the new key is loaded onto the unit.
                </p>
                <p>
                  The new key is shown <strong>once</strong> and cannot be
                  retrieved afterwards.
                </p>
              </div>
            </DialogDescription>
          </DialogHeader>

          <div className="space-y-2">
            <label htmlFor="rotate-confirm" className="text-sm font-medium">
              Type <code className="font-mono">{chargerName}</code> to confirm
            </label>
            <Input
              id="rotate-confirm"
              value={rotateConfirm}
              onChange={(e) => setRotateConfirm(e.target.value)}
              placeholder={chargerName}
              autoComplete="off"
            />
          </div>

          <DialogFooter>
            <Button variant="ghost" onClick={() => setRotateOpen(false)}>
              Cancel
            </Button>
            <Button
              variant="destructive"
              onClick={handleRotate}
              // Matched leniently here and server-side: the guard exists to stop
              // a slip, and demanding exact case would push people to paste.
              disabled={
                provisioning ||
                rotateConfirm.trim().toLowerCase() !==
                  chargerName.trim().toLowerCase()
              }
            >
              {provisioning ? "Rotating…" : "Rotate key"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </Card>
  );
}
