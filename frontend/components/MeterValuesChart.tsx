"use client";

import React, { useMemo, useState } from "react";
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
import { Button } from "@/components/ui/button";
import { Activity, ChevronLeft, ChevronRight, Zap, Gauge, Power, Battery } from "lucide-react";
import { MeterValue } from "@/types/api";

interface MeterValuesChartProps {
  meterValues: MeterValue[];
  transactionId?: number;
}

type ChartView = 'energy' | 'current' | 'voltage' | 'power';

const CHART_CONFIGS = {
  energy: {
    title: 'Energy Consumption',
    icon: Battery,
    dataKey: 'reading_kwh',
    color: '#3b82f6',
    unit: 'kWh',
    label: 'Energy (kWh)',
    description: 'Total energy consumed over time',
  },
  current: {
    title: 'Current',
    icon: Zap,
    dataKey: 'current',
    color: '#10b981',
    unit: 'A',
    label: 'Current (A)',
    description: 'Electrical current flowing through the charger',
  },
  voltage: {
    title: 'Voltage',
    icon: Gauge,
    dataKey: 'voltage',
    color: '#f59e0b',
    unit: 'V',
    label: 'Voltage (V)',
    description: 'Supply voltage level',
  },
  power: {
    title: 'Power',
    icon: Power,
    dataKey: 'power_kw',
    color: '#ef4444',
    unit: 'kW',
    label: 'Power (kW)',
    description: 'Instantaneous power consumption',
  },
};

export default function MeterValuesChart({ meterValues, transactionId }: MeterValuesChartProps) {
  const [currentView, setCurrentView] = useState<ChartView>('energy');

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
        energy_delta: energy_delta > 0 ? energy_delta : undefined,
      };
    });
  }, [meterValues]);

  // Check which metrics have data
  const availableMetrics = useMemo(() => {
    return {
      energy: chartData.length > 0,
      current: chartData.some(d => d.current !== null && d.current !== undefined),
      voltage: chartData.some(d => d.voltage !== null && d.voltage !== undefined),
      power: chartData.some(d => d.power_kw !== null && d.power_kw !== undefined),
    };
  }, [chartData]);

  const currentConfig = CHART_CONFIGS[currentView];
  const Icon = currentConfig.icon;

  // Get ordered views that have data
  const viewOrder: ChartView[] = ['energy', 'current', 'voltage', 'power'];
  const availableViews = viewOrder.filter(view => availableMetrics[view]);

  const currentIndex = availableViews.indexOf(currentView);

  const goToPrevious = () => {
    const newIndex = currentIndex > 0 ? currentIndex - 1 : availableViews.length - 1;
    setCurrentView(availableViews[newIndex]);
  };

  const goToNext = () => {
    const newIndex = currentIndex < availableViews.length - 1 ? currentIndex + 1 : 0;
    setCurrentView(availableViews[newIndex]);
  };

  // Custom tooltip formatter
  //eslint-disable-next-line @typescript-eslint/no-explicit-any
  const formatTooltipValue = (value: any) => {
    if (value === null || value === undefined) return '--';

    switch (currentView) {
      case 'energy':
        return `${Number(value).toFixed(3)} kWh`;
      case 'current':
        return `${Number(value).toFixed(1)} A`;
      case 'voltage':
        return `${Number(value).toFixed(1)} V`;
      case 'power':
        return `${Number(value).toFixed(2)} kW`;
      default:
        return value;
    }
  };

  const formatTooltipLabel = (label: string) => {
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

  // Calculate statistics for current view
  const stats = useMemo(() => {
    if (chartData.length === 0) return null;

    const dataKey = currentConfig.dataKey as keyof typeof chartData[0];
    const values = chartData
      .map(d => d[dataKey])
      .filter(v => v !== null && v !== undefined) as number[];

    if (values.length === 0) return null;

    const min = Math.min(...values);
    const max = Math.max(...values);
    const avg = values.reduce((sum, v) => sum + v, 0) / values.length;
    const latest = values[values.length - 1];

    return { min, max, avg, latest };
  }, [chartData, currentConfig.dataKey]);

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
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <Icon className="w-5 h-5" />
            <div>
              <CardTitle className="flex items-center gap-2">
                {currentConfig.title}
                {transactionId && (
                  <span className="text-sm font-normal text-muted-foreground">
                    (Transaction #{transactionId})
                  </span>
                )}
              </CardTitle>
              <p className="text-sm text-muted-foreground mt-1">
                {currentConfig.description}
              </p>
            </div>
          </div>

          {/* Navigation controls */}
          <div className="flex items-center gap-2">
            <Button
              variant="outline"
              size="icon"
              onClick={goToPrevious}
              disabled={availableViews.length <= 1}
            >
              <ChevronLeft className="h-4 w-4" />
            </Button>

            {/* View indicators */}
            <div className="flex gap-1.5">
              {availableViews.map((view) => (
                <button
                  key={view}
                  onClick={() => setCurrentView(view)}
                  className={`w-2 h-2 rounded-full transition-all ${
                    view === currentView
                      ? 'bg-primary w-6'
                      : 'bg-muted hover:bg-muted-foreground/30'
                  }`}
                  title={CHART_CONFIGS[view].title}
                />
              ))}
            </div>

            <Button
              variant="outline"
              size="icon"
              onClick={goToNext}
              disabled={availableViews.length <= 1}
            >
              <ChevronRight className="h-4 w-4" />
            </Button>
          </div>
        </div>

        {/* Statistics */}
        {stats && (
          <div className="grid grid-cols-4 gap-4 mt-4">
            <div className="text-center">
              <div className="text-xs text-muted-foreground">Latest</div>
              <div className="text-lg font-semibold" style={{ color: currentConfig.color }}>
                {formatTooltipValue(stats.latest)}
              </div>
            </div>
            <div className="text-center">
              <div className="text-xs text-muted-foreground">Average</div>
              <div className="text-lg font-semibold">
                {formatTooltipValue(stats.avg)}
              </div>
            </div>
            <div className="text-center">
              <div className="text-xs text-muted-foreground">Min</div>
              <div className="text-lg font-semibold">
                {formatTooltipValue(stats.min)}
              </div>
            </div>
            <div className="text-center">
              <div className="text-xs text-muted-foreground">Max</div>
              <div className="text-lg font-semibold">
                {formatTooltipValue(stats.max)}
              </div>
            </div>
          </div>
        )}
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
                fontSize={12}
                label={{ value: currentConfig.label, angle: -90, position: 'insideLeft' }}
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

              <Line
                type="monotone"
                dataKey={currentConfig.dataKey}
                stroke={currentConfig.color}
                strokeWidth={3}
                dot={{ fill: currentConfig.color, strokeWidth: 2, r: 4 }}
                connectNulls={false}
                name={currentConfig.title}
              />
            </LineChart>
          </ResponsiveContainer>
        </div>
      </CardContent>
    </Card>
  );
}
