/**
 * Global test setup. Loaded once before all tests via vitest.config.ts.
 * Adds RTL's jest-dom matchers (toBeInTheDocument, toHaveTextContent, …) to
 * Vitest's expect.
 */
import "@testing-library/jest-dom/vitest";
