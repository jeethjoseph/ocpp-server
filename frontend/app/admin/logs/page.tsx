"use client";

import React, { Suspense, useCallback, useEffect, useMemo, useState } from "react";
import { useRouter, useSearchParams, usePathname } from "next/navigation";
import Link from "next/link";
import { AdminOnly } from "@/components/RoleWrapper";
import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Button } from "@/components/ui/button";
import { AlertTriangle, ArrowUpDown, Download } from "lucide-react";
import { useLogs } from "@/lib/queries/logs";
import { LogEntry } from "@/lib/api-services";
import { OCPP_ACTIONS } from "@/lib/ocpp-actions";
import { exportLogsToCSV } from "@/lib/csv-export";
import ChargerCombobox from "@/components/ChargerCombobox";

type Direction = "ALL" | "IN" | "OUT";

// datetime-local <-> Date helpers (inputs are in local tz; the API wants ISO+tz).
function toDateTimeLocal(date: Date): string {
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}T${pad(date.getHours())}:${pad(date.getMinutes())}`;
}

function LogsConsoleInner() {
  const router = useRouter();
  const pathname = usePathname();
  const searchParams = useSearchParams();

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
    Number(searchParams.get("limit")) || 100
  );
  const [direction, setDirection] = useState<Direction>(
    (searchParams.get("dir") as Direction) || "ALL"
  );
  const [errorsOnly, setErrorsOnly] = useState<boolean>(searchParams.get("errors") === "1");

  // --- write state back to the URL (shareable) ---
  useEffect(() => {
    const sp = new URLSearchParams();
    if (charger) sp.set("charger", charger);
    if (actions.length) sp.set("actions", actions.join(","));
    if (startLocal) sp.set("start", startLocal);
    if (endLocal) sp.set("end", endLocal);
    if (limit !== 100) sp.set("limit", String(limit));
    if (direction !== "ALL") sp.set("dir", direction);
    if (errorsOnly) sp.set("errors", "1");
    const qs = sp.toString();
    router.replace(qs ? `${pathname}?${qs}` : pathname, { scroll: false });
  }, [charger, actions, startLocal, endLocal, limit, direction, errorsOnly, pathname, router]);

  // --- server query (charger + action + date window, all server-side) ---
  const { data: logsResponse, isLoading, error } = useLogs({
    charge_point_id: charger,
    message_type: actions.length ? actions : undefined,
    start_date: startLocal ? new Date(startLocal).toISOString() : undefined,
    end_date: endLocal ? new Date(endLocal).toISOString() : undefined,
    limit,
  });

  const fetched = useMemo(() => logsResponse?.data ?? [], [logsResponse]);

  // --- in-memory refinement: direction + errors-only ---
  const visible = useMemo(
    () =>
      fetched.filter((log) => {
        if (direction !== "ALL" && log.direction !== direction) return false;
        if (errorsOnly && (log.status ?? "SUCCESS") === "SUCCESS") return false;
        return true;
      }),
    [fetched, direction, errorsOnly]
  );

  const inboundFetched = useMemo(() => fetched.filter((l) => l.direction === "IN").length, [fetched]);
  const outboundFetched = fetched.length - inboundFetched;
  const refined = visible.length !== fetched.length;

  const toggleAction = useCallback((action: string) => {
    setActions((prev) =>
      prev.includes(action) ? prev.filter((a) => a !== action) : [...prev, action]
    );
  }, []);

  const handleExportCSV = () => {
    if (visible.length > 0) exportLogsToCSV(visible, charger || "logs-console");
  };

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
            <Label htmlFor="limit" className="text-xs font-medium text-gray-600 dark:text-gray-300">Limit</Label>
            <Input
              id="limit"
              type="number"
              min={1}
              max={100000}
              value={limit}
              onChange={(e) => setLimit(Math.min(100000, Math.max(1, parseInt(e.target.value) || 100)))}
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

        {/* In-memory refinements */}
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

      {/* Results summary */}
      {logsResponse && (
        <div className="flex items-center justify-between bg-gray-50 dark:bg-gray-800 p-3 rounded-lg border border-gray-200 dark:border-gray-700">
          <div className="text-sm text-gray-600 dark:text-gray-400">
            <strong className="text-gray-900 dark:text-gray-100">
              Showing {visible.length}
              {refined ? ` of ${fetched.length} fetched` : ""}
            </strong>{" "}
            <span>
              ({logsResponse.total} match on server
              {logsResponse.has_more ? ", more beyond the fetched window" : ""})
            </span>
            <span className="ml-3 text-blue-600 dark:text-blue-400">IN {inboundFetched}</span>
            <span className="ml-2 text-green-600 dark:text-green-400">OUT {outboundFetched}</span>
          </div>
          {visible.length > 0 && (
            <Button onClick={handleExportCSV} variant="outline" size="sm" className="flex items-center gap-2">
              <Download className="w-4 h-4" />
              Export CSV
            </Button>
          )}
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

      {/* Logs list */}
      {logsResponse && visible.length > 0 && (
        <div className="space-y-3">
          {visible.map((log) => (
            <LogRow key={log.id} log={log} />
          ))}
        </div>
      )}

      {logsResponse && visible.length === 0 && !isLoading && (
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
    body = (
      <div className="space-y-2">
        <div className="flex items-center gap-2 text-xs">
          <Badge variant="outline" className="text-xs">{kind}</Badge>
          <span className="font-medium text-gray-900 dark:text-gray-100">{String(action)}</span>
          <span className="text-gray-600 dark:text-gray-300 font-mono text-xs">ID: {String(msgId)}</span>
        </div>
        {actualPayload && Object.keys(actualPayload).length > 0 && (
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
