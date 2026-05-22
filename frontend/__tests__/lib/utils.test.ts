/**
 * Tests for the synthetic-fee math helpers in `lib/utils.ts`.
 *
 * `breakdownAllInTariff` is the frontend mirror of the backend's
 * `back_derive_rate_per_kwh` (services/tariff_utils.py). The fixtures here
 * mirror the backend's `test_back_derive_30_at_18_pct_gst_and_2_pct_fee` so
 * the two implementations stay in sync.
 */
import { describe, it, expect } from "vitest";
import {
  formatTariffRangeAllIn,
  breakdownAllInTariff,
} from "@/lib/utils";

describe("formatTariffRangeAllIn", () => {
  it("returns N/A when both bounds are null", () => {
    expect(formatTariffRangeAllIn(null, null)).toBe("N/A");
  });

  it("collapses to a single value when bounds match", () => {
    expect(formatTariffRangeAllIn(25.0, 25.0)).toBe("₹25.00/kWh (all-inclusive)");
  });

  it("collapses near-matching bounds within 0.005", () => {
    expect(formatTariffRangeAllIn(25.001, 25.003)).toBe("₹25.00/kWh (all-inclusive)");
  });

  it("renders a range when bounds differ", () => {
    expect(formatTariffRangeAllIn(20.0, 30.0)).toBe(
      "₹20.00–₹30.00/kWh (all-inclusive)",
    );
  });

  it("falls back to the non-null value when one bound is missing", () => {
    expect(formatTariffRangeAllIn(null, 25.0)).toBe("₹25.00/kWh (all-inclusive)");
    expect(formatTariffRangeAllIn(25.0, null)).toBe("₹25.00/kWh (all-inclusive)");
  });
});

describe("breakdownAllInTariff", () => {
  it("matches the CONTEXT.md worked example: ₹25 all-in at 18% GST + 2% fee", () => {
    const result = breakdownAllInTariff(25);
    expect(result).not.toBeNull();
    // Backend's test_back_derive_30_at_18_pct_gst_and_2_pct_fee asserts the
    // same shape at ₹30; this is the ₹25 equivalent from CONTEXT.md.
    // rate_per_kwh = 25 × 0.98 / 1.18 = 20.7627...
    expect(result!.ratePerKwh).toBeCloseTo(20.7627, 3);
    expect(result!.gatewayPerKwh).toBeCloseTo(0.5, 3);
    expect(result!.gstPerKwh).toBeCloseTo(3.7373, 3);
  });

  it("matches the ₹30 worked example from the backend tests", () => {
    const result = breakdownAllInTariff(30);
    expect(result).not.toBeNull();
    // Backend asserts rate=24.9153 (4dp ROUND_HALF_UP).
    expect(result!.ratePerKwh).toBeCloseTo(24.9153, 3);
    expect(result!.gatewayPerKwh).toBeCloseTo(0.6, 3);
    expect(result!.gstPerKwh).toBeCloseTo(4.4847, 3);
  });

  it("matches the ₹100 example (round-number sanity)", () => {
    const result = breakdownAllInTariff(100);
    expect(result).not.toBeNull();
    // 100 × 0.98 = 98 (post-gateway, incl GST); / 1.18 = 83.0508
    expect(result!.ratePerKwh).toBeCloseTo(83.0508, 3);
    expect(result!.gatewayPerKwh).toBeCloseTo(2.0, 3);
    expect(result!.gstPerKwh).toBeCloseTo(14.9492, 3);
  });

  it("components sum back to the input within rounding tolerance", () => {
    const result = breakdownAllInTariff(17.7);
    expect(result).not.toBeNull();
    const sum = result!.ratePerKwh + result!.gatewayPerKwh + result!.gstPerKwh;
    expect(sum).toBeCloseTo(17.7, 4);
  });

  it("honors custom GST and fee percents", () => {
    // 28% GST + 2% fee → rate = 25 × 0.98 / 1.28 = 19.1406
    const result = breakdownAllInTariff(25, 28, 2);
    expect(result).not.toBeNull();
    expect(result!.ratePerKwh).toBeCloseTo(19.1406, 3);
  });

  it("returns null for non-finite input", () => {
    expect(breakdownAllInTariff(NaN)).toBeNull();
    expect(breakdownAllInTariff(Infinity)).toBeNull();
  });

  it("returns null for zero or negative input", () => {
    expect(breakdownAllInTariff(0)).toBeNull();
    expect(breakdownAllInTariff(-5)).toBeNull();
  });
});
