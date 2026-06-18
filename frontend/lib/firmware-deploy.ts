/**
 * Pure selection helpers for the bulk firmware deploy picker.
 *
 * Kept free of React so the eligibility / select-all-within-filter rules can be
 * unit-tested directly. The picker auto-excludes chargers already on the target
 * version, and "select all" applies only to chargers matching the active
 * station filter — never the literal fleet.
 */
import type { Charger } from "@/types/api";

export type StationFilter = number | "all";

/** A charger is eligible for deploy only if it isn't already on the target version. */
export function isChargerEligible(charger: Charger, targetVersion: string): boolean {
  return charger.firmware_version !== targetVersion;
}

/** Chargers matching the active station filter ("all" = no station restriction). */
export function filterChargersByStation(chargers: Charger[], station: StationFilter): Charger[] {
  if (station === "all") return chargers;
  return chargers.filter((c) => c.station_id === station);
}

/**
 * Ids that "select all" should select: eligible chargers within the active
 * station filter. This is the count shown next to the select-all control.
 */
export function eligibleIdsForFilter(
  chargers: Charger[],
  targetVersion: string,
  station: StationFilter,
): number[] {
  return filterChargersByStation(chargers, station)
    .filter((c) => isChargerEligible(c, targetVersion))
    .map((c) => c.id);
}
