/**
 * Tests for the tariff math helpers in `lib/utils.ts`.
 *
 * `breakdownGstIncludedTariff` backs GST out of a GST-inclusive,
 * gateway-EXCLUSIVE per-kWh rate (ADR 0026). There is no gateway component in
 * the tariff anymore — the Razorpay fee is a separate variable line.
 */
import { describe, it, expect } from "vitest";
import {
  formatTariffRangeAllIn,
  breakdownGstIncludedTariff,
  isSocketCharger,
} from "@/lib/utils";

describe("isSocketCharger", () => {
  const c = (t: string) => [{ connector_type: t }];
  it("treats Type2 (the standard untethered AC socket) as a socket", () => {
    expect(isSocketCharger(c("Type2"))).toBe(true);
  });
  it("treats Socket / Type1 / domestic as sockets (case + spacing insensitive)", () => {
    expect(isSocketCharger(c("Socket"))).toBe(true);
    expect(isSocketCharger(c("type 1"))).toBe(true);
    expect(isSocketCharger(c("DOMESTIC"))).toBe(true);
  });
  it("treats CCS / CHAdeMO / GB-T (tethered/DC) as NOT sockets", () => {
    expect(isSocketCharger(c("CCS"))).toBe(false);
    expect(isSocketCharger(c("CHAdeMO"))).toBe(false);
    expect(isSocketCharger(c("GB/T"))).toBe(false);
  });
  it("defaults unknown types and empty input to NOT a socket", () => {
    expect(isSocketCharger(c("Frobnicator"))).toBe(false);
    expect(isSocketCharger([])).toBe(false);
    expect(isSocketCharger(undefined)).toBe(false);
  });
  it("is a socket if ANY connector is untethered", () => {
    expect(isSocketCharger([{ connector_type: "CCS" }, { connector_type: "Type2" }])).toBe(true);
  });
});

describe("formatTariffRangeAllIn", () => {
  it("returns N/A when both bounds are null", () => {
    expect(formatTariffRangeAllIn(null, null)).toBe("N/A");
  });

  it("collapses to a single value when bounds match", () => {
    expect(formatTariffRangeAllIn(25.0, 25.0)).toBe("₹25.00/kWh (incl. GST)");
  });

  it("collapses near-matching bounds within 0.005", () => {
    expect(formatTariffRangeAllIn(25.001, 25.003)).toBe("₹25.00/kWh (incl. GST)");
  });

  it("renders a range when bounds differ", () => {
    expect(formatTariffRangeAllIn(20.0, 30.0)).toBe(
      "₹20.00–₹30.00/kWh (incl. GST)",
    );
  });

  it("falls back to the non-null value when one bound is missing", () => {
    expect(formatTariffRangeAllIn(null, 25.0)).toBe("₹25.00/kWh (incl. GST)");
    expect(formatTariffRangeAllIn(25.0, null)).toBe("₹25.00/kWh (incl. GST)");
  });
});

describe("breakdownGstIncludedTariff", () => {
  it("backs GST out of a ₹25 GST-inclusive rate at 18% GST", () => {
    const result = breakdownGstIncludedTariff(25);
    expect(result).not.toBeNull();
    // rate_per_kwh = 25 / 1.18 = 21.1864...; GST = 25 − 21.1864 = 3.8136...
    expect(result!.ratePerKwh).toBeCloseTo(21.1864, 3);
    expect(result!.gstPerKwh).toBeCloseTo(3.8136, 3);
  });

  it("backs GST out of a ₹30 GST-inclusive rate at 18% GST", () => {
    const result = breakdownGstIncludedTariff(30);
    expect(result).not.toBeNull();
    // 30 / 1.18 = 25.4237...; GST = 4.5763...
    expect(result!.ratePerKwh).toBeCloseTo(25.4237, 3);
    expect(result!.gstPerKwh).toBeCloseTo(4.5763, 3);
  });

  it("backs GST out of a ₹100 GST-inclusive rate (round-number sanity)", () => {
    const result = breakdownGstIncludedTariff(100);
    expect(result).not.toBeNull();
    // 100 / 1.18 = 84.7458...; GST = 15.2542...
    expect(result!.ratePerKwh).toBeCloseTo(84.7458, 3);
    expect(result!.gstPerKwh).toBeCloseTo(15.2542, 3);
  });

  it("has no gateway component — the result is two-row only", () => {
    const result = breakdownGstIncludedTariff(25);
    expect(result).not.toBeNull();
    expect(result).not.toHaveProperty("gatewayPerKwh");
    expect(Object.keys(result!).sort()).toEqual(["gstPerKwh", "ratePerKwh"]);
  });

  it("components sum back to the input within rounding tolerance", () => {
    const result = breakdownGstIncludedTariff(17.7);
    expect(result).not.toBeNull();
    const sum = result!.ratePerKwh + result!.gstPerKwh;
    expect(sum).toBeCloseTo(17.7, 4);
  });

  it("honors a custom GST percent", () => {
    // 28% GST → rate = 25 / 1.28 = 19.5313
    const result = breakdownGstIncludedTariff(25, 28);
    expect(result).not.toBeNull();
    expect(result!.ratePerKwh).toBeCloseTo(19.5313, 3);
  });

  it("returns null for non-finite input", () => {
    expect(breakdownGstIncludedTariff(NaN)).toBeNull();
    expect(breakdownGstIncludedTariff(Infinity)).toBeNull();
  });

  it("returns null for zero or negative input", () => {
    expect(breakdownGstIncludedTariff(0)).toBeNull();
    expect(breakdownGstIncludedTariff(-5)).toBeNull();
  });
});
