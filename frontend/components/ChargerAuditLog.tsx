"use client";

import React, { useState } from "react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Shield, ChevronLeft, ChevronRight } from "lucide-react";
import { useChargerTimeline } from "@/lib/queries/logs";
import { AuditLogEntry } from "@/lib/api-services";

interface ChargerAuditLogProps {
  chargePointId: string;
  chargerName?: string;
}

const ACTOR_TYPES = ["", "admin", "system", "ocpp", "webhook", "user"] as const;
const ACTION_OPTIONS = [
  "",
  "charger.connected",
  "charger.disconnected",
  "charger.connection_rejected",
  "charger.created",
  "charger.updated",
  "charger.deleted",
  "charger.availability_changed",
  "charger.reset",
  "charger.status_changed",
  "charger.force_stopped",
  "transaction.status_changed",
  "transaction.suspended",
  "transaction.suspended_timeout",
  "transaction.resumed",
  "transaction.force_stopped",
] as const;

const actorTypeBadge = (actorType: string) => {
  const styles: Record<string, string> = {
    admin: "bg-purple-100 text-purple-800 dark:bg-purple-900/30 dark:text-purple-300",
    system: "bg-gray-100 text-gray-800 dark:bg-gray-800 dark:text-gray-300",
    ocpp: "bg-blue-100 text-blue-800 dark:bg-blue-900/30 dark:text-blue-300",
    webhook: "bg-orange-100 text-orange-800 dark:bg-orange-900/30 dark:text-orange-300",
    user: "bg-green-100 text-green-800 dark:bg-green-900/30 dark:text-green-300",
  };
  return (
    <Badge variant="secondary" className={styles[actorType] || styles.system}>
      {actorType}
    </Badge>
  );
};

const actionLabel = (action: string) => {
  const parts = action.split(".");
  const verb = parts[parts.length - 1];
  const styles: Record<string, string> = {
    connected: "bg-green-100 text-green-800 dark:bg-green-900/30 dark:text-green-300",
    disconnected: "bg-red-100 text-red-800 dark:bg-red-900/30 dark:text-red-300",
    connection_rejected: "bg-yellow-100 text-yellow-800 dark:bg-yellow-900/30 dark:text-yellow-300",
    created: "bg-blue-100 text-blue-800 dark:bg-blue-900/30 dark:text-blue-300",
    updated: "bg-indigo-100 text-indigo-800 dark:bg-indigo-900/30 dark:text-indigo-300",
    deleted: "bg-red-100 text-red-800 dark:bg-red-900/30 dark:text-red-300",
    reset: "bg-orange-100 text-orange-800 dark:bg-orange-900/30 dark:text-orange-300",
    availability_changed: "bg-teal-100 text-teal-800 dark:bg-teal-900/30 dark:text-teal-300",
    status_changed: "bg-amber-100 text-amber-800 dark:bg-amber-900/30 dark:text-amber-300",
    force_stopped: "bg-red-100 text-red-800 dark:bg-red-900/30 dark:text-red-300",
    suspended: "bg-yellow-100 text-yellow-800 dark:bg-yellow-900/30 dark:text-yellow-300",
    suspended_timeout: "bg-red-100 text-red-800 dark:bg-red-900/30 dark:text-red-300",
    resumed: "bg-green-100 text-green-800 dark:bg-green-900/30 dark:text-green-300",
  };
  return (
    <Badge variant="outline" className={styles[verb] || "border-gray-300 dark:border-gray-600"}>
      {action}
    </Badge>
  );
};

const formatForDateTimeLocal = (date: Date) => {
  const year = date.getFullYear();
  const month = String(date.getMonth() + 1).padStart(2, "0");
  const day = String(date.getDate()).padStart(2, "0");
  const hours = String(date.getHours()).padStart(2, "0");
  const minutes = String(date.getMinutes()).padStart(2, "0");
  return `${year}-${month}-${day}T${hours}:${minutes}`;
};

export default function ChargerAuditLog({ chargePointId, chargerName }: ChargerAuditLogProps) {
  const now = new Date();
  const twentyFourHoursAgo = new Date(now.getTime() - 24 * 60 * 60 * 1000);

  const [page, setPage] = useState(1);
  const [startDate, setStartDate] = useState(formatForDateTimeLocal(twentyFourHoursAgo));
  const [endDate, setEndDate] = useState(formatForDateTimeLocal(now));
  const [actionFilter, setActionFilter] = useState("");
  const [actorTypeFilter, setActorTypeFilter] = useState("");
  const limit = 20;

  const { data: auditData, isLoading, error } = useChargerTimeline(
    chargePointId,
    {
      page,
      limit,
      action: actionFilter || undefined,
      actor_type: actorTypeFilter || undefined,
      start_date: startDate ? new Date(startDate).toISOString() : undefined,
      end_date: endDate ? new Date(endDate).toISOString() : undefined,
    }
  );

  const totalPages = auditData ? Math.ceil(auditData.total / limit) : 0;

  const formatTimestamp = (ts: string) => new Date(ts).toLocaleString();

  const handleFilterChange = () => {
    setPage(1);
  };

  return (
    <Card className="w-full">
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <Shield className="w-5 h-5" />
          Audit Log {chargerName && `- ${chargerName}`}
        </CardTitle>
      </CardHeader>

      <CardContent>
        {/* Filter Controls */}
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4 mb-6 p-4 bg-gray-50 dark:bg-gray-900/50 border border-gray-200 dark:border-gray-700 rounded-lg">
          <div>
            <Label htmlFor="auditStartDate" className="text-gray-700 dark:text-gray-300">Start Date</Label>
            <Input
              id="auditStartDate"
              type="datetime-local"
              value={startDate}
              onChange={(e) => { setStartDate(e.target.value); handleFilterChange(); }}
              className="mt-1 bg-white dark:bg-gray-900 border-gray-300 dark:border-gray-600 text-gray-900 dark:text-gray-100"
            />
          </div>
          <div>
            <Label htmlFor="auditEndDate" className="text-gray-700 dark:text-gray-300">End Date</Label>
            <Input
              id="auditEndDate"
              type="datetime-local"
              value={endDate}
              onChange={(e) => { setEndDate(e.target.value); handleFilterChange(); }}
              className="mt-1 bg-white dark:bg-gray-900 border-gray-300 dark:border-gray-600 text-gray-900 dark:text-gray-100"
            />
          </div>
          <div>
            <Label htmlFor="actionFilter" className="text-gray-700 dark:text-gray-300">Action</Label>
            <select
              id="actionFilter"
              value={actionFilter}
              onChange={(e) => { setActionFilter(e.target.value); handleFilterChange(); }}
              className="mt-1 w-full h-9 rounded-md border border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-800 px-3 text-sm text-gray-900 dark:text-gray-100 [&>option]:bg-white [&>option]:dark:bg-gray-800 [&>option]:dark:text-gray-100"
            >
              <option value="">All actions</option>
              {ACTION_OPTIONS.filter(Boolean).map((a) => (
                <option key={a} value={a}>{a}</option>
              ))}
            </select>
          </div>
          <div>
            <Label htmlFor="actorTypeFilter" className="text-gray-700 dark:text-gray-300">Actor Type</Label>
            <select
              id="actorTypeFilter"
              value={actorTypeFilter}
              onChange={(e) => { setActorTypeFilter(e.target.value); handleFilterChange(); }}
              className="mt-1 w-full h-9 rounded-md border border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-800 px-3 text-sm text-gray-900 dark:text-gray-100 [&>option]:bg-white [&>option]:dark:bg-gray-800 [&>option]:dark:text-gray-100"
            >
              <option value="">All actors</option>
              {ACTOR_TYPES.filter(Boolean).map((t) => (
                <option key={t} value={t}>{t}</option>
              ))}
            </select>
          </div>
        </div>

        {/* Loading */}
        {isLoading && (
          <div className="text-center py-8 text-gray-500 dark:text-gray-400 bg-gray-50 dark:bg-gray-800 rounded-lg border border-gray-200 dark:border-gray-700">
            Loading audit log...
          </div>
        )}

        {/* Error */}
        {error && (
          <div className="text-center py-8 text-red-600 dark:text-red-400 bg-red-50 dark:bg-red-900/20 rounded-lg border border-red-200 dark:border-red-800">
            Error loading audit log. Please try again.
          </div>
        )}

        {/* Results */}
        {auditData && auditData.data.length > 0 && (
          <>
            <div className="mb-4 text-sm text-gray-600 dark:text-gray-400">
              <strong className="text-gray-900 dark:text-gray-100">
                {auditData.total} event{auditData.total !== 1 ? "s" : ""}
              </strong>
              {" "}(page {page} of {totalPages})
            </div>

            <div className="border border-gray-200 dark:border-gray-700 rounded-md overflow-hidden">
              <table className="w-full text-sm text-gray-900 dark:text-gray-100">
                <thead className="bg-gray-100 dark:bg-gray-800/80">
                  <tr>
                    <th className="text-left px-4 py-2 font-medium text-gray-700 dark:text-gray-300">Time</th>
                    <th className="text-left px-4 py-2 font-medium text-gray-700 dark:text-gray-300">Actor</th>
                    <th className="text-left px-4 py-2 font-medium text-gray-700 dark:text-gray-300">Action</th>
                    <th className="text-left px-4 py-2 font-medium text-gray-700 dark:text-gray-300">Details</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-gray-200 dark:divide-gray-700">
                  {auditData.data.map((entry: AuditLogEntry) => (
                    <tr key={entry.id} className="bg-white dark:bg-gray-900/30 hover:bg-gray-50 dark:hover:bg-gray-800/50">
                      <td className="px-4 py-3 whitespace-nowrap text-xs text-gray-500 dark:text-gray-400">
                        {formatTimestamp(entry.created_at)}
                      </td>
                      <td className="px-4 py-3">
                        <div className="flex flex-col gap-1">
                          {actorTypeBadge(entry.actor_type)}
                          {entry.actor_email && (
                            <span className="text-xs text-gray-500 dark:text-gray-400 truncate max-w-[150px]">
                              {entry.actor_email}
                            </span>
                          )}
                        </div>
                      </td>
                      <td className="px-4 py-3">
                        {actionLabel(entry.action)}
                      </td>
                      <td className="px-4 py-3">
                        {entry.changes && Object.keys(entry.changes).length > 0 ? (
                          <div className="flex flex-wrap gap-x-3 gap-y-1 text-xs">
                            {Object.entries(entry.changes).map(([key, value]) => (
                              <span key={key} className="text-gray-600 dark:text-gray-400">
                                <span className="font-medium text-gray-700 dark:text-gray-300">{key.replace(/_/g, " ")}:</span>{" "}
                                {typeof value === "object" ? JSON.stringify(value) : String(value)}
                              </span>
                            ))}
                          </div>
                        ) : (
                          <span className="text-xs text-gray-400">-</span>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>

            {/* Pagination */}
            {totalPages > 1 && (
              <div className="flex items-center justify-center gap-2 mt-4">
                <Button
                  variant="outline"
                  size="sm"
                  disabled={page <= 1}
                  onClick={() => setPage((p) => Math.max(1, p - 1))}
                >
                  <ChevronLeft className="w-4 h-4" />
                </Button>
                <span className="text-sm text-gray-600 dark:text-gray-400">
                  {page} / {totalPages}
                </span>
                <Button
                  variant="outline"
                  size="sm"
                  disabled={page >= totalPages}
                  onClick={() => setPage((p) => p + 1)}
                >
                  <ChevronRight className="w-4 h-4" />
                </Button>
              </div>
            )}
          </>
        )}

        {/* Empty */}
        {auditData && auditData.data.length === 0 && (
          <div className="text-center py-8 text-gray-500 dark:text-gray-400 bg-gray-50 dark:bg-gray-800 rounded-lg border border-gray-200 dark:border-gray-700">
            No audit events found for the specified criteria. Try adjusting your filters or date range.
          </div>
        )}
      </CardContent>
    </Card>
  );
}
