/**
 * Component tests for `RecentFirmwareUpdates`. Verifies that a FAILED update's
 * `error_message` is surfaced inline, while a FAILED update without a message
 * (and non-failed updates) render no error line.
 */
import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { RecentFirmwareUpdates } from "@/components/firmware/RecentFirmwareUpdates";
import type { FirmwareUpdate } from "@/types/api";

const baseUpdate: FirmwareUpdate = {
  id: 1,
  charger_id: 10,
  firmware_file_id: 5,
  status: "FAILED",
  download_url: "https://example.com/fw",
  initiated_at: "2026-06-01T00:00:00Z",
  attempt_count: 5,
  firmware_version: "1.5.0",
};

describe("RecentFirmwareUpdates", () => {
  it("shows the error_message for a FAILED update", () => {
    const failed: FirmwareUpdate = {
      ...baseUpdate,
      error_message: "retry budget exhausted (5 attempts): charger offline",
    };
    render(<RecentFirmwareUpdates updates={[failed]} />);

    expect(screen.getByText("FAILED")).toBeInTheDocument();
    expect(screen.getByText(/retry budget exhausted/)).toBeInTheDocument();
  });

  it("renders no error line for a FAILED update without a message", () => {
    const failedNoMsg: FirmwareUpdate = { ...baseUpdate, error_message: undefined };
    const { container } = render(<RecentFirmwareUpdates updates={[failedNoMsg]} />);

    expect(screen.getByText("FAILED")).toBeInTheDocument();
    // No destructive paragraph rendered.
    expect(container.querySelector("p.text-destructive")).toBeNull();
  });

  it("does not show an error line for a non-failed update that carries a message", () => {
    const installed: FirmwareUpdate = {
      ...baseUpdate,
      status: "INSTALLED",
      error_message: "stale reason that should not surface",
    };
    render(<RecentFirmwareUpdates updates={[installed]} />);

    expect(screen.getByText("INSTALLED")).toBeInTheDocument();
    expect(screen.queryByText(/stale reason/)).not.toBeInTheDocument();
  });

  it("excludes PENDING rows from the recent list", () => {
    const pending: FirmwareUpdate = { ...baseUpdate, status: "PENDING" };
    const { container } = render(<RecentFirmwareUpdates updates={[pending]} />);
    expect(container).toBeEmptyDOMElement();
  });
});
