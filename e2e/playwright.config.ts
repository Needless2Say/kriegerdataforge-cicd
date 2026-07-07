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
 * The system under test is the real ecosystem stack brought up externally (the
 * self-contained `ci_stack.py up`, or the delegated `make docker-up`). Playwright
 * drives a browser across the origins — there is no `webServer` here; the stack
 * is external and long-lived.
 *
 * testDir is `./staged-tests` (gitignored): the driver (ci_stack.py) STAGES the
 * active journeys' specs there so `npm test` runs exactly the journeys that are
 * up — no `--grep` needed. Each journey's spec is OWNED by its tenant repo
 * (transitionally e2e/tenants/<j>/tests/); the driver copies it in per run.
 * See docs/design/e2e-test-decoupling.md (ADR D-006).
 */
const BASE_URL = process.env.E2E_BASE_URL ?? "http://localhost:3000";

export default defineConfig({
  testDir: "./staged-tests",
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
