/**
 * Component tests for `TariffBreakdownPreview`. Verifies the admin tariff
 * form's live preview renders the two-row breakdown (base rate + GST) of a
 * GST-inclusive, gateway-EXCLUSIVE per-kWh rate. The gateway fee is billed
 * separately and is NOT part of the tariff. See ADR 0026.
 */
import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { TariffBreakdownPreview } from "@/components/TariffBreakdownPreview";

describe("TariffBreakdownPreview", () => {
  it("renders the base-rate and GST rows for a valid GST-inclusive value", () => {
    render(<TariffBreakdownPreview value="25" gstPercent={18} />);

    expect(screen.getByText(/Base rate \(rate_per_kwh\):/i)).toBeInTheDocument();
    expect(screen.getByText(/GST \(18%\):/i)).toBeInTheDocument();

    // ₹25 incl. GST at 18% → rate = 25 / 1.18 ≈ 21.1864, GST ≈ 3.8136.
    expect(screen.getByText("₹21.1864/kWh")).toBeInTheDocument();
    expect(screen.getByText("₹3.8136/kWh")).toBeInTheDocument();
  });

  it("does NOT render a synthetic gateway-fee percent row", () => {
    render(<TariffBreakdownPreview value="25" gstPercent={18} />);
    // The old "Gateway fee (2%):" per-kWh line item is gone (ADR 0026).
    expect(screen.queryByText(/Gateway fee \(\d+%\):/i)).not.toBeInTheDocument();
  });

  it("notes that the gateway fee is billed separately", () => {
    render(<TariffBreakdownPreview value="25" gstPercent={18} />);
    expect(
      screen.getByText(/Gateway fee \(Razorpay actual\) billed separately/i),
    ).toBeInTheDocument();
  });

  it("renders the configured GST percent in the label", () => {
    render(<TariffBreakdownPreview value="25" gstPercent={28} />);
    expect(screen.getByText(/GST \(28%\):/i)).toBeInTheDocument();
  });

  it("renders nothing for an empty input value", () => {
    const { container } = render(
      <TariffBreakdownPreview value="" gstPercent={18} />,
    );
    expect(container).toBeEmptyDOMElement();
  });

  it("renders nothing for a non-numeric input value", () => {
    const { container } = render(
      <TariffBreakdownPreview value="abc" gstPercent={18} />,
    );
    expect(container).toBeEmptyDOMElement();
  });

  it("renders nothing for a zero or negative input value", () => {
    const { container: zero } = render(
      <TariffBreakdownPreview value="0" gstPercent={18} />,
    );
    expect(zero).toBeEmptyDOMElement();

    const { container: neg } = render(
      <TariffBreakdownPreview value="-5" gstPercent={18} />,
    );
    expect(neg).toBeEmptyDOMElement();
  });
});
