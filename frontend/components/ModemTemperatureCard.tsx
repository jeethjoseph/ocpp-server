"use client";

import { useMemo } from "react";
import {
  CartesianGrid,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { useSignalQuality } from "@/lib/queries/chargers";
import type { SignalQualityListResponse } from "@/types/api";

const STALE_THRESHOLD_MS = 5 * 60 * 1000;

interface ModemTemperatureCardProps {
  chargerId: number;
}

interface ChartPoint {
  t: number;
  label: string;
  temperature: number;
}

/**
 * Modem board temperature, 24h window. Data comes from the same
 * /signal-quality endpoint as RSSI/BER but is plotted on its own card —
 * RSSI history has its own surface and dual-axis muddies both. See
 * ADR 0009 for why this lives alongside signal-quality data.
 */
export default function ModemTemperatureCard({
  chargerId,
}: ModemTemperatureCardProps) {
  const { data, isLoading } = useSignalQuality(chargerId, 24);

  const { points, latestTemp, latestAt } = useMemo(
    () => buildChartData(data),
    [data]
  );

  const isStale =
    latestAt === null || Date.now() - latestAt > STALE_THRESHOLD_MS;

  return (
    <Card>
      <CardHeader className="flex flex-row items-center justify-between">
        <CardTitle>Modem Temperature</CardTitle>
        <LatestReadout
          isLoading={isLoading}
          isStale={isStale}
          value={latestTemp}
          latestAt={latestAt}
        />
      </CardHeader>
      <CardContent>
        {points.length === 0 ? (
          <EmptyState isLoading={isLoading} />
        ) : (
          <ResponsiveContainer width="100%" height={260}>
            <LineChart
              data={points}
              margin={{ top: 8, right: 24, left: 0, bottom: 0 }}
            >
              <CartesianGrid strokeDasharray="3 3" stroke="#e5e7eb" />
              <XAxis dataKey="label" tick={{ fontSize: 11 }} minTickGap={32} />
              <YAxis
                tick={{ fontSize: 11 }}
                label={{
                  value: "°C",
                  angle: -90,
                  position: "insideLeft",
                  style: { fontSize: 11 },
                }}
                domain={["auto", "auto"]}
              />
              <Tooltip
                formatter={(v: number | undefined) =>
                  v == null ? ["—", "Temp"] : [`${v.toFixed(1)} °C`, "Temp"]
                }
                labelFormatter={(label) => `Sample at ${label ?? ""}`}
              />
              <Line
                type="monotone"
                dataKey="temperature"
                stroke="#ef4444"
                strokeWidth={2}
                dot={false}
                isAnimationActive={false}
              />
            </LineChart>
          </ResponsiveContainer>
        )}
      </CardContent>
    </Card>
  );
}

function buildChartData(data: SignalQualityListResponse | undefined): {
  points: ChartPoint[];
  latestTemp: number | null;
  latestAt: number | null;
} {
  if (!data) {
    return { points: [], latestTemp: null, latestAt: null };
  }
  const points: ChartPoint[] = [];
  for (const row of data.data) {
    if (row.temperature_celsius == null) continue;
    const t = new Date(row.created_at).getTime();
    points.push({
      t,
      label: new Date(t).toLocaleTimeString([], {
        hour: "2-digit",
        minute: "2-digit",
      }),
      temperature: row.temperature_celsius,
    });
  }
  points.sort((a, b) => a.t - b.t);

  const latestTemp = data.latest_temperature_celsius ?? null;
  const latestAt = points.length ? points[points.length - 1]!.t : null;
  return { points, latestTemp, latestAt };
}

function LatestReadout({
  isLoading,
  isStale,
  value,
  latestAt,
}: {
  isLoading: boolean;
  isStale: boolean;
  value: number | null;
  latestAt: number | null;
}) {
  if (isLoading) {
    return (
      <span className="text-sm text-muted-foreground">Loading…</span>
    );
  }
  if (value == null) {
    return (
      <span className="text-sm text-muted-foreground">
        No temperature reported yet
      </span>
    );
  }
  return (
    <div className="text-right">
      <p className={`text-2xl font-bold ${isStale ? "text-muted-foreground" : ""}`}>
        {value.toFixed(1)}°C
      </p>
      <p className="text-xs text-muted-foreground">
        {isStale
          ? "Stale — last seen "
          : "Latest "}
        {latestAt ? new Date(latestAt).toLocaleTimeString() : "—"}
      </p>
    </div>
  );
}

function EmptyState({ isLoading }: { isLoading: boolean }) {
  return (
    <div className="flex h-[260px] items-center justify-center text-sm text-muted-foreground">
      {isLoading
        ? "Loading temperature history…"
        : "No temperature samples in the last 24 hours."}
    </div>
  );
}
