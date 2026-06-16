"use client";

import React, { useEffect, useMemo, useState } from "react";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { useChargers, useStations } from "@/lib/queries/chargers";
import { useBulkUpdate } from "@/lib/queries/firmware";
import {
  eligibleIdsForFilter,
  filterChargersByStation,
  type StationFilter,
} from "@/lib/firmware-deploy";
import { ChargerDeployList } from "./ChargerDeployList";
import { BulkDeployResult } from "./BulkDeployResult";
import type { BulkUpdateResult, FirmwareFile } from "@/types/api";

interface BulkDeployDialogProps {
  firmware: FirmwareFile | null;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}

type Step = "pick" | "review" | "result";

export function BulkDeployDialog({ firmware, open, onOpenChange }: BulkDeployDialogProps) {
  const [step, setStep] = useState<Step>("pick");
  const [stationFilter, setStationFilter] = useState<StationFilter>("all");
  const [search, setSearch] = useState("");
  const [selected, setSelected] = useState<Set<number>>(new Set());
  const [result, setResult] = useState<BulkUpdateResult | null>(null);

  // The admin chargers list endpoint caps `limit` at 100 (rejects higher with a
  // 422). 100 covers the current fleet; revisit with pagination if it grows past that.
  const { data: chargersData } = useChargers({ limit: 100 });
  const { data: stationsData } = useStations({ limit: 200 });
  const bulkUpdate = useBulkUpdate();

  const chargers = useMemo(() => chargersData?.data ?? [], [chargersData]);
  const stations = useMemo(() => stationsData?.data ?? [], [stationsData]);
  const targetVersion = firmware?.version ?? "";

  // Reset to a clean pick step whenever the dialog (re)opens for a firmware.
  useEffect(() => {
    if (open) {
      setStep("pick");
      setStationFilter("all");
      setSearch("");
      setSelected(new Set());
      setResult(null);
    }
  }, [open, firmware?.id]);

  const stationName = (id: number) => stations.find((s) => s.id === id)?.name ?? `Station #${id}`;

  const visible = useMemo(() => {
    const byStation = filterChargersByStation(chargers, stationFilter);
    const q = search.trim().toLowerCase();
    if (!q) return byStation;
    return byStation.filter(
      (c) => c.name.toLowerCase().includes(q) || c.charge_point_string_id.toLowerCase().includes(q),
    );
  }, [chargers, stationFilter, search]);

  const eligibleInFilter = useMemo(
    () => eligibleIdsForFilter(chargers, targetVersion, stationFilter),
    [chargers, targetVersion, stationFilter],
  );
  const allEligibleSelected =
    eligibleInFilter.length > 0 && eligibleInFilter.every((id) => selected.has(id));

  const toggleOne = (id: number) =>
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(id)) {
        next.delete(id);
      } else {
        next.add(id);
      }
      return next;
    });

  const toggleAll = () =>
    setSelected((prev) => {
      const next = new Set(prev);
      eligibleInFilter.forEach((id) => {
        if (allEligibleSelected) {
          next.delete(id);
        } else {
          next.add(id);
        }
      });
      return next;
    });

  const selectedStationCount = useMemo(
    () => new Set(chargers.filter((c) => selected.has(c.id)).map((c) => c.station_id)).size,
    [chargers, selected],
  );

  const handleDeploy = async () => {
    if (!firmware) return;
    const res = await bulkUpdate.mutateAsync({
      firmware_file_id: firmware.id,
      charger_ids: Array.from(selected),
    });
    setResult(res);
    setStep("result");
  };

  if (!firmware) return null;

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-2xl">
        <DialogHeader>
          <DialogTitle>Deploy firmware {firmware.version}</DialogTitle>
          <DialogDescription>
            {step === "pick" && "Select the chargers to deploy this firmware version to."}
            {step === "review" && "Review the deployment before scheduling."}
            {step === "result" && "Deployment scheduled."}
          </DialogDescription>
        </DialogHeader>

        {step === "pick" && (
          <div className="space-y-3">
            <div className="flex gap-2">
              <Select
                value={String(stationFilter)}
                onValueChange={(v) => setStationFilter(v === "all" ? "all" : Number(v))}
              >
                <SelectTrigger className="w-48">
                  <SelectValue placeholder="All stations" />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="all">All stations</SelectItem>
                  {stations.map((s) => (
                    <SelectItem key={s.id} value={String(s.id)}>
                      {s.name}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
              <Input
                placeholder="Search charger…"
                value={search}
                onChange={(e) => setSearch(e.target.value)}
              />
            </div>

            <label className="flex items-center gap-2 text-sm">
              <input
                type="checkbox"
                checked={allEligibleSelected}
                onChange={toggleAll}
                disabled={eligibleInFilter.length === 0}
              />
              Select all ({eligibleInFilter.length})
            </label>

            <ChargerDeployList
              chargers={visible}
              targetVersion={targetVersion}
              stationName={stationName}
              selected={selected}
              onToggle={toggleOne}
            />
          </div>
        )}

        {step === "review" && (
          <div className="text-sm">
            <p>
              Deploy <span className="font-medium">{firmware.version}</span> to{" "}
              <span className="font-medium">{selected.size}</span> charger(s) across{" "}
              {selectedStationCount} station(s).
            </p>
            <p className="text-muted-foreground mt-2 text-xs">
              Chargers already on {firmware.version} or with an in-flight update are skipped automatically.
            </p>
          </div>
        )}

        {step === "result" && result && <BulkDeployResult result={result} />}

        <DialogFooter>
          {step === "pick" && (
            <>
              <Button variant="outline" onClick={() => onOpenChange(false)}>
                Cancel
              </Button>
              <Button disabled={selected.size === 0} onClick={() => setStep("review")}>
                Next ({selected.size})
              </Button>
            </>
          )}
          {step === "review" && (
            <>
              <Button variant="outline" onClick={() => setStep("pick")}>
                Back
              </Button>
              <Button disabled={bulkUpdate.isPending} onClick={handleDeploy}>
                {bulkUpdate.isPending ? "Deploying…" : `Deploy to ${selected.size} charger(s)`}
              </Button>
            </>
          )}
          {step === "result" && <Button onClick={() => onOpenChange(false)}>Done</Button>}
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
