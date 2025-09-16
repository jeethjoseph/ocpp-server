"use client";

import React, { useState } from "react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Button } from "@/components/ui/button";
import { Calendar, AlertTriangle, ArrowUpDown, Download } from "lucide-react";
import { useChargerLogs, useChargerLogSummary } from "@/lib/queries/logs";
import { LogEntry } from "@/lib/api-services";
import { exportLogsToCSV } from "@/lib/csv-export";

interface ChargerLogsProps {
  chargePointId: string;
  chargerName?: string;
}

export default function ChargerLogs({ chargePointId, chargerName }: ChargerLogsProps) {
  // Set default to last 30 minutes (in local timezone)
  const getDefaultDates = () => {
    const now = new Date();
    const thirtyMinsAgo = new Date(now.getTime() - 30 * 60 * 1000);
    
    // Format for datetime-local input (needs to be in local timezone, not UTC)
    const formatForDateTimeLocal = (date: Date) => {
      const year = date.getFullYear();
      const month = String(date.getMonth() + 1).padStart(2, '0');
      const day = String(date.getDate()).padStart(2, '0');
      const hours = String(date.getHours()).padStart(2, '0');
      const minutes = String(date.getMinutes()).padStart(2, '0');
      
      return `${year}-${month}-${day}T${hours}:${minutes}`;
    };
    
    return {
      start: formatForDateTimeLocal(thirtyMinsAgo),
      end: formatForDateTimeLocal(now)
    };
  };

  const defaults = getDefaultDates();
  const [startDate, setStartDate] = useState(defaults.start);
  const [endDate, setEndDate] = useState(defaults.end);
  const [limit, setLimit] = useState(100);

  // Get log summary for overview
  const { data: summary } = useChargerLogSummary(chargePointId);

  // Get logs with current filters
  const { data: logsResponse, isLoading, error } = useChargerLogs(
    chargePointId,
    {
      start_date: startDate || undefined,
      end_date: endDate || undefined,
      limit: limit,
    }
  );

  const handleExportCSV = () => {
    if (logsResponse?.data && logsResponse.data.length > 0) {
      exportLogsToCSV(logsResponse.data, chargerName || chargePointId);
    }
  };


  const formatTimestamp = (timestamp: string) => {
    return new Date(timestamp).toLocaleString();
  };

  const getDirectionBadge = (direction: "IN" | "OUT") => {
    return direction === "IN" ? (
      <Badge variant="secondary" className="bg-blue-100 text-blue-800">
        <ArrowUpDown className="w-3 h-3 mr-1 rotate-180" />
        IN
      </Badge>
    ) : (
      <Badge variant="secondary" className="bg-green-100 text-green-800">
        <ArrowUpDown className="w-3 h-3 mr-1" />
        OUT
      </Badge>
    );
  };

  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const renderPayload = (payload: Record<string, any> | any[] | null) => {
    if (!payload) return <span className="text-gray-500 dark:text-gray-400">No payload</span>;
    
    // Handle OCPP message format: [message_type, message_id, action, payload]
    if (Array.isArray(payload) && payload.length >= 4) {
      const [msgType, msgId, action, actualPayload] = payload;
      const messageTypeLabel = msgType === 2 ? 'Call' : msgType === 3 ? 'CallResult' : msgType === 4 ? 'CallError' : 'Unknown';
      
      return (
        <div className="space-y-2">
          <div className="flex items-center gap-2 text-xs">
            <Badge variant="outline" className="text-xs border-gray-300 dark:border-gray-600 text-gray-700 dark:text-gray-200 bg-white dark:bg-gray-800">
              {messageTypeLabel}
            </Badge>
            <span className="font-medium text-gray-900 dark:text-gray-100">{action}</span>
            <span className="text-gray-600 dark:text-gray-300 font-mono text-xs">ID: {msgId}</span>
          </div>
          
          {actualPayload && Object.keys(actualPayload).length > 0 && (
            <pre className="text-xs bg-gray-50 dark:bg-gray-900 border border-gray-200 dark:border-gray-600 p-3 rounded overflow-x-auto max-w-md text-gray-900 dark:text-gray-100">
              {JSON.stringify(actualPayload, null, 2)}
            </pre>
          )}
        </div>
      );
    }
    
    // Handle regular payload (dict or other formats)
    return (
      <pre className="text-xs bg-gray-50 dark:bg-gray-900 border border-gray-200 dark:border-gray-600 p-3 rounded overflow-x-auto max-w-md text-gray-900 dark:text-gray-100">
        {JSON.stringify(payload, null, 2)}
      </pre>
    );
  };

  return (
    <Card className="w-full">
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <Calendar className="w-5 h-5" />
          OCPP Logs {chargerName && `- ${chargerName}`}
        </CardTitle>
        
        {summary && (
          <div className="grid grid-cols-2 md:grid-cols-4 gap-4 text-sm bg-gray-50 dark:bg-gray-800 p-4 rounded-lg">
            <div>
              <span className="font-medium text-gray-700 dark:text-gray-300">Total Logs:</span> 
              <span className="text-gray-900 dark:text-gray-100 ml-1">{summary.total_logs}</span>
            </div>
            <div>
              <span className="font-medium text-gray-700 dark:text-gray-300">Inbound:</span> 
              <span className="text-blue-600 dark:text-blue-400 ml-1">{summary.inbound_logs}</span>
            </div>
            <div>
              <span className="font-medium text-gray-700 dark:text-gray-300">Outbound:</span> 
              <span className="text-green-600 dark:text-green-400 ml-1">{summary.outbound_logs}</span>
            </div>
            <div>
              <span className="font-medium text-gray-700 dark:text-gray-300">Date Range:</span>{" "}
              <span className="text-gray-900 dark:text-gray-100 ml-1">
                {summary.oldest_log_date && summary.newest_log_date
                  ? `${new Date(summary.oldest_log_date).toLocaleDateString()} - ${new Date(summary.newest_log_date).toLocaleDateString()}`
                  : "No logs"}
              </span>
            </div>
          </div>
        )}
      </CardHeader>
      
      <CardContent>
        {/* Date Filter Controls */}
        <div className="grid grid-cols-1 md:grid-cols-3 gap-4 mb-6 p-4 bg-white dark:bg-gray-800 border border-gray-200 dark:border-gray-700 rounded-lg">
          <div>
            <Label htmlFor="startDate" className="text-gray-700 dark:text-gray-300">Start Date</Label>
            <Input
              id="startDate"
              type="datetime-local"
              value={startDate}
              onChange={(e) => setStartDate(e.target.value)}
              className="mt-1 bg-white dark:bg-gray-900 border-gray-300 dark:border-gray-600 text-gray-900 dark:text-gray-100"
            />
          </div>
          <div>
            <Label htmlFor="endDate" className="text-gray-700 dark:text-gray-300">End Date</Label>
            <Input
              id="endDate"
              type="datetime-local"
              value={endDate}
              onChange={(e) => setEndDate(e.target.value)}
              className="mt-1 bg-white dark:bg-gray-900 border-gray-300 dark:border-gray-600 text-gray-900 dark:text-gray-100"
            />
          </div>
          <div>
            <Label htmlFor="limit" className="text-gray-700 dark:text-gray-300">Limit (max 10,000)</Label>
            <Input
              id="limit"
              type="number"
              min="1"
              max="10000"
              value={limit}
              onChange={(e) => setLimit(Math.min(10000, Math.max(1, parseInt(e.target.value) || 100)))}
              className="mt-1 bg-white dark:bg-gray-900 border-gray-300 dark:border-gray-600 text-gray-900 dark:text-gray-100"
            />
          </div>
        </div>

        {/* Warning Message */}
        {logsResponse?.message && (
          <div className="mb-4 p-3 bg-yellow-50 dark:bg-yellow-900/20 border border-yellow-200 dark:border-yellow-800 rounded-lg flex items-start gap-2">
            <AlertTriangle className="w-5 h-5 text-yellow-600 dark:text-yellow-400 mt-0.5" />
            <div className="text-sm text-yellow-800 dark:text-yellow-200">
              <strong>Note:</strong> {logsResponse.message}
            </div>
          </div>
        )}

        {/* Results Summary */}
        {logsResponse && (
          <div className="mb-4 flex items-center justify-between bg-gray-50 dark:bg-gray-800 p-3 rounded-lg border border-gray-200 dark:border-gray-700">
            <div className="text-sm text-gray-600 dark:text-gray-400">
              <strong className="text-gray-900 dark:text-gray-100">
                Showing {logsResponse.data.length} of {logsResponse.total} logs
              </strong>
              {logsResponse.has_more && <span className="text-blue-600 dark:text-blue-400"> (more available)</span>}
            </div>
            {logsResponse.data.length > 0 && (
              <Button
                onClick={handleExportCSV}
                variant="outline"
                size="sm"
                className="flex items-center gap-2"
              >
                <Download className="w-4 h-4" />
                Export CSV
              </Button>
            )}
          </div>
        )}

        {/* Loading State */}
        {isLoading && (
          <div className="text-center py-8 text-gray-500 dark:text-gray-400 bg-gray-50 dark:bg-gray-800 rounded-lg border border-gray-200 dark:border-gray-700">
            Loading logs...
          </div>
        )}

        {/* Error State */}
        {error && (
          <div className="text-center py-8 text-red-600 dark:text-red-400 bg-red-50 dark:bg-red-900/20 rounded-lg border border-red-200 dark:border-red-800">
            Error loading logs. Please try again.
          </div>
        )}

        {/* Logs List */}
        {logsResponse && logsResponse.data.length > 0 && (
          <div className="h-96 w-full border border-gray-200 dark:border-gray-700 rounded-md overflow-y-auto bg-white dark:bg-gray-900">
            <div className="p-4 space-y-3">
              {logsResponse.data.map((log: LogEntry) => (
                <div
                  key={log.id}
                  className="border border-gray-200 dark:border-gray-700 rounded-lg p-4 bg-white dark:bg-gray-800 hover:bg-gray-50 dark:hover:bg-gray-700 transition-colors shadow-sm"
                >
                  <div className="flex items-start justify-between mb-3">
                    <div className="flex items-center gap-2 flex-wrap">
                      {getDirectionBadge(log.direction)}
                      <span className="font-medium text-sm text-gray-900 dark:text-gray-100">
                        {log.message_type || "Unknown Message"}
                      </span>
                      {log.status && (
                        <Badge variant="outline" className="text-xs border-gray-300 dark:border-gray-600 text-gray-700 dark:text-gray-300">
                          {log.status}
                        </Badge>
                      )}
                    </div>
                    <span className="text-xs text-gray-500 dark:text-gray-400 whitespace-nowrap ml-2">
                      {formatTimestamp(log.timestamp)}
                    </span>
                  </div>
                  
                  {log.correlation_id && (
                    <div className="text-xs text-gray-500 dark:text-gray-400 mb-3 font-mono">
                      Correlation ID: {log.correlation_id}
                    </div>
                  )}
                  
                  <div className="mt-3">
                    {renderPayload(log.payload)}
                  </div>
                </div>
              ))}
            </div>
          </div>
        )}

        {/* Empty State */}
        {logsResponse && logsResponse.data.length === 0 && (
          <div className="text-center py-8 text-gray-500 dark:text-gray-400 bg-gray-50 dark:bg-gray-800 rounded-lg border border-gray-200 dark:border-gray-700">
            No logs found for the specified criteria. Try adjusting your date range or search parameters.
          </div>
        )}
      </CardContent>
    </Card>
  );
}