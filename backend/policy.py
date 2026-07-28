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
