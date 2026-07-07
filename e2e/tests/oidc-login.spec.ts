import { test, expect } from "@playwright/test";

/**
 * Tier 2 capstone: the real fitness-tenant OIDC login journey, end to end,
 * across three origins — proving the pieces that only integrate in a browser:
 *
 *   fitness FE (:3000)  gated route → proxy bounces to OIDC initiate
 *     → hub auth-UI (:3002)  hosted login form → (one-time) consent
 *       → back to FE callback  code→token exchange sets the session cookie
 *         → protected page renders data fetched from the fitness backend (:8001).
 *
 * This is the only tier that exercises the BFF proxy, the cross-origin OIDC
 * redirect chain, the callback's real code→token exchange, and server-rendered
 * backend data together as a user experiences them. Unit/integration tests
 * (including the hub OIDC E2E in kriegerdataforge/integration_tests) cover the
 * protocol; this covers the *journey*.
 *
 * Requires the full stack up (`make e2e-up` / `make docker-up`) and a seeded,
 * active user — see e2e/README.md. Skips cleanly if credentials are unset.
 */

const AUTH_UI_URL = process.env.E2E_AUTH_UI_URL ?? "http://localhost:3002";
const BASE_URL = process.env.E2E_BASE_URL ?? "http://localhost:3000";
const USERNAME = process.env.E2E_USERNAME ?? "";
const PASSWORD = process.env.E2E_PASSWORD ?? "";

function escapeRegExp(value: string): string {
  return value.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

test.describe("Fitness OIDC login journey @fitness", () => {
  test.skip(
    !USERNAME || !PASSWORD,
    "set E2E_USERNAME + E2E_PASSWORD to a seeded, active hub user (see e2e/README.md)",
  );

  test("gated route → hosted login → consent → protected data renders", async ({ page }) => {
    // 1. Unauthenticated hit on a gated route is bounced through OIDC to the
    //    hub's hosted login page (a different origin).
    await page.goto("/database");
    await expect(page).toHaveURL(new RegExp(`^${escapeRegExp(AUTH_UI_URL)}/login`));

    // 2. Fill the hosted login form. Prefer the data-testid hooks, falling back
    //    to stable ids / accessible names so the spec passes whether or not the
    //    auth-UI/frontend test-id changes are deployed yet.
    await page.getByTestId("login-username").or(page.locator("#username")).fill(USERNAME);
    await page.getByTestId("login-password").or(page.locator("#password")).fill(PASSWORD);
    await page
      .getByTestId("login-submit")
      .or(page.getByRole("button", { name: "Sign in" }))
      .click();

    // The login POST + OIDC redirect chain (login → authorize → consent|callback)
    // is async, so wait until it settles on either the consent screen or the app
    // before deciding what to do next.
    await page.waitForURL(
      (url) => url.href.includes("/consent") || url.href.startsWith(BASE_URL),
      { timeout: 25_000 },
    );

    // 3. Consent is recorded per (user, client) and only shown on first login.
    //    If shown, approve — retrying the click to ride out client hydration
    //    (the SSR'd button is visible before React attaches onClick, so a single
    //    early click can no-op) until we've navigated off /consent.
    if (page.url().includes("/consent")) {
      const allow = page.getByTestId("consent-approve").or(page.getByRole("button", { name: "Allow" }));
      await allow.waitFor({ state: "visible" });
      await expect(async () => {
        if (page.url().includes("/consent")) {
          await allow.click({ timeout: 3_000 }).catch(() => {});
        }
        expect(page.url()).not.toContain("/consent");
      }).toPass({ timeout: 20_000 });
    }

    // 4. Back on the fitness app, authenticated. The account menu button is
    //    rendered on every private page — a reliable "logged in" marker that
    //    doesn't depend on client-side dashboard data.
    await page.waitForURL((url) => url.href.startsWith(BASE_URL), { timeout: 25_000 });
    await expect(
      page.getByTestId("account-menu").or(page.getByRole("button", { name: "Open account menu" })),
    ).toBeVisible();

    // 5. Protected, server-rendered data from the fitness backend. /database
    //    lists foods; each item is a link (data-testid="food-result", or the
    //    "View food details: <name>" aria-label as a fallback).
    await page.goto("/database");
    await expect(
      page
        .getByTestId("food-result")
        .or(page.locator('a[aria-label^="View food details:"]'))
        .first(),
    ).toBeVisible();
  });
});
