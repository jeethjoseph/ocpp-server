import type { NextConfig } from "next";
import { withSentryConfig } from "@sentry/nextjs";

const nextConfig: NextConfig = {
  output: 'standalone', // Required for Docker production builds
};

export default withSentryConfig(nextConfig, {
  org: process.env.SENTRY_ORG,
  project: process.env.SENTRY_PROJECT,
  authToken: process.env.SENTRY_AUTH_TOKEN,
  silent: !process.env.CI,
  widenClientFileUpload: true,
  // If SENTRY_AUTH_TOKEN is unset, the upload step skips silently — the
  // build still succeeds and runtime error capture still works; only the
  // stack-trace symbolication on Sentry's UI is degraded.
});
