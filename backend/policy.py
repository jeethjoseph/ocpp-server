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
# Blocks are numeric rather than an environment letter for one reason: there is
# no room for a letter. Rule 46(b) caps the invoice serial at sixteen characters
# and "F0001/Q/26/00001" spends all sixteen, so the partition had to live inside
# the digits. Contrast the Asset Code (ADR 0028), which solves the same problem
# with a distinct per-environment series (VOW / VOWS) because it is NOT part of
# the serial — it is voluntary descriptive content on the invoice, under no
# statutory length or charset constraint, so it can afford the clearer
# mechanism. Same reasoning, two mechanisms, because the budgets differ.
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
    the same fail-safe direction as ADR 0028's series map, so a misconfigured
    box cannot mint a code production might later issue.
    """
    return FRANCHISEE_CODE_BLOCKS.get(
        (environment or "").strip().lower(), FRANCHISEE_CODE_BLOCKS["staging"]
    )


# --- Asset Code series: the customer-facing charger identifier (ADR 0028) ---
#
# An Asset Code is an environment series plus a zero-padded integer: VOW0001 in
# production, VOWS0001 in staging and development. It replaces the
# charge_point_string_id UUID on every customer surface.
#
# The series exists for the same reason FRANCHISEE_CODE_BLOCKS does, and guards
# the same hazard from the other side: staging serves real paying customers
# (~11 GST invoices/day as of 2026-08), so both registers mint codes that a real
# person reads off a real unit and quotes to support. Without a series split,
# staging's VOW0004 and production's VOW0004 are the same string naming two
# different chargers — the shape that produced the duplicate VL/F2/ invoice
# numbers and the qr_payment_{PK} refund collision.
#
# Here the partition is a letter rather than a numeric block because, unlike the
# GST invoice serial, an Asset Code is under no statutory length constraint. It
# can afford the clearer mechanism.
CHARGER_CODE_SERIES = {
    "production": "VOW",
    "staging": "VOWS",
    "development": "VOWS",
}

# Minimum digit width. The code widens by itself past VOW9999 -> VOW10000: no
# migration, no re-padding, no fleet re-stencil at the boundary. Codes are
# consumed cumulatively (a retired unit keeps its code so its historical
# invoices still resolve), so a fixed ceiling would eventually cost a
# fleet-wide re-stencil plus a permanent discontinuity in the invoice record.
# Lookup parses the integer rather than matching the string, which is what
# makes a variable width safe.
CHARGER_CODE_MIN_WIDTH = 4

# The one place the Asset Code's shape is written down. The DB CHECK in
# migration 58 is built from these, and so is every Python-side validation, so
# a format change cannot land in one and not the other. Tests assert against
# these rather than restating the regex, which is what makes them meaningful.
CHARGER_CODE_FORMAT_PATTERN = f"^VOWS?[0-9]{{{CHARGER_CODE_MIN_WIDTH},}}$"


def charger_code_series_pattern(environment: str) -> str:
    """Regex accepting only the codes this environment may hold.

    Note VOW is a strict prefix of VOWS, so production's pattern must not
    accidentally admit a staging code. It does not: the character after `VOW`
    is required to be a digit, and `S` is not.
    """
    series = charger_code_series(environment)
    return f"^{series}[0-9]{{{CHARGER_CODE_MIN_WIDTH},}}$"


def charger_code_series(environment: str) -> str:
    """The Asset Code series this environment may mint.

    Unknown, empty or None environments resolve to the STAGING series, never
    production's. A misconfigured box must not be able to mint a
    production-looking code — the failure is silent and the collision it
    creates is permanent, because the code lands on issued GST invoices.
    """
    return CHARGER_CODE_SERIES.get(
        (environment or "").strip().lower(), CHARGER_CODE_SERIES["staging"]
    )
