/// <reference types="vitest" />
import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";
import path from "node:path";

/**
 * Frontend test harness — Vitest + React Testing Library + jsdom.
 *
 * Mirrors the `@/*` path alias from tsconfig.json so component tests can
 * import production modules the same way the app does. See
 * `__tests__/README.md` for how to add new tests.
 */
export default defineConfig({
  plugins: [react()],
  // Override the project's PostCSS auto-discovery with an empty config so
  // Vite doesn't try to load Tailwind v4's PostCSS plugin (which uses an
  // ESM-only export format Vitest's CJS loader can't parse). Component tests
  // don't assert on styles, so an empty PostCSS pipeline is fine.
  css: { postcss: { plugins: [] } },
  test: {
    environment: "jsdom",
    setupFiles: ["./__tests__/setup.ts"],
    globals: true,
    include: ["__tests__/**/*.test.{ts,tsx}"],
  },
  resolve: {
    alias: {
      "@": path.resolve(__dirname, "./"),
    },
  },
});
