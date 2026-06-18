/**
 * Component tests for `BulkDeployResult`. Verifies the three-bucket summary and
 * that skipped / failed reasons are surfaced.
 */
import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { BulkDeployResult } from "@/components/firmware/BulkDeployResult";
import type { BulkUpdateResult } from "@/types/api";

describe("BulkDeployResult", () => {
  it("renders the three-bucket summary and per-charger reasons", () => {
    const result: BulkUpdateResult = {
      success: [
        { charger_id: 1, charger_name: "CP-1", update_id: 11 },
        { charger_id: 2, charger_name: "CP-2", update_id: 12 },
      ],
      skipped: [
        { charger_id: 3, charger_name: "CP-3", reason: "already on 1.5.0" },
      ],
      failed: [
        { charger_id: 4, charger_name: "CP-4", reason: "Charger not found" },
      ],
    };
    render(<BulkDeployResult result={result} />);

    expect(screen.getByText("2 scheduled · 1 skipped · 1 failed")).toBeInTheDocument();
    expect(screen.getByText(/already on 1.5.0/)).toBeInTheDocument();
    expect(screen.getByText(/Charger not found/)).toBeInTheDocument();
    expect(screen.getByText("CP-3")).toBeInTheDocument();
    expect(screen.getByText("CP-4")).toBeInTheDocument();
  });

  it("falls back to a charger id label when name is missing", () => {
    const result: BulkUpdateResult = {
      success: [],
      skipped: [{ charger_id: 7, reason: "in-flight, attempt 3/5" }],
      failed: [],
    };
    render(<BulkDeployResult result={result} />);

    expect(screen.getByText("Charger #7")).toBeInTheDocument();
    expect(screen.getByText(/in-flight, attempt 3\/5/)).toBeInTheDocument();
  });
});
