import { defineConfig, devices } from "@playwright/test";

// Load e2e/.env if present (Node >= 20.12), so E2E_* can live in a gitignored
// file. Falls back to the localhost defaults below when there is no .env.
try {
  (process as NodeJS.Process & { loadEnvFile?: (p?: string) => void }).loadEnvFile?.();
} catch {
  /* no .env file — use env vars / defaults */
}

/**
 * Tier 2 full-stack E2E config.
 *
 * The system under test is the real ecosystem stack brought up via
 * `make docker-up` (fitness frontend :3000, hub auth-UI :3002, hub API :8000,
 * fitness backend :8001, + Postgres). Playwright drives a browser across those
 * origins — there is no `webServer` here; the stack is external and long-lived.
 */
const BASE_URL = process.env.E2E_BASE_URL ?? "http://localhost:3000";

export default defineConfig({
  testDir: "./tests",
  // The OIDC journey mutates shared IdP session + consent state, so keep it serial.
  fullyParallel: false,
  workers: 1,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 1 : 0,
  reporter: [["list"], ["html", { open: "never" }]],
  timeout: 60_000,
  expect: { timeout: 15_000 },
  use: {
    baseURL: BASE_URL,
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
    video: "retain-on-failure",
    ignoreHTTPSErrors: true,
  },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],
});
