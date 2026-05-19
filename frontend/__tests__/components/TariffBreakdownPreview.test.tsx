/**
 * Component tests for `TariffBreakdownPreview`. Verifies the admin tariff
 * form's live preview renders the expected back-derivation breakdown.
 */
import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { TariffBreakdownPreview } from "@/components/TariffBreakdownPreview";

describe("TariffBreakdownPreview", () => {
  it("renders all three breakdown rows for a valid all-in value", () => {
    render(
      <TariffBreakdownPreview
        value="25"
        feePercent={2}
        gstPercent={18}
      />,
    );

    // The three label rows are all present.
    expect(screen.getByText(/Base rate \(rate_per_kwh\):/i)).toBeInTheDocument();
    expect(screen.getByText(/Gateway fee \(2%\):/i)).toBeInTheDocument();
    expect(screen.getByText(/GST \(18%\):/i)).toBeInTheDocument();

    // The computed figures match the worked example in CONTEXT.md.
    // (Implementation rounds to 4dp; ₹25 → rate ≈ 20.7627, gateway = 0.5, GST ≈ 3.7373)
    expect(screen.getByText("₹20.7627/kWh")).toBeInTheDocument();
    expect(screen.getByText("₹0.5000/kWh")).toBeInTheDocument();
    expect(screen.getByText("₹3.7373/kWh")).toBeInTheDocument();
  });

  it("renders the configured fee and GST percents in the labels", () => {
    // Verifies the L1 fix: percents come from props, not hardcoded strings.
    render(
      <TariffBreakdownPreview
        value="25"
        feePercent={3}
        gstPercent={28}
      />,
    );
    expect(screen.getByText(/Gateway fee \(3%\):/i)).toBeInTheDocument();
    expect(screen.getByText(/GST \(28%\):/i)).toBeInTheDocument();
  });

  it("renders nothing for an empty input value", () => {
    const { container } = render(
      <TariffBreakdownPreview value="" feePercent={2} gstPercent={18} />,
    );
    expect(container).toBeEmptyDOMElement();
  });

  it("renders nothing for a non-numeric input value", () => {
    const { container } = render(
      <TariffBreakdownPreview value="abc" feePercent={2} gstPercent={18} />,
    );
    expect(container).toBeEmptyDOMElement();
  });

  it("renders nothing for a zero or negative input value", () => {
    const { container: zero } = render(
      <TariffBreakdownPreview value="0" feePercent={2} gstPercent={18} />,
    );
    expect(zero).toBeEmptyDOMElement();

    const { container: neg } = render(
      <TariffBreakdownPreview value="-5" feePercent={2} gstPercent={18} />,
    );
    expect(neg).toBeEmptyDOMElement();
  });
});
