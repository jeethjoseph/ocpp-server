/**
 * Frontend numeric constants that mirror backend defaults.
 *
 * Keep in sync with `backend/core/config.py`. If the backend env var changes,
 * these UI labels and previews will lie until this file is updated — there's
 * no automatic propagation.
 *
 * Note (ADR 0026): the synthetic 2% gateway fee was removed. The tariff the
 * operator enters is now GST-inclusive and gateway-EXCLUSIVE; the Razorpay
 * gateway fee is a separate, variable line billed on top. There is no
 * `PLATFORM_FEE_PERCENT` constant anymore.
 */

/** Default GST percent applied to per-kWh charges. Mirrors `Tariff.gst_percent` default 18.00. */
export const DEFAULT_GST_PERCENT = 18;
