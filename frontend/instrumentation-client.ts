import * as Sentry from "@sentry/nextjs";

const dsn = process.env.NEXT_PUBLIC_SENTRY_DSN;

if (dsn) {
  Sentry.init({
    dsn,
    environment: process.env.NEXT_PUBLIC_SENTRY_ENVIRONMENT || "development",
    tracesSampleRate: 0,
    replaysSessionSampleRate: 0,
    replaysOnErrorSampleRate: 0,
    debug: false,
  });
}

// Required by @sentry/nextjs to instrument Next.js App Router client-side
// navigations. Without this export, Sentry only sees the initial page load
// and errors fired after a client-side navigation appear with stale route
// metadata + missing nav breadcrumbs.
export const onRouterTransitionStart = Sentry.captureRouterTransitionStart;
