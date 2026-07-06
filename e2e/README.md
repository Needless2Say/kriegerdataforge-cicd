# Tier 2 full-stack E2E (Playwright)

Browser E2E for the **real** KriegerDataForge ecosystem stack — the tier that
proves the pieces only integrate in a browser: the BFF proxy, the cross-origin
OIDC redirect chain, the callback's real code→token exchange, and
server-rendered backend data, all as a user experiences them.

Unit + integration tests (including the hub OIDC E2E in
`kriegerdataforge/integration_tests/test_oidc_e2e_db.py`) cover the OIDC
*protocol*; this covers the *journey*.

> **Status:** local-first. This is the proven local harness + one happy-path
> spec. The reusable cross-repo CI job (`e2e-compose`) is the next increment —
> see [Toward CI](#toward-ci).

## The journey under test

```
fitness FE (:3000)  gated route "/database"
  → proxy 307 → /api/auth/oidc/initiate → 307 → hub authorize
    → hub auth-UI (:3002)  hosted login form  → (one-time) consent "Allow"
      → FE callback  /api/auth/oidc/callback  code→token, sets session cookie
        → "/"  account menu visible (logged in)
          → "/database"  server-rendered foods from the fitness backend (:8001)
```

## Prerequisites

- **Node ≥ 20** and **Docker Desktop**.
- The four sibling repos checked out next to each other (`kriegerdataforge`,
  `kriegerdataforge-auth-ui`, `fitness-app-backend`, `fitness-app-frontend`),
  each with its `.env.local` provisioned (RSA dev keypair, `GH_PACKAGES_PAT`,
  a seeded fitness OIDC client). See each repo's `.env.local.example`.

## Run it locally

From the **cicd repo root** (`make` targets wrap the steps):

```bash
make e2e-install        # npm ci + playwright browsers (chromium), in e2e/
make e2e-up             # bring the full stack up (delegates to fitness-app-frontend `make docker-up`)
make e2e-seed-user      # create the deterministic active test user (e2e-user)
make e2e                # run the Playwright suite
make e2e-down           # tear the stack down
```

Or directly in `e2e/`:

```bash
npm ci
npm run install:browsers
cp .env.example .env     # adjust if your ports/creds differ
npm test                 # headless;  npm run test:headed  to watch
npm run report           # open the last HTML report
```

The stack must already be up and a matching **active** user seeded (the
`E2E_USERNAME`/`E2E_PASSWORD` in `.env`). The spec **skips cleanly** if those
are unset, so `npm test` never hard-fails on an unconfigured checkout.

### Seeding the test user

`users.json` is gitignored, so no dev login user exists on a fresh DB. Create a
deterministic one against the running stack (also in `make e2e-seed-user`):

```bash
docker exec kdf-api python -c "from api.auth.service import AuthDatabaseService; \
  from api.auth.schemas import RegisterRequest; \
  AuthDatabaseService().create_user(RegisterRequest(username='e2e-user', \
  password='E2eTest123!', email='e2e-user@example.com'), auto_activate=True)"
```

The fitness OIDC client and food catalogue are seeded by the stack's init/seed
step; `/database` needs ≥ 1 food for the data-render assertion.

## Selectors (no test-ids yet)

Neither the auth-UI nor the fitness frontend ships `data-testid` hooks, so the
spec drives by stable ids / accessible roles:

| Step | Selector |
|---|---|
| hub login username / password | `#username` / `#password` |
| hub login submit | `getByRole('button', { name: 'Sign in' })` |
| consent approve (one-time) | `getByRole('button', { name: 'Allow' })` |
| logged-in marker (any private page) | `button[aria-label="Open account menu"]` |
| rendered backend data (`/database`) | `a[aria-label^="View food details:"]` |

**Hardening follow-up:** add `data-testid` to the auth-UI login/consent controls
and the fitness account menu so the suite is robust to copy/label changes.

## Toward CI

The whole-stack compose is currently a loose workspace-root
`docker-compose.yml` referencing sibling dirs by relative path — not committed to
any repo. The CI increment will:

1. Commit a CI-usable `e2e/docker-compose.e2e.yml` (builds images, no source
   bind-mounts, reads `POSTGRES_PASSWORD` + `GH_PACKAGES_PAT` from CI env).
2. Add a reusable `.github/workflows/e2e-compose.yml` that `actions/checkout`s
   the sibling private repos (via `CICD_PAT`), brings the stack up, seeds, runs
   Playwright, and uploads the HTML report + traces as artifacts.

No org move or public repos are required — same-account private repos are
clonable with a token.
