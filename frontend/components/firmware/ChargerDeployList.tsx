"use client";

import React from "react";
import { Badge } from "@/components/ui/badge";
import { isChargerEligible } from "@/lib/firmware-deploy";
import type { Charger } from "@/types/api";

interface ChargerDeployListProps {
  chargers: Charger[];
  targetVersion: string;
  stationName: (stationId: number) => string;
  selected: Set<number>;
  onToggle: (id: number) => void;
}

/**
 * Scrollable, checkbox-driven charger list for the bulk deploy picker. Chargers
 * already on the target version are disabled and badged "already on <version>"
 * (auto-excluded). Online/offline is shown but does not gate selection — offline
 * chargers are valid targets and update when they reconnect.
 */
export function ChargerDeployList({ chargers, targetVersion, stationName, selected, onToggle }: ChargerDeployListProps) {
  if (chargers.length === 0) {
    return <div className="px-3 py-6 text-center text-sm text-muted-foreground">No chargers match.</div>;
  }

  return (
    <div className="max-h-72 overflow-y-auto border rounded-md divide-y">
      {chargers.map((c) => {
        const eligible = isChargerEligible(c, targetVersion);
        return (
          <label
            key={c.id}
            className={`flex items-center gap-3 px-3 py-2 text-sm cursor-pointer ${eligible ? "" : "opacity-50 cursor-not-allowed"}`}
          >
            <input
              type="checkbox"
              aria-label={`Select ${c.name}`}
              disabled={!eligible}
              checked={selected.has(c.id)}
              onChange={() => onToggle(c.id)}
            />
            <div className="flex-1 min-w-0">
              <div className="font-medium truncate">{c.name}</div>
              <div className="text-xs text-muted-foreground truncate">
                {stationName(c.station_id)} · {c.firmware_version || "unknown"}
              </div>
            </div>
            {eligible ? (
              <Badge variant={c.connection_status ? "outline" : "secondary"}>
                {c.connection_status ? "online" : "offline"}
              </Badge>
            ) : (
              <Badge variant="secondary">already on {targetVersion}</Badge>
            )}
          </label>
        );
      })}
    </div>
  );
}
