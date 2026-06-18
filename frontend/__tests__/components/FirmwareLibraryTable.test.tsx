/**
 * Component tests for `FirmwareLibraryTable`. Verifies that the firmware
 * `description` (release notes) is surfaced via an expandable detail row, and
 * that rows without a description degrade gracefully (no expand affordance).
 */
import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { FirmwareLibraryTable } from "@/components/firmware/FirmwareLibraryTable";
import type { FirmwareFile } from "@/types/api";

const baseFirmware: FirmwareFile = {
  id: 1,
  version: "1.5.0",
  filename: "1.5.0_continuous_read.bin",
  file_size: 5 * 1024 * 1024,
  checksum: "abcdef1234567890",
  uploaded_by_id: 1,
  created_at: "2026-06-01T00:00:00Z",
  is_active: true,
};

describe("FirmwareLibraryTable", () => {
  it("reveals the release notes when the row is expanded", () => {
    const withDescription: FirmwareFile = {
      ...baseFirmware,
      description: "Fixes modem reconnect loop\nImproves OTA download retry",
    };
    render(<FirmwareLibraryTable firmwareFiles={[withDescription]} onDelete={vi.fn()} />);

    // Collapsed by default — the description text is not yet rendered.
    expect(screen.queryByText(/Fixes modem reconnect loop/)).not.toBeInTheDocument();

    // The expand affordance is present and toggling it reveals the notes.
    const toggle = screen.getByLabelText("Show release notes");
    fireEvent.click(toggle);
    expect(screen.getByText(/Fixes modem reconnect loop/)).toBeInTheDocument();
    expect(screen.getByText("Release notes")).toBeInTheDocument();
  });

  it("shows no expand affordance for a firmware with no description", () => {
    render(<FirmwareLibraryTable firmwareFiles={[baseFirmware]} onDelete={vi.fn()} />);

    expect(screen.queryByLabelText("Show release notes")).not.toBeInTheDocument();
    expect(screen.queryByText("Release notes")).not.toBeInTheDocument();
    // The row itself still renders.
    expect(screen.getByText("1.5.0")).toBeInTheDocument();
  });

  it("treats a whitespace-only description as empty", () => {
    const blankDescription: FirmwareFile = { ...baseFirmware, description: "   " };
    render(<FirmwareLibraryTable firmwareFiles={[blankDescription]} onDelete={vi.fn()} />);

    expect(screen.queryByLabelText("Show release notes")).not.toBeInTheDocument();
  });
});
