"use client";

import React, { Suspense, useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useRouter, useSearchParams, usePathname } from "next/navigation";
import Link from "next/link";
import { toast } from "sonner";
import { useVirtualizer } from "@tanstack/react-virtual";
import { AdminOnly } from "@/components/RoleWrapper";
import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Button } from "@/components/ui/button";
import { AlertTriangle, ArrowUpDown, Download } from "lucide-react";
import { useLogs } from "@/lib/queries/logs";
import { LogEntry, logService } from "@/lib/api-services";
import { OCPP_ACTIONS } from "@/lib/ocpp-actions";
import { useAuth } from "@/contexts/AuthContext";
import ChargerCombobox from "@/components/ChargerCombobox";

type Direction = "ALL" | "IN" | "OUT";

const DEFAULT_LIMIT = 200;
const MAX_LIMIT = 5000;

// datetime-local <-> Date helpers (inputs are in local tz; the API wants ISO+tz).
function toDateTimeLocal(date: Date): string {
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}T${pad(date.getHours())}:${pad(date.getMinutes())}`;
}

function LogsConsoleInner() {
  const router = useRouter();
  const pathname = usePathname();
  const searchParams = useSearchParams();
  const { getToken } = useAuth();

  // --- initial state from the URL (read once) ---
  const [charger, setCharger] = useState<string | undefined>(
    searchParams.get("charger") || undefined
  );
  const [actions, setActions] = useState<string[]>(
    searchParams.get("actions")?.split(",").filter(Boolean) ?? []
  );
  const [startLocal, setStartLocal] = useState<string>(
    searchParams.get("start") || toDateTimeLocal(new Date(Date.now() - 24 * 60 * 60 * 1000))
  );
  const [endLocal, setEndLocal] = useState<string>(
    searchParams.get("end") || toDateTimeLocal(new Date())
  );
  const [limit, setLimit] = useState<number>(
    Number(searchParams.get("limit")) || DEFAULT_LIMIT
  );
  const [direction, setDirection] = useState<Direction>(
    (searchParams.get("dir") as Direction) || "ALL"
  );
  const [errorsOnly, setErrorsOnly] = useState<boolean>(searchParams.get("errors") === "1");
  const [offset, setOffset] = useState<number>(0);
  const [downloading, setDownloading] = useState<boolean>(false);

  // --- write state back to the URL (shareable) ---
  useEffect(() => {
    const sp = new URLSearchParams();
    if (charger) sp.set("charger", charger);
    if (actions.length) sp.set("actions", actions.join(","));
    if (startLocal) sp.set("start", startLocal);
    if (endLocal) sp.set("end", endLocal);
    if (limit !== DEFAULT_LIMIT) sp.set("limit", String(limit));
    if (direction !== "ALL") sp.set("dir", direction);
    if (errorsOnly) sp.set("errors", "1");
    const qs = sp.toString();
    router.replace(qs ? `${pathname}?${qs}` : pathname, { scroll: false });
  }, [charger, actions, startLocal, endLocal, limit, direction, errorsOnly, pathname, router]);

  // --- reset paging to the first page whenever a filter changes ---
  useEffect(() => {
    setOffset(0);
  }, [charger, actions, startLocal, endLocal, limit, direction, errorsOnly]);

  // --- shared filter params (server-side: charger, action, window, direction, errors) ---
  const filters = useMemo(
    () => ({
      charge_point_id: charger,
      message_type: actions.length ? actions : undefined,
      start_date: startLocal ? new Date(startLocal).toISOString() : undefined,
      end_date: endLocal ? new Date(endLocal).toISOString() : undefined,
      direction: direction !== "ALL" ? direction : undefined,
      errors_only: errorsOnly || undefined,
      limit,
    }),
    [charger, actions, startLocal, endLocal, direction, errorsOnly, limit]
  );

  // --- server query (everything is filtered + paged server-side now) ---
  const { data: logsResponse, isLoading, error } = useLogs({ ...filters, offset });

  const rows = useMemo(() => logsResponse?.data ?? [], [logsResponse]);
  const total = logsResponse?.total ?? 0;
  const hasMore = logsResponse?.has_more ?? false;

  const inbound = useMemo(() => rows.filter((l) => l.direction === "IN").length, [rows]);
  const outbound = rows.length - inbound;

  const rangeStart = total === 0 ? 0 : offset + 1;
  const rangeEnd = offset + rows.length;

  const toggleAction = useCallback((action: string) => {
    setActions((prev) =>
      prev.includes(action) ? prev.filter((a) => a !== action) : [...prev, action]
    );
  }, []);

  const handleDownloadCSV = async () => {
    setDownloading(true);
    try {
      const blob = await logService.exportCsv(filters, getToken);
      const url = URL.createObjectURL(blob);
      const anchor = document.createElement("a");
      anchor.href = url;
      anchor.download = `${charger || "logs-console"}.csv`;
      document.body.appendChild(anchor);
      anchor.click();
      anchor.remove();
      URL.revokeObjectURL(url);
    } catch (err) {
      console.error("CSV export failed", err);
      toast.error("Failed to download CSV. Please try again.");
    } finally {
      setDownloading(false);
    }
  };

  // --- virtualized row list ---
  const parentRef = useRef<HTMLDivElement>(null);
  const virtualizer = useVirtualizer({
    count: rows.length,
    getScrollElement: () => parentRef.current,
    estimateSize: () => 140,
    overscan: 8,
  });

  return (
    <div className="space-y-4">
      {/* Filters */}
      <div className="flex flex-col gap-4 p-4 bg-white dark:bg-gray-800 border border-gray-200 dark:border-gray-700 rounded-lg">
        <div className="flex flex-wrap gap-4 items-end">
          <div className="space-y-1">
            <Label className="text-xs font-medium text-gray-600 dark:text-gray-300">Charger</Label>
            <ChargerCombobox value={charger} onChange={setCharger} />
          </div>
          <div className="space-y-1">
            <Label htmlFor="start" className="text-xs font-medium text-gray-600 dark:text-gray-300">Start</Label>
            <Input
              id="start"
              type="datetime-local"
              value={startLocal}
              onChange={(e) => setStartLocal(e.target.value)}
              className="w-56 bg-white dark:bg-gray-900"
            />
          </div>
          <div className="space-y-1">
            <Label htmlFor="end" className="text-xs font-medium text-gray-600 dark:text-gray-300">End</Label>
            <Input
              id="end"
              type="datetime-local"
              value={endLocal}
              onChange={(e) => setEndLocal(e.target.value)}
              className="w-56 bg-white dark:bg-gray-900"
            />
          </div>
          <div className="space-y-1">
            <Label htmlFor="limit" className="text-xs font-medium text-gray-600 dark:text-gray-300">
              Page size (max {MAX_LIMIT})
            </Label>
            <Input
              id="limit"
              type="number"
              min={1}
              max={MAX_LIMIT}
              value={limit}
              onChange={(e) =>
                setLimit(Math.min(MAX_LIMIT, Math.max(1, parseInt(e.target.value) || DEFAULT_LIMIT)))
              }
              className="w-28 bg-white dark:bg-gray-900"
            />
          </div>
        </div>

        {/* Action multi-select */}
        <div className="space-y-1">
          <div className="flex items-center gap-3">
            <Label className="text-xs font-medium text-gray-600 dark:text-gray-300">Action</Label>
            {actions.length > 0 && (
              <button
                type="button"
                onClick={() => setActions([])}
                className="text-xs text-blue-600 dark:text-blue-400 hover:underline"
              >
                Clear ({actions.length})
              </button>
            )}
          </div>
          <div className="flex flex-wrap gap-1.5">
            {OCPP_ACTIONS.map((action) => (
              <Button
                key={action}
                variant={actions.includes(action) ? "default" : "outline"}
                size="sm"
                className="h-7 text-xs"
                onClick={() => toggleAction(action)}
              >
                {action}
              </Button>
            ))}
          </div>
        </div>

        {/* Direction + errors-only (server-side filters) */}
        <div className="flex flex-wrap gap-6 items-center">
          <div className="flex items-center gap-2">
            <Label className="text-xs font-medium text-gray-600 dark:text-gray-300">Direction</Label>
            {(["ALL", "IN", "OUT"] as Direction[]).map((d) => (
              <Button
                key={d}
                variant={direction === d ? "default" : "outline"}
                size="sm"
                className="h-7 text-xs"
                onClick={() => setDirection(d)}
              >
                {d}
              </Button>
            ))}
          </div>
          <Button
            variant={errorsOnly ? "default" : "outline"}
            size="sm"
            className="h-7 text-xs"
            onClick={() => setErrorsOnly((v) => !v)}
          >
            Errors only
          </Button>
        </div>
      </div>

      {/* Warning */}
      {logsResponse?.message && (
        <div className="p-3 bg-yellow-50 dark:bg-yellow-900/20 border border-yellow-200 dark:border-yellow-800 rounded-lg flex items-start gap-2">
          <AlertTriangle className="w-5 h-5 text-yellow-600 dark:text-yellow-400 mt-0.5" />
          <div className="text-sm text-yellow-800 dark:text-yellow-200">
            <strong>Note:</strong> {logsResponse.message}
          </div>
        </div>
      )}

      {/* Results summary + pagination */}
      {logsResponse && (
        <div className="flex flex-wrap items-center justify-between gap-3 bg-gray-50 dark:bg-gray-800 p-3 rounded-lg border border-gray-200 dark:border-gray-700">
          <div className="text-sm text-gray-600 dark:text-gray-400">
            <strong className="text-gray-900 dark:text-gray-100">
              Showing {rangeStart}&ndash;{rangeEnd} of {total}
            </strong>
            <span className="ml-3 text-blue-600 dark:text-blue-400">IN {inbound}</span>
            <span className="ml-2 text-green-600 dark:text-green-400">OUT {outbound}</span>
          </div>
          <div className="flex items-center gap-2">
            <Button
              variant="outline"
              size="sm"
              disabled={offset === 0}
              onClick={() => setOffset((o) => Math.max(0, o - limit))}
            >
              Prev
            </Button>
            <Button
              variant="outline"
              size="sm"
              disabled={!hasMore}
              onClick={() => setOffset((o) => o + limit)}
            >
              Next
            </Button>
            <Button
              onClick={handleDownloadCSV}
              variant="outline"
              size="sm"
              disabled={downloading}
              className="flex items-center gap-2"
            >
              <Download className="w-4 h-4" />
              {downloading ? "Downloading…" : "Download CSV"}
            </Button>
          </div>
        </div>
      )}

      {isLoading && (
        <div className="text-center py-8 text-gray-500 dark:text-gray-400 bg-gray-50 dark:bg-gray-800 rounded-lg border border-gray-200 dark:border-gray-700">
          Loading logs…
        </div>
      )}
      {error && (
        <div className="text-center py-8 text-red-600 dark:text-red-400 bg-red-50 dark:bg-red-900/20 rounded-lg border border-red-200 dark:border-red-800">
          Error loading logs. Please try again.
        </div>
      )}

      {/* Virtualized logs list */}
      {logsResponse && rows.length > 0 && (
        <div
          ref={parentRef}
          className="h-[70vh] overflow-y-auto rounded-lg"
        >
          <div
            style={{ height: `${virtualizer.getTotalSize()}px`, position: "relative", width: "100%" }}
          >
            {virtualizer.getVirtualItems().map((virtualRow) => {
              const log = rows[virtualRow.index];
              return (
                <div
                  key={log.id}
                  data-index={virtualRow.index}
                  ref={virtualizer.measureElement}
                  style={{
                    position: "absolute",
                    top: 0,
                    left: 0,
                    width: "100%",
                    transform: `translateY(${virtualRow.start}px)`,
                  }}
                  className="pb-3"
                >
                  <LogRow log={log} />
                </div>
              );
            })}
          </div>
        </div>
      )}

      {logsResponse && rows.length === 0 && !isLoading && (
        <div className="text-center py-8 text-gray-500 dark:text-gray-400 bg-gray-50 dark:bg-gray-800 rounded-lg border border-gray-200 dark:border-gray-700">
          No logs match the current filters. Try widening the date range or clearing filters.
        </div>
      )}
    </div>
  );
}

function DirectionBadge({ direction }: { direction: "IN" | "OUT" }) {
  return direction === "IN" ? (
    <Badge variant="secondary" className="bg-blue-100 text-blue-800">
      <ArrowUpDown className="w-3 h-3 mr-1 rotate-180" /> IN
    </Badge>
  ) : (
    <Badge variant="secondary" className="bg-green-100 text-green-800">
      <ArrowUpDown className="w-3 h-3 mr-1" /> OUT
    </Badge>
  );
}

function LogRow({ log }: { log: LogEntry }) {
  const payload = log.payload;
  let body: React.ReactNode;
  if (!payload) {
    body = <span className="text-gray-500 dark:text-gray-400">No payload</span>;
  } else if (Array.isArray(payload) && payload.length >= 4) {
    const [msgType, msgId, action, actualPayload] = payload;
    const kind = msgType === 2 ? "Call" : msgType === 3 ? "CallResult" : msgType === 4 ? "CallError" : "Unknown";
    // The 4th element is usually an object, but can be an array or primitive on
    // malformed/non-standard frames — guard before treating it as a record.
    const isRecord = typeof actualPayload === "object" && actualPayload !== null;
    const hasContent = isRecord ? Object.keys(actualPayload).length > 0 : actualPayload != null;
    body = (
      <div className="space-y-2">
        <div className="flex items-center gap-2 text-xs">
          <Badge variant="outline" className="text-xs">{kind}</Badge>
          <span className="font-medium text-gray-900 dark:text-gray-100">{String(action)}</span>
          <span className="text-gray-600 dark:text-gray-300 font-mono text-xs">ID: {String(msgId)}</span>
        </div>
        {hasContent && (
          <pre className="text-xs bg-gray-50 dark:bg-gray-900 border border-gray-200 dark:border-gray-600 p-3 rounded overflow-x-auto max-w-2xl text-gray-900 dark:text-gray-100">
            {JSON.stringify(actualPayload, null, 2)}
          </pre>
        )}
      </div>
    );
  } else {
    body = (
      <pre className="text-xs bg-gray-50 dark:bg-gray-900 border border-gray-200 dark:border-gray-600 p-3 rounded overflow-x-auto max-w-2xl text-gray-900 dark:text-gray-100">
        {JSON.stringify(payload, null, 2)}
      </pre>
    );
  }

  return (
    <div className="border border-gray-200 dark:border-gray-700 rounded-lg p-4 bg-white dark:bg-gray-800 shadow-sm">
      <div className="flex items-start justify-between mb-2">
        <div className="flex items-center gap-2 flex-wrap">
          <DirectionBadge direction={log.direction} />
          <span className="font-medium text-sm text-gray-900 dark:text-gray-100">
            {log.message_type || "Unknown"}
          </span>
          {log.charge_point_id && (
            <span className="text-xs text-gray-500 dark:text-gray-400 font-mono">{log.charge_point_id}</span>
          )}
          {log.status && (
            <Badge variant="outline" className="text-xs">{log.status}</Badge>
          )}
        </div>
        <span className="text-xs text-gray-500 dark:text-gray-400 whitespace-nowrap ml-2">
          {new Date(log.timestamp).toLocaleString()}
        </span>
      </div>
      {log.correlation_id && (
        <div className="text-xs text-gray-500 dark:text-gray-400 mb-2 font-mono">
          Correlation ID: {log.correlation_id}
        </div>
      )}
      <div className="mt-2">{body}</div>
    </div>
  );
}

export default function LogsConsolePage() {
  return (
    <AdminOnly
      fallback={
        <div className="flex items-center justify-center min-h-[400px]">
          <div className="text-center">
            <h2 className="text-2xl font-bold text-gray-900 mb-2">Access Denied</h2>
            <p className="text-gray-600 mb-4">You need administrator privileges to view logs.</p>
            <Link href="/dashboard" className="text-blue-600 hover:text-blue-800">Go to Dashboard →</Link>
          </div>
        </div>
      }
    >
      <div className="space-y-6 p-4 md:p-6">
        <div>
          <h1 className="text-3xl font-bold">Logs Console</h1>
          <p className="text-gray-600 mt-1">
            OCPP message logs across all chargers. Filter by action and charger; the date
            window defaults to the last 24 hours.
          </p>
        </div>
        <Suspense fallback={<div className="text-gray-500">Loading…</div>}>
          <LogsConsoleInner />
        </Suspense>
      </div>
    </AdminOnly>
  );
}
