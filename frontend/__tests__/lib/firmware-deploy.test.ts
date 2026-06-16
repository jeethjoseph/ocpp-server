/**
 * Unit tests for the bulk-deploy selection helpers: eligibility (same-version
 * auto-exclusion) and select-all-within-filter scoping.
 */
import { describe, it, expect } from "vitest";
import {
  isChargerEligible,
  filterChargersByStation,
  eligibleIdsForFilter,
} from "@/lib/firmware-deploy";
import type { Charger } from "@/types/api";

function charger(partial: Partial<Charger>): Charger {
  return {
    id: 0,
    charge_point_string_id: "CP",
    station_id: 1,
    name: "CP",
    latest_status: "Available",
    availability: "Operative",
    connection_status: true,
    created_at: "",
    updated_at: "",
    ...partial,
  } as Charger;
}

const chargers = [
  charger({ id: 1, station_id: 10, firmware_version: "1.4.0" }),
  charger({ id: 2, station_id: 10, firmware_version: "1.5.0" }), // already on target
  charger({ id: 3, station_id: 20, firmware_version: "1.4.0" }),
];

describe("firmware-deploy helpers", () => {
  it("treats a charger already on the target version as ineligible", () => {
    expect(isChargerEligible(chargers[0], "1.5.0")).toBe(true);
    expect(isChargerEligible(chargers[1], "1.5.0")).toBe(false);
  });

  it("filters chargers by station, with 'all' returning everything", () => {
    expect(filterChargersByStation(chargers, 10).map((c) => c.id)).toEqual([1, 2]);
    expect(filterChargersByStation(chargers, "all")).toHaveLength(3);
  });

  it("select-all across all stations excludes the same-version charger", () => {
    expect(eligibleIdsForFilter(chargers, "1.5.0", "all")).toEqual([1, 3]);
  });

  it("select-all within a station filter is scoped to that station", () => {
    // Station 10 has chargers 1 (eligible) and 2 (already on target) → only 1.
    const ids = eligibleIdsForFilter(chargers, "1.5.0", 10);
    expect(ids).toEqual([1]);
    expect(ids).toHaveLength(1);
  });
});
