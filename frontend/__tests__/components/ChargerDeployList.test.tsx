/**
 * Component tests for `ChargerDeployList`. Verifies same-version chargers are
 * auto-excluded (disabled + badged) while eligible chargers are selectable.
 */
import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { ChargerDeployList } from "@/components/firmware/ChargerDeployList";
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

describe("ChargerDeployList", () => {
  const eligible = charger({ id: 1, name: "CP-Eligible", firmware_version: "1.4.0" });
  const sameVersion = charger({ id: 2, name: "CP-Current", firmware_version: "1.5.0" });

  it("auto-excludes a charger already on the target version", () => {
    render(
      <ChargerDeployList
        chargers={[eligible, sameVersion]}
        targetVersion="1.5.0"
        stationName={() => "Station One"}
        selected={new Set()}
        onToggle={vi.fn()}
      />,
    );

    // The same-version charger is badged and its checkbox disabled.
    expect(screen.getByText("already on 1.5.0")).toBeInTheDocument();
    expect(screen.getByLabelText("Select CP-Current")).toBeDisabled();

    // The eligible charger is selectable.
    expect(screen.getByLabelText("Select CP-Eligible")).not.toBeDisabled();
  });

  it("fires onToggle for an eligible charger, and disables the same-version one", () => {
    const onToggle = vi.fn();
    render(
      <ChargerDeployList
        chargers={[eligible, sameVersion]}
        targetVersion="1.5.0"
        stationName={() => "Station One"}
        selected={new Set()}
        onToggle={onToggle}
      />,
    );

    fireEvent.click(screen.getByLabelText("Select CP-Eligible"));
    expect(onToggle).toHaveBeenCalledWith(1);

    // The same-version checkbox is disabled, so it cannot be selected in a real
    // browser. (jsdom does not enforce `disabled` for programmatic clicks, so we
    // assert the attribute rather than the click outcome.)
    expect(screen.getByLabelText("Select CP-Current")).toBeDisabled();
  });

  it("renders an empty state when there are no chargers", () => {
    render(
      <ChargerDeployList
        chargers={[]}
        targetVersion="1.5.0"
        stationName={() => "Station One"}
        selected={new Set()}
        onToggle={vi.fn()}
      />,
    );
    expect(screen.getByText("No chargers match.")).toBeInTheDocument();
  });
});
