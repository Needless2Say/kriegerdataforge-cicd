import { test, expect } from "@playwright/test";
import crypto from "node:crypto";

/**
 * Tier 2: the SHARED IDENTITY-layer journey — auth-UI + hub + db, with NO tenant
 * app. It proves the hosted login/consent UI + the hub's code issuance in a
 * browser, driven by a SYNTHETIC OIDC client whose callback we intercept (nothing
 * listens on :9999). This is the auth-UI's own gate; the hub's hub+db auth system
 * is separately covered by its real-DB integration tests
 * (kriegerdataforge/integration_tests/test_oidc_e2e_db.py + test_auth_lifecycle_db.py).
 *
 * Requires `ci_stack.py up --journey auth` (auth-UI + hub + db + the synthetic
 * client seeded; the driver writes E2E_AUTH_CLIENT_ID into e2e/.env). Skips
 * cleanly if creds are unset — this spec reads only the environment, so it stays
 * portable when it moves into the auth-UI repo (Phase 2).
 */

const AUTH_UI_URL = process.env.E2E_AUTH_UI_URL ?? "http://localhost:3002";
const REDIRECT = process.env.E2E_AUTH_REDIRECT_URI ?? "http://localhost:9999/callback";
const USERNAME = process.env.E2E_USERNAME ?? "";
const PASSWORD = process.env.E2E_PASSWORD ?? "";
// The synthetic client id is generated per run; the driver (ci_stack.py) writes it
// to e2e/.env, which playwright.config.ts loads into the environment.
const CLIENT_ID = process.env.E2E_AUTH_CLIENT_ID ?? "";

function b64url(buf: Buffer): string {
  return buf.toString("base64url");
}

function escapeRegExp(value: string): string {
  return value.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

function authorizeUrl(): string {
  const verifier = b64url(crypto.randomBytes(32));
  const challenge = b64url(crypto.createHash("sha256").update(verifier).digest());
  const q = new URLSearchParams({
    response_type: "code",
    client_id: CLIENT_ID,
    redirect_uri: REDIRECT,
    scope: "openid profile email",
    state: "e2e-auth-state",
    nonce: "e2e-auth-nonce",
    code_challenge: challenge,
    code_challenge_method: "S256",
  });
  return `${AUTH_UI_URL}/oauth/authorize?${q.toString()}`;
}

test.describe("Auth-UI login journey @auth", () => {
  test.skip(
    !USERNAME || !PASSWORD || !CLIENT_ID,
    "needs E2E_USERNAME/PASSWORD + a seeded synthetic client (E2E_AUTH_CLIENT_ID)",
  );

  test("synthetic client → auth-UI login → consent → authorization code issued", async ({ page }) => {
    // The synthetic redirect_uri has no server. Capture the callback from the
    // REQUEST (which carries ?code=) the moment the browser navigates to it —
    // before the connection is refused — rather than the loaded page.
    let callbackUrl = "";
    page.on("request", (r) => {
      if (!callbackUrl && r.url().startsWith(REDIRECT)) callbackUrl = r.url();
    });

    // 1. A raw authorize request (no session) lands on the hub's hosted login.
    await page.goto(authorizeUrl());
    await expect(page).toHaveURL(new RegExp(`^${escapeRegExp(AUTH_UI_URL)}/login`));

    // 2. Fill + submit the hosted login form (shared auth-UI testids).
    await page.getByTestId("login-username").or(page.locator("#username")).fill(USERNAME);
    await page.getByTestId("login-password").or(page.locator("#password")).fill(PASSWORD);
    await page.getByTestId("login-submit").or(page.getByRole("button", { name: "Sign in" })).click();

    // 3. Consent is per (user, client) — shown on first login (always on a fresh
    //    CI DB), skipped if already granted. Approve it if/when it appears (riding
    //    out the SSR-before-hydration click race) and stop once the callback (the
    //    code) has fired, whichever path we're on.
    const allow = page.getByTestId("consent-approve").or(page.getByRole("button", { name: "Allow" }));
    await expect(async () => {
      if (!callbackUrl && await allow.isVisible().catch(() => false)) {
        await allow.click({ timeout: 2_000 }).catch(() => {});
      }
      expect(callbackUrl, "callback reached with an authorization code").toBeTruthy();
    }).toPass({ timeout: 30_000 });

    // 4. The hub issued an authorization code to the synthetic client.
    expect(new URL(callbackUrl).searchParams.get("code"), "authorization code issued").toBeTruthy();
  });

  test("wrong password is rejected at the hosted login", async ({ page }) => {
    await page.goto(authorizeUrl());
    await page.getByTestId("login-username").or(page.locator("#username")).fill(USERNAME);
    await page.getByTestId("login-password").or(page.locator("#password")).fill("wrong-" + PASSWORD);
    await page.getByTestId("login-submit").or(page.getByRole("button", { name: "Sign in" })).click();

    // The login must NOT proceed to consent or the client callback — the hosted
    // form stays put (bad credentials rejected).
    await expect(
      page.getByTestId("login-username").or(page.locator("#username")),
    ).toBeVisible({ timeout: 10_000 });
    expect(page.url()).not.toContain(new URL(REDIRECT).host);
    expect(page.url()).not.toContain("/consent");
  });
});
