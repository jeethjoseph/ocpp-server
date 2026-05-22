"use client";

import { formatTariffBare } from "@/lib/utils";
import type { StationWithDistance } from "@/components/StationMap";

export type ConnectorDetail = StationWithDistance["connector_details"][number];

export function ChargerRow({ detail }: { detail: ConnectorDetail }) {
  const { ready_count, in_use_count, out_of_service_count } = detail;
  const dotColor =
    ready_count > 0
      ? "bg-green-500"
      : in_use_count > 0
        ? "bg-amber-500"
        : "bg-red-500";

  const statusParts: string[] = [];
  if (ready_count > 0) statusParts.push(`${ready_count} ready`);
  if (in_use_count > 0) statusParts.push(`${in_use_count} in use`);
  if (out_of_service_count > 0) statusParts.push(`${out_of_service_count} out of service`);
  const statusLine = statusParts.join(" · ") || "Status unknown";

  const tariff = formatTariffBare(detail.min_tariff_all_in, detail.max_tariff_all_in);

  return (
    <div className="p-2 bg-muted/50 rounded space-y-1">
      <div className="flex items-center justify-between">
        <div className="flex items-center space-x-2">
          <div className={`w-2 h-2 rounded-full ${dotColor}`}></div>
          <span className="text-sm font-medium text-foreground">
            {detail.connector_type}
          </span>
          {detail.max_power_kw && (
            <span className="text-xs text-muted-foreground">
              ({detail.max_power_kw}kW)
            </span>
          )}
        </div>
        {tariff && (
          <span className="text-xs font-medium text-foreground">{tariff}*</span>
        )}
      </div>
      <div className="text-xs text-muted-foreground pl-4">{statusLine}</div>
    </div>
  );
}
