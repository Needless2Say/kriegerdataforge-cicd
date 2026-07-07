import { test, expect } from "@playwright/test";

/**
 * Tier 2: the real TIFFANY'S-tenant OIDC login journey — a second tenant sharing
 * the hub + auth-UI, proving the same browser-only integration for a different
 * app + a DISTINCT OIDC client:
 *
 *   tiffanys FE (:3001)  gated route → proxy bounces to OIDC initiate
 *     → hub auth-UI (:3002)  hosted login form → (one-time) consent
 *       → back to FE callback  code→token exchange sets the session cookie
 *         → /shop renders products fetched from the tiffanys backend (:8002).
 *
 * tiffanys is OIDC-only (no legacy toggle) and default-deny (private preview), so
 * even /shop — whose product data is public — requires a full OIDC login to reach.
 * The hosted login + consent are the SHARED auth-UI, so those selectors are
 * identical to the fitness spec; only the app origin, the gated route, and the
 * tenant's markers differ. The Playwright baseURL is the fitness origin, so this
 * spec navigates the tiffanys origin with absolute URLs. Skips if creds are unset.
 */

const AUTH_UI_URL = process.env.E2E_AUTH_UI_URL ?? "http://localhost:3002";
const BASE_URL = process.env.E2E_TIFFANYS_BASE_URL ?? "http://localhost:3001";
const USERNAME = process.env.E2E_USERNAME ?? "";
const PASSWORD = process.env.E2E_PASSWORD ?? "";

function escapeRegExp(value: string): string {
  return value.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

test.describe("Tiffany's OIDC login journey @tiffanys", () => {
  test.skip(
    !USERNAME || !PASSWORD,
    "set E2E_USERNAME + E2E_PASSWORD to a seeded, active hub user (see e2e/README.md)",
  );

  test("gated route → hosted login → consent → protected data renders", async ({ page }) => {
    // 1. Unauthenticated hit on a gated route is bounced through OIDC to the hub's
    //    hosted login page. tiffanys default-denies every route, so /shop requires
    //    a full OIDC login even though its product data is public.
    await page.goto(`${BASE_URL}/shop`);
    await expect(page).toHaveURL(new RegExp(`^${escapeRegExp(AUTH_UI_URL)}/login`));

    // 2. Fill the SHARED hosted login form (same auth-UI + testids as fitness).
    await page.getByTestId("login-username").or(page.locator("#username")).fill(USERNAME);
    await page.getByTestId("login-password").or(page.locator("#password")).fill(PASSWORD);
    await page
      .getByTestId("login-submit")
      .or(page.getByRole("button", { name: "Sign in" }))
      .click();

    // The login POST + OIDC redirect chain is async — settle on consent or the app.
    await page.waitForURL(
      (url) => url.href.includes("/consent") || url.href.startsWith(BASE_URL),
      { timeout: 25_000 },
    );

    // 3. Consent is recorded per (user, client). The tiffanys client is DISTINCT
    //    from the fitness one, so consent is shown on first tiffanys login even if
    //    the user already consented to fitness. Approve, riding out the
    //    SSR-before-hydration click race.
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

    // 4. Back on the tiffanys app, authenticated. The account menu button renders
    //    on every chrome page — a reliable "logged in" marker.
    await page.waitForURL((url) => url.href.startsWith(BASE_URL), { timeout: 25_000 });
    await expect(
      page.getByTestId("account-menu").or(page.getByRole("button", { name: "My account" })),
    ).toBeVisible();

    // 5. Protected, server-rendered data from the tiffanys backend. /shop lists
    //    products; each card is a link (data-testid="product-card", or an
    //    /shop/<slug> href as a fallback).
    await page.goto(`${BASE_URL}/shop`);
    await expect(
      page
        .getByTestId("product-card")
        .or(page.locator('a[href^="/shop/"]'))
        .first(),
    ).toBeVisible();
  });
});
