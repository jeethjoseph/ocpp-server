import type { NextConfig } from "next";
import { withSentryConfig } from "@sentry/nextjs";

const nextConfig: NextConfig = {
  output: 'standalone', // Required for Docker production builds
};

// Build a release name that does NOT depend on git context being
// present inside the Docker build (Dockerfile's `COPY . .` only brings
// frontend/, not the repo-root .git/). Without an explicit name the
// Sentry plugin's auto-detection comes back empty and the upload step
// no-ops silently. Priority order: explicit env (CI/git SHA passed as
// build arg) → fall back to a timestamped staging marker.
const sentryRelease =
  process.env.SENTRY_RELEASE ||
  process.env.GIT_COMMIT ||
  `${process.env.NEXT_PUBLIC_SENTRY_ENVIRONMENT || "dev"}-${new Date()
    .toISOString()
    .replace(/[:.]/g, "-")
    .slice(0, 19)}`;

export default withSentryConfig(nextConfig, {
  org: process.env.SENTRY_ORG,
  project: process.env.SENTRY_PROJECT,
  authToken: process.env.SENTRY_AUTH_TOKEN,
  // Plugin must log errors during source-map upload — `silent: true`
  // here cost us hours on 2026-05-26 because upload failures were
  // invisible. Routine success lines are still tolerable noise.
  silent: false,
  widenClientFileUpload: true,
  release: {
    name: sentryRelease,
  },
  sourcemaps: {
    // After Sentry has the .map files, remove them from the build
    // output so they aren't shipped in the public /_next/static/
    // bundle. Without this anyone can curl the .map files off the
    // running site and reconstruct unminified source. Replacement for
    // the v10-removed `hideSourceMaps` option.
    deleteSourcemapsAfterUpload: true,
  },
  // If SENTRY_AUTH_TOKEN is unset, the upload step skips with a logged
  // warning; runtime error capture still works, only the stack-trace
  // symbolication on Sentry's UI is degraded.
});
