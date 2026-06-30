/**
 * Smoke test for the admin transaction detail page. Mocks the data hook, the
 * route params, and the AdminOnly gate so we can render the page with a
 * representative QR session (refund + customer_vpa) and assert the key fields
 * render: session status, refund amount, and the UPI ID.
 */
import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import type { TransactionDetail } from "@/types/api";

// AdminOnly wraps the page in a role gate that reads auth context; render its
// children directly so the test doesn't need a Clerk/role provider.
vi.mock("@/components/RoleWrapper", () => ({
  AdminOnly: ({ children }: { children: React.ReactNode }) => <>{children}</>,
}));

vi.mock("next/navigation", () => ({
  useParams: () => ({ id: "42" }),
}));

const qrSession: TransactionDetail = {
  transaction: {
    id: 42,
    user_id: 7,
    charger_id: 3,
    energy_consumed_kwh: 5.25,
    start_time: "2026-06-01T10:00:00Z",
    end_time: "2026-06-01T10:45:00Z",
    transaction_status: "COMPLETED",
    created_at: "2026-06-01T10:00:00Z",
    updated_at: "2026-06-01T10:45:00Z",
  },
  user: { id: 7, full_name: "Jane Driver", email: "jane@example.com" },
  charger: { id: 3, name: "CP-3", charge_point_string_id: "CP3-XYZ" },
  meter_values: [],
  wallet_transactions: [],
  funding_source: "QR",
  payment_status: "REFUNDED",
  settlement_status: "SETTLED",
  refund_speed: "instant",
  refund_amount: 12.5,
  customer_vpa: "jane@upi",
};

vi.mock("@/lib/queries/transactions", () => ({
  useAdminTransaction: () => ({
    data: qrSession,
    isLoading: false,
    error: null,
    refetch: vi.fn(),
  }),
}));

import AdminTransactionDetailPage from "@/app/admin/transactions/[id]/page";

describe("AdminTransactionDetailPage", () => {
  it("renders status, refund amount and UPI ID for a QR session", () => {
    render(<AdminTransactionDetailPage />);

    // Session status badge
    expect(screen.getByText("COMPLETED")).toBeInTheDocument();
    // Refund amount (₹12.50)
    expect(screen.getByText("₹12.50")).toBeInTheDocument();
    // UPI ID (customer_vpa)
    expect(screen.getByText("jane@upi")).toBeInTheDocument();
    // QR funding source — appears as both a badge and the funding-source value.
    expect(screen.getAllByText("QR").length).toBeGreaterThan(0);
  });
});
