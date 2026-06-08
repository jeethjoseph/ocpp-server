/**
 * Build-time feature flags, read from NEXT_PUBLIC_* env vars that Next.js
 * inlines at `next build` time. Toggling these requires a frontend rebuild.
 */

/**
 * Whether wallet charging (start-with-wallet + wallet top-up) is offered in the
 * UI. The backend is the source of truth and returns 403 when off (ADR 0011);
 * this flag only hides dead-end UI so users aren't sent to an endpoint that
 * will reject them. Default true; only an explicit "false" disables it, so dev
 * and existing environments (where the var is unset) are unaffected.
 */
export function walletChargingEnabled(): boolean {
  return process.env.NEXT_PUBLIC_WALLET_CHARGING_ENABLED !== "false";
}
