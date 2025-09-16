"use client";

import React, { useMemo } from "react";
import {
  LineChart,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  Legend,
  ResponsiveContainer,
} from "recharts";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Activity } from "lucide-react";
import { MeterValue } from "@/types/api";

interface MeterValuesChartProps {
  meterValues: MeterValue[];
  transactionId?: number;
}

interface ChartDataPoint {
  timestamp: string;
  timeDisplay: string;
  reading_kwh: number;
  current?: number;
  voltage?: number;
  power_kw?: number;
  energy_delta?: number;
}

export default function MeterValuesChart({ meterValues, transactionId }: MeterValuesChartProps) {
  const chartData = useMemo(() => {
    if (!meterValues || meterValues.length === 0) return [];

    // Sort by timestamp to ensure proper order
    const sortedValues = [...meterValues].sort((a, b) =>
      new Date(a.created_at).getTime() - new Date(b.created_at).getTime()
    );

    return sortedValues.map((mv, index) => {
      const timestamp = new Date(mv.created_at);
      const timeDisplay = timestamp.toLocaleTimeString('en-IN', {
        timeZone: 'Asia/Kolkata',
        hour: '2-digit',
        minute: '2-digit',
        second: '2-digit'
      });

      // Calculate energy delta from previous reading
      let energy_delta = 0;
      if (index > 0) {
        const prevReading = sortedValues[index - 1].reading_kwh;
        energy_delta = mv.reading_kwh - prevReading;
      }

      return {
        timestamp: mv.created_at,
        timeDisplay,
        reading_kwh: mv.reading_kwh,
        current: mv.current,
        voltage: mv.voltage,
        power_kw: mv.power_kw,
        energy_delta: energy_delta > 0 ? energy_delta : undefined, // Only show positive deltas
      };
    });
  }, [meterValues]);

  // Custom tooltip formatter
  const formatTooltipValue = (value: any, name: string) => {
    if (value === null || value === undefined) return ['--', name];

    switch (name) {
      case 'reading_kwh':
        return [`${Number(value).toFixed(3)} kWh`, 'Energy Reading'];
      case 'current':
        return [`${Number(value).toFixed(1)} A`, 'Current'];
      case 'voltage':
        return [`${Number(value).toFixed(1)} V`, 'Voltage'];
      case 'power_kw':
        return [`${Number(value).toFixed(2)} kW`, 'Power'];
      case 'energy_delta':
        return [`+${Number(value).toFixed(3)} kWh`, 'Energy Consumed'];
      default:
        return [value, name];
    }
  };

  const formatTooltipLabel = (label: string) => {
    // The label comes from timeDisplay, not timestamp, so we need to find the actual timestamp
    const dataPoint = chartData.find(d => d.timeDisplay === label);
    if (!dataPoint) return label;

    const date = new Date(dataPoint.timestamp);
    if (isNaN(date.getTime())) return label;

    return date.toLocaleString('en-IN', {
      timeZone: 'Asia/Kolkata',
      year: 'numeric',
      month: 'short',
      day: 'numeric',
      hour: '2-digit',
      minute: '2-digit',
      second: '2-digit'
    });
  };

  if (!chartData || chartData.length === 0) {
    return (
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <Activity className="w-5 h-5" />
            Meter Values Chart
          </CardTitle>
        </CardHeader>
        <CardContent>
          <div className="flex items-center justify-center h-64 text-muted-foreground">
            No meter data available for this transaction
          </div>
        </CardContent>
      </Card>
    );
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <Activity className="w-5 h-5" />
          Meter Values Chart
          {transactionId && (
            <span className="text-sm font-normal text-muted-foreground">
              (Transaction #{transactionId})
            </span>
          )}
        </CardTitle>
        <p className="text-sm text-muted-foreground">
          Real-time meter readings showing energy consumption, current, voltage, and power over time
        </p>
      </CardHeader>
      <CardContent>
        <div className="h-96 w-full">
          <ResponsiveContainer width="100%" height="100%">
            <LineChart data={chartData} margin={{ top: 20, right: 30, left: 20, bottom: 60 }}>
              <CartesianGrid strokeDasharray="3 3" className="opacity-30" />
              <XAxis
                dataKey="timeDisplay"
                angle={-45}
                textAnchor="end"
                height={80}
                fontSize={12}
                interval="preserveStartEnd"
              />
              <YAxis
                yAxisId="energy"
                orientation="left"
                fontSize={12}
                label={{ value: 'Energy (kWh)', angle: -90, position: 'insideLeft' }}
              />
              <YAxis
                yAxisId="electrical"
                orientation="right"
                fontSize={12}
                label={{ value: 'Current (A) / Voltage (V) / Power (kW)', angle: 90, position: 'insideRight' }}
              />
              <Tooltip
                formatter={formatTooltipValue}
                labelFormatter={formatTooltipLabel}
                contentStyle={{
                  backgroundColor: 'hsl(var(--background))',
                  border: '1px solid hsl(var(--border))',
                  borderRadius: '6px',
                }}
              />
              <Legend />

              {/* Energy reading - primary axis */}
              <Line
                yAxisId="energy"
                type="monotone"
                dataKey="reading_kwh"
                stroke="#3b82f6"
                strokeWidth={3}
                dot={{ fill: '#3b82f6', strokeWidth: 2, r: 4 }}
                name="Energy Reading"
              />

              {/* Current */}
              {chartData.some(d => d.current !== null && d.current !== undefined) && (
                <Line
                  yAxisId="electrical"
                  type="monotone"
                  dataKey="current"
                  stroke="#10b981"
                  strokeWidth={1.5}
                  dot={{ fill: '#10b981', strokeWidth: 1, r: 3 }}
                  connectNulls={false}
                  name="Current (A)"
                />
              )}

              {/* Voltage */}
              {chartData.some(d => d.voltage !== null && d.voltage !== undefined) && (
                <Line
                  yAxisId="electrical"
                  type="monotone"
                  dataKey="voltage"
                  stroke="#f59e0b"
                  strokeWidth={1.5}
                  dot={{ fill: '#f59e0b', strokeWidth: 1, r: 3 }}
                  connectNulls={false}
                  name="Voltage (V)"
                />
              )}

              {/* Power */}
              {chartData.some(d => d.power_kw !== null && d.power_kw !== undefined) && (
                <Line
                  yAxisId="electrical"
                  type="monotone"
                  dataKey="power_kw"
                  stroke="#ef4444"
                  strokeWidth={1.5}
                  dot={{ fill: '#ef4444', strokeWidth: 1, r: 3 }}
                  connectNulls={false}
                  name="Power (kW)"
                />
              )}

            </LineChart>
          </ResponsiveContainer>
        </div>

      </CardContent>
    </Card>
  );
}