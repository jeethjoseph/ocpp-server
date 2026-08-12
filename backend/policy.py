# backend/policy.py
"""Git-tracked operational policy values.

These are deliberate business/policy decisions, NOT environment wiring: they
are identical in every environment and changing one should be a reviewed git
diff, not an invisible .env edit. Secrets and per-environment values (hosts,
credentials, feature flags mid-rollout) stay in env vars; policy numbers live
here. See ADR 0027.

Rationale for the split: every incident in the suspend-window area came from
env-var invisibility — MAX_RESUME_GAP_SECONDS silently inverted against the
disconnect window (txn 870, ADR 0022), and a 10x drift between the compose
fallback (180) and the deployed value (1800) that nothing flagged.
"""

# --- Suspend windows: how long a mid-session disconnect waits for reconnect ---
#
# Keyed by the connector's `latching` trait (services.charger_type_service):
# a latching connector (Type2/Type1/CCS/CHAdeMO/GB-T) locks the cable into the
# vehicle inlet, so nobody can unplug or walk off with it while the CSMS link
# is down — the session can safely be held for a long window. An unlatched
# socket (Socket/domestic) gives no evidence about physical state, so it gets
# a short window. Unknown connector types resolve to non-latching (safe side).
#
# Applies to BOTH suspension paths — the disconnect timer AND the post-boot
# timer armed by BootNotification. The post-boot window must never be shorter
# than the window it replaces (the 300s post-boot timer killed 9 sessions
# fleet-wide; ~41% of prod reconnects arrive via BootNotification).
SUSPEND_WINDOW_LATCHED_SECONDS = 43200    # 12 h — captures ~95% of observed Type2 reconnects
SUSPEND_WINDOW_UNLATCHED_SECONDS = 2700   # 45 min — deliberate cable-security tradeoff

# Buffer added on top of a transaction's suspend window to form the
# stale-suspended cutoff used by the backstop sweep and the resume-staleness
# guard. Derived (window + buffer), never configured independently, so the
# guard/sweep can never fire before the primary timer (ADR 0022 invariant).
STALE_SUSPENDED_BUFFER_SECONDS = 60


# --- Franchisee invoice-code blocks: cross-environment collision guard ---
#
# The customer-facing GST Invoice number embeds a franchisee identifier. That
# identifier used to be `Franchisee.id` — a per-database autoincrement — so
# production and staging, which share one GSTIN and one financial year,
# independently minted the same value. It produced two duplicate invoice
# numbers (VL/F2/QR/202627/00001 and /00002, issued to different franchisees
# in each register) and would have produced more: production was three
# franchisees away from minting F5, already live on staging with 878 invoices.
#
# `Franchisee.invoice_code` replaces the primary key in the invoice number. Each
# environment may only mint from its own block, so two databases cannot collide
# without coordinating — no shared counter, no network call, no discipline.
# A CHECK constraint on the column enforces the block; this map is only the
# source the allocator reads.
#
# Blocks are deliberately NOT an environment letter in the invoice number: the
# serial is a Rule 46(b) statutory field and "staging" has no business on a tax
# invoice. Contrast the Charger Code (ADR 0028), which IS env-prefixed because
# it is a display alias with no statutory meaning. Same problem, two mechanisms,
# for that reason.
#
# Staging's block is closed: it has five franchisees, only two of which ever
# issued an invoice, and it will not gain more.
FRANCHISEE_CODE_BLOCKS = {
    "production": (1, 8999),
    "staging": (9000, 9999),
    "development": (9000, 9999),
}

# Reserved for VoltLync-owned stations (`Franchisee` is NULL on the invoice).
VOLTLYNC_OWNED_INVOICE_CODE = "F0000"

# Offset applied to `Franchisee.id` when backfilling existing rows, so a code
# can be read back to the franchisee's old `VL/F{id}/` invoice series. Staging
# keeps the id in the last digits (id 5 -> F9005) precisely so support can
# correlate an old number with a new one without a lookup. Only ever used by
# the backfill; new rows are allocated by scanning the block.
FRANCHISEE_CODE_BACKFILL_OFFSET = {
    "production": 0,      # id 1 -> F0001
    "staging": 9000,      # id 5 -> F9005
    "development": 9000,
}


def franchisee_code_backfill_offset(environment: str) -> int:
    return FRANCHISEE_CODE_BACKFILL_OFFSET.get(
        (environment or "").strip().lower(), FRANCHISEE_CODE_BACKFILL_OFFSET["staging"]
    )


def franchisee_code_block(environment: str) -> tuple[int, int]:
    """Inclusive (low, high) code range this environment may allocate from.

    Unknown environments resolve to the staging block, never production's —
    the same fail-safe direction as ADR 0028's prefix map, so a misconfigured
    box cannot mint a code production might later issue.
    """
    return FRANCHISEE_CODE_BLOCKS.get(
        (environment or "").strip().lower(), FRANCHISEE_CODE_BLOCKS["staging"]
    )
