"use client";

import React from "react";
import type { BulkUpdateResult } from "@/types/api";

interface BulkDeployResultProps {
  result: BulkUpdateResult;
}

function bucketLabel(entry: { charger_name?: string; charger_id: number }): string {
  return entry.charger_name || `Charger #${entry.charger_id}`;
}

/**
 * Result view for a bulk firmware deploy. Shows a one-line summary plus the
 * skipped / failed breakdowns expanded (the rows an admin needs the reason
 * for). The success bucket collapses to a count.
 */
export function BulkDeployResult({ result }: BulkDeployResultProps) {
  const { success, skipped, failed } = result;

  return (
    <div className="space-y-3 text-sm">
      <p className="font-medium">
        {success.length} scheduled · {skipped.length} skipped · {failed.length} failed
      </p>

      {skipped.length > 0 && (
        <div>
          <p className="text-xs font-medium text-muted-foreground mb-1">Skipped</p>
          <ul className="space-y-1">
            {skipped.map((s) => (
              <li key={`skip-${s.charger_id}`} className="text-xs">
                <span className="font-medium">{bucketLabel(s)}</span>
                <span className="text-muted-foreground"> — {s.reason}</span>
              </li>
            ))}
          </ul>
        </div>
      )}

      {failed.length > 0 && (
        <div>
          <p className="text-xs font-medium text-destructive mb-1">Failed</p>
          <ul className="space-y-1">
            {failed.map((f) => (
              <li key={`fail-${f.charger_id}`} className="text-xs">
                <span className="font-medium">{bucketLabel(f)}</span>
                <span className="text-destructive"> — {f.reason}</span>
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}
