# 02 — Gate 2a: Paytm split-settlement commercial + compliance confirmation

Status: ready-for-human

## What to build

Resolve the non-code unknowns that decide whether Paytm's Split Settlement product is even available and viable for our franchisee-payout model, before any technical spike. Runs in parallel with Gate 1.

Paytm Split Settlement exists and architecturally matches our Razorpay Route usage (platform-collects-first, per-vendor accounts, refund splitting, `feePercentage` commission allocation, T+1). But the docs leave three items unresolved that require a conversation with Paytm's KAM/MHD and a compliance review:

- **MID enablement**: Split Settlement must be explicitly enabled on our MID ("Contact MHD/KAM"). Confirm we qualify and can get it enabled.
- **Programmatic onboarding API**: docs read as dashboard-first (bulk upload mentioned). Confirm whether per-franchisee sub-account onboarding + KYC can be done via API, since we onboard franchisees programmatically today (`create_linked_account`). Dashboard-only would be a workflow regression to weigh.
- **TDS handling**: Paytm's split docs don't mention TDS; we settle franchisees net of `tds_amount`. Confirm whether Paytm supports TDS deduction in split, or whether we must handle it ourselves.
- **RBI / disclosure viability**: confirm Paytm's platform-collects-first split is compatible with our RBI disclosure model (`project_rbi_route_disclosure`) for our business category.

## Acceptance criteria

- [ ] Written confirmation of whether Split Settlement can be enabled on our MID (and any eligibility conditions)
- [ ] Answer on programmatic sub-account onboarding + KYC API availability
- [ ] Answer on TDS handling within Paytm split settlement
- [ ] Compliance sign-off (or blocker) on RBI disclosure viability with Paytm's model
- [ ] Findings recorded so Gate 2b (technical spike) and the Go/No-Go decision can consume them

## Blocked by

- None - can start immediately (runs parallel to Gate 1)
