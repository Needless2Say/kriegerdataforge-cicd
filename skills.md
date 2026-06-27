# KriegerDataForge — Agent Security Playbook (`skills.md`)

The ecosystem-wide security playbook every KDF repo shares. It is **scenario-organized**: find the
scenario(s) matching your current task and follow the rules. Derived from the 2026 production-launch
security audit (`PL-###` findings); the canonical audit lives in the `kriegerdataforge` ecosystem docs
(`docs/kdf-enhancements/security/`).

> **How to use this:** Before — and while — doing any security-sensitive work, read the matching scenario(s)
> below and apply them. When unsure, choose the **more secure / fail-closed** option and say so. Verify a
> suspected issue is real before claiming it, and **pause for owner approval before anything
> architectural, destructive, or behavior-changing** (OIDC protocol changes get a design note first).

---

## Prime directives (always)

1. **Fail closed, not open.** A check that cannot run must **deny**, not allow — auth, JWKS fetch,
   rate-limit store, missing config. Fail-open is only acceptable when explicitly chosen and documented.
2. **Never trust client-supplied input for a security decision** — IPs, hostnames, `request.url`, `Origin`,
   totals/prices, roles/status, ownership, redirect targets.
3. **The server is authoritative.** Recompute security- or money-relevant values server-side; never trust
   client-sent totals, prices, roles, or status.
4. **Defense in depth.** A control at one layer never excuses a gap at another.
5. **Secrets never touch git or logs.** Reference by name/location only; the owner rotates.
6. **Least privilege.** Allow-list, don't deny-list — closed schemas, explicit scopes, exact ownership.

---

## Scenario: secrets, environment & config  *(every repo)*

- Real secret **values** live ONLY in gitignored files (`*.secrets.auto.tfvars`, `.env.local`, `.env.github`,
  `*.pem`). Never commit them; the tracked `*.example` files hold `""` / placeholders.
- **Never print, echo, or paste a secret value**; never read `.pem` private keys or recovery codes. Refer to
  a secret by its name + location.
- `NEXT_PUBLIC_*` / client-exposed env is **inlined into the shipped bundle** — treat it as public; never put
  a real secret there. (EmailJS/public keys are public by design; the real control is the provider dashboard.)
- **gitleaks** runs in CI on **PR diffs** (+ a pre-commit hook). It does NOT scan the whole tree, so a secret
  already committed in an unchanged file slips through — don't rely on it as the only guard; grep before you ship.
- Pydantic v2 `extra="ignore"` **silently drops unknown env keys** — a "flag" the code doesn't read does
  nothing. Don't document/ship phantom config flags; use `extra="forbid"` where unknown keys should `422`.
- The **owner handles ALL secret rotation + git-history purge**. Never rotate or purge yourself — add rotation
  docs + hygiene and flag leaked values.

## Scenario: OIDC / auth tokens / JWT  *(kriegerdataforge AS · kdf_sdk · auth-ui)*

- **Per-client OIDC model:** the access token carries `iss=issuer`, `aud=client_id`, `sub=username`. Each
  tenant pins its **own** `client_id` as the audience; two tenants' audiences MUST be **distinct** (a shared
  one = cross-tenant confused-deputy — each accepts the other's tokens).
- **Verify fail-closed:** when `KDF_JWT_ISSUER` / `KDF_JWT_AUDIENCE` are set, the SDK rejects on `iss`/`aud`
  mismatch (it only fails open when they're unset). Proxies/backends must **validate** `iss`/`aud`, never
  leave it optional.
- A **`sub`-shape change is never AS-only** — the SDK maps `sub` → `KDFUser.username`. Check what the SDK
  *populates*, not just what tenant code reads.
- **JWKS:** support rotation overlap (select by `kid` over the published keys); **fail closed** on fetch
  error/throttle (`503` + `Retry-After`), never silent-anonymous; throttle the unknown-`kid` refetch.
- **Account status / revocation:** suspended/deleted users keep access until token expiry UNLESS a single
  epoch signal (`sessions_valid_after`) **and** the `status` check are enforced on BOTH the stateless SSO
  cookie path AND the OIDC refresh grant. Access JWTs live ≤ their short TTL; the epoch closes the mint paths.
- **Algorithms:** allow-list `RS*`/`PS*` only; reject `none`/`HS*`; don't advertise families your key loaders
  can't actually verify.

## Scenario: Next.js BFF / proxy / frontend  *(auth-ui · *-frontend · tiffanys-space · portfolios)*

- **`request.url` is the INTERNAL bind** (`0.0.0.0:3000` behind Docker/Vercel) in a route handler/proxy.
  NEVER derive a browser host from it (CSRF origin check, F5/redirect target). Use `Host` / `X-Forwarded-Host`
  or a **relative** `Location`; derive the allowed origin from `KDF_OIDC_REDIRECT_URI`.
- **CSRF** on state-changing BFF routes: `SameSite=Lax` **plus** an `Origin` / `Sec-Fetch-Site` check (Origin
  authoritative → exact match; else `Sec-Fetch-Site` must be `same-origin`). SameSite alone is not enough.
- **Session cookie = `SameSite=Lax`, NOT `Strict`** — Strict drops the first login redirect back from the OIDC
  UI (cross-site-initiated). Tell: "works locally, fails on Vercel, second attempt works."
- Read OIDC config from **`serverEnv`** (runtime-parsed), NOT bare `process.env.KDF_OIDC_*` (build-inlined →
  `undefined` for runtime secrets → silent OIDC-refresh failure → session capped at ~15 min).
- **`proxy.ts`** (Next 16, replaces `middleware.ts`): `config.matcher` must be a **static literal** (can't be
  generated from a const) — add a drift-guard test that `matcher ⊇ PRIVATE_ROUTES`; a missing private route
  means JWT verify is skipped.
- **CSP:** allow-list EVERY host the site already uses (`script-`/`connect-`/`frame-`/`img-src`). A static
  export's inline bootstrap needs `script-src 'unsafe-inline'` (can't be nonced); **never ship `frame-src
  'none'` over existing iframes** (e.g. YouTube) — grep the built output for `<iframe>` / third-party hosts
  first. GitHub Pages can't send headers, so a `<meta>` CSP is partial (`frame-ancestors`/XFO are header-only).
- The server-side API client must forward **only the session cookie**, never the refresh / OIDC-flow cookies.

## Scenario: FastAPI backend endpoint  *(kriegerdataforge AS · *-backend · kdf_sdk)*

- **AuthZ on every endpoint** via the SDK deps (`current_user` / `admin_user`); the user PK is
  `user.user_id` (`int`), not `.id`.
- **Mass-assignment:** bind to a CLOSED request schema (`ConfigDict(extra="forbid")`) + an explicit field
  allow-list in the service. Never blind `setattr` over `model_dump()` — `extra="ignore"` hides unknown keys
  from you so the loop looks safe when it isn't.
- **IDOR:** prove ownership with an **exact** check (e.g. `urlparse` the path and compare the owner segment),
  never a substring/regex over the whole URL — a query string can smuggle your id (`?x=/<my-id>/`) and bypass it.
- **Server-authoritative compute:** recompute security/$-relevant values (nutrition totals, order prices,
  roles) server-side and ignore client-sent totals. When a recompute REPLACES a client value on a **save**
  path, mirror the client's own validity filter (skip-and-log unverifiable items) so raw autosave/`sendBeacon`
  data isn't rejected and lost.
- **Rate limiting:** `slowapi` reads `RATELIMIT_STORAGE_URI`; `memory://` is per-instance (useless on
  serverless) → needs a **shared store** (Redis/Upstash). Key off the edge-set, non-forgeable IP header
  (`x-vercel-forwarded-for` → `x-real-ip`), **never** raw left-most `X-Forwarded-For` (Vercel *appends*, so
  the left entry is client-spoofable). Per-account lockout is **DB-backed** (`failed_login_attempts` /
  `locked_until`) and works without Redis.
- **Timing:** run a uniform argon2 verify for every login outcome (**verify-first**) so locked/inactive/
  missing accounts don't answer faster (enumeration/timing oracle).
- Raise domain exceptions → `to_http_exception()` (never bare `HTTPException` in services); keep settings
  access **lazy** (no module-level `get_*_settings()` — the vercel compactor imports with no env).

## Scenario: Terraform / infrastructure  *(kriegerdataforge-terraform)*

- **Per-client audience invariant:** each tenant's `AUTH_AUDIENCE` / `KDF_JWT_AUDIENCE` = its own
  `<tenant>_oidc_client_id`; the issuer is the single shared `kdf_auth_ui_url`. `jwt_claims_sync.rego` denies
  a client_id **collision** between tenants.
- **prod-guard (OPA, env-gated):** prod must have Stripe enabled + `RATELIMIT_STORAGE_URI` set to a real
  Redis. It **warns** today; flip to **deny** only AFTER the store + Stripe are actually provisioned (a
  default-empty value would hard-block the first prod apply).
- **No secrets in committed files:** secrets go in gitignored `*.secrets.auto.tfvars`; never commit
  `tfplan.json` / `*.tfstate*` — they contain cleartext secrets (gitignore them, rotate if leaked).
- `sensitive = true` on every secret-bearing var. The top-level plan `.variables` show even `sensitive` vars
  in **cleartext** — don't assume redaction when reasoning about exposure.
- **No GCP resources** until an ADR approves. Run `make env-audit && make check-invariants` before any apply.

## Scenario: CI/CD & supply chain  *(kriegerdataforge-cicd · every repo)*

- A **secret-scan (gitleaks)** + an **approval / deployer gate** must run before anything ships — fail-closed
  `check_deployer`, `github-pages` Environment reviewers. Gate on `github.triggering_actor` (survives re-runs),
  not `event.sender`.
- **SHA-pin** third-party actions (not `@master` / `@vN`). First-party **reusable-workflow** calls use
  `@main` by convention (the reusable file is itself pinned).
- Pin dependency floors against CVEs; generate **hash-pinned** lockfiles (`--generate-hashes`); use npm
  `"overrides"` to force a patched transitive (a `next` bump often won't move a pinned transitive like
  `postcss`). Run **Dependabot** for the real ecosystem (pip / npm), not just GitHub Actions.
- Build **provenance / attestation** on publish (skip on private-personal repos until an org move / public).

## Scenario: writing tests for security code

- A new guard must **fail on the regression it targets** — mutation-test it (break the code, confirm the test
  goes red), don't just assert the happy path.
- Don't instantiate SQLModel **table** models / build `select(...)` that triggers the mapper cascade in unit
  tests — use `MagicMock` / `SimpleNamespace`; a `Mock(spec=KDFUser)` flowing the auth/refresh gate needs
  `sessions_valid_after=None`.
- Two hand-maintained tables that must agree (e.g. the unit-conversion FE JSON + BE dict) **drift** — vendor a
  canonical copy + a CI **drift-guard** (superset + agreement-within-tolerance + reciprocal consistency), and
  **verify, don't regenerate**, when the two sides intentionally differ in precision.
- `round(84.535, 2) == 84.53` in Python (float repr + banker's rounding) — assert the **actual** value.

---

## When you find a security issue

1. **Classify** severity and **verify it's real** before claiming it — self-check, and adversarially try to
   refute it. Distinguish *real vuln* vs *defense-in-depth* vs *reframe/not-applicable*.
2. Prefer the **fail-closed** fix; mirror the client's own validity rules when a server check could reject
   legitimate (e.g. in-progress autosave) data.
3. **Pause for owner approval** before anything architectural, destructive, or behavior-changing. OIDC
   protocol items get a **design note first**. The owner handles secret rotation.
