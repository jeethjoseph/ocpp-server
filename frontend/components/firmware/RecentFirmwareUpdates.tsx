"use client";

import React from "react";
import { Badge } from "@/components/ui/badge";
import type { FirmwareUpdate } from "@/types/api";

interface RecentFirmwareUpdatesProps {
  updates: FirmwareUpdate[];
  limit?: number;
}

/**
 * Compact "Recent Updates" list shown on the charger detail page. Excludes the
 * live PENDING row (rendered separately) and surfaces the `error_message` of a
 * FAILED update inline so an admin sees *why* it failed without an API/log dive.
 */
export function RecentFirmwareUpdates({ updates, limit = 3 }: RecentFirmwareUpdatesProps) {
  const recent = updates.filter((u) => u.status !== "PENDING").slice(0, limit);
  if (recent.length === 0) return null;

  return (
    <div className="space-y-2">
      {recent.map((update) => (
        <div key={update.id} className="text-xs">
          <div className="flex items-center">
            <Badge
              variant={
                update.status === "INSTALLED"
                  ? "outline"
                  : update.status === "CANCELLED"
                  ? "secondary"
                  : update.status.includes("FAILED")
                  ? "destructive"
                  : "default"
              }
              className="text-xs"
            >
              {update.status}
            </Badge>
            {update.firmware_version && <span className="ml-2">{update.firmware_version}</span>}
            <span className="ml-2 text-muted-foreground">
              {new Date(update.initiated_at).toLocaleDateString()}
            </span>
          </div>
          {update.status === "FAILED" && update.error_message && (
            <p className="mt-1 text-destructive whitespace-pre-wrap break-words">
              {update.error_message}
            </p>
          )}
        </div>
      ))}
    </div>
  );
}
