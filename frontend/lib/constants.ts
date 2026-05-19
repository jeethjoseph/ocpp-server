/**
 * Frontend numeric constants that mirror backend defaults.
 *
 * Keep in sync with `backend/core/config.py`. If the backend env var changes,
 * these UI labels and previews will lie until this file is updated — there's
 * no automatic propagation. For the synthetic-fee rate specifically, the
 * authoritative value lives in the backend (`RAZORPAY_PLATFORM_FEE_PERCENT`);
 * this constant exists so the admin form's live preview can show the
 * back-derivation breakdown without an extra API round-trip.
 *
 * See ADR 0001 (synthetic platform fee) and ADR 0003 (all-inclusive tariff).
 */

/** Synthetic platform-fee rate in percent. Mirrors backend default 2.0. */
export const PLATFORM_FEE_PERCENT = 2;

/** Default GST percent applied to per-kWh charges. Mirrors `Tariff.gst_percent` default 18.00. */
export const DEFAULT_GST_PERCENT = 18;
