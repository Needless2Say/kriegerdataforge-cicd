# Tier 2 full-stack E2E (Playwright)

Browser E2E for the **real** KriegerDataForge ecosystem stack — the tier that
proves the pieces only integrate in a browser: the BFF proxy, the cross-origin
OIDC redirect chain, the callback's real code→token exchange, and
server-rendered backend data, all as a user experiences them.

Unit + integration tests (including the hub OIDC E2E in
`kriegerdataforge/integration_tests/test_oidc_e2e_db.py`) cover the OIDC
*protocol*; this covers the *journey*.

> **Status:** two ways to bring the stack up — the **delegated** local stack
> (`make e2e-up`, reuses each repo's `.env.local` + bind-mounts) and the
> **self-contained** stack (`make e2e-ci`, builds every image from source with
> generated secrets, no `.env.local`). The self-contained stack also runs in
> GitHub Actions via the owner-dispatched `e2e-compose` workflow — see
> [CI (GitHub Actions)](#ci-github-actions).

## The journeys under test

Two tenants share the hub + auth-UI, each with a **distinct OIDC client** — the
same browser-only integration, proven per tenant (`tests/oidc-login.spec.ts`
`@fitness`, `tests/tiffanys-login.spec.ts` `@tiffanys`):

```
fitness FE (:3000)  gated route "/database"
  → proxy 307 → /api/auth/oidc/initiate → 307 → hub authorize
    → hub auth-UI (:3002)  hosted login form  → (one-time) consent "Allow"
      → FE callback  /api/auth/oidc/callback  code→token, sets session cookie
        → "/"  account menu visible (logged in)
          → "/database"  server-rendered foods from the fitness backend (:8001)

tiffanys FE (:3001)  gated route "/shop"   (OIDC-only; default-deny proxy)
  → … same hosted login + consent (distinct tiffanys client) …
    → "/"  account menu visible → "/shop"  products from tiffanys backend (:8002)
```

A third journey, **`auth`** (`tests/auth-login.spec.ts` `@auth`), tests the shared
identity layer at its own level — auth-UI + hub + db, a **synthetic** OIDC client
and **no tenant app** (login → consent → an authorization code, plus a
wrong-password case). The hub's hub+db auth system is separately covered by its
real-DB integration tests.

The stack is journey-profiled: `ci_stack.py up --tenants fitness` (or `tiffanys`,
`auth`, or `fitness,tiffanys`) brings up only what that journey needs (+ the shared
hub/auth-UI), and Playwright selects the matching spec by tag (`--grep @fitness`).

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

## Self-contained CI stack (no local checkout state)

`make e2e-up` above delegates to `fitness-app-frontend`'s `make docker-up`, which
bind-mounts each repo's source and reads secrets from each repo's gitignored
`.env.local`. Great for local iteration, but it **can't run in CI** — a fresh
runner has no `.env.local` and nothing to bind-mount.

`docker-compose.e2e.yml` + `ci_stack.py` are the hermetic sibling. `ci_stack.py`:

- generates a throwaway RS256 keypair + fixed-per-run OIDC `client_id`/`secret` +
  session secret + DB password (persisted to `e2e/.e2e-ci.json`, gitignored) and
  threads them through the compose so the hub, the frontend, and the seed all
  agree — no capture-and-inject dance;
- builds every service from source (the `dev` image targets, source COPY'd in,
  **no** bind-mounts), brings them up on their own network with healthcheck
  gating, migrates **both** databases to head, then seeds the active login user +
  the OIDC client (hub) and the food catalogue (fitness);
- sources `GH_PACKAGES_PAT` from the environment (the CI secret), falling back to
  `fitness-app-backend/.env.local` locally so you needn't export it by hand.

```bash
make e2e-ci          # build + up + seed → run Playwright → tear down (one shot)
# …or keep the stack up to iterate:
make e2e-ci-up       # build + up + migrate + seed   (leaves it running)
make e2e             # run the suite against it
make e2e-ci-logs SERVICE=fitness-app-nextjs   # debug a service
make e2e-ci-down     # remove containers, volumes, network
```

The generated keys are ephemeral and never touch your real dev keypair. The
seeded login user is the same deterministic `e2e-user` / `E2eTest123!` the suite
defaults to, so no `.env` wiring is needed. It uses the `dev` image targets on
purpose — the production `runner`/standalone build breaks a plain-http E2E
(Secure cookies get dropped, CSP upgrades http→https, `NEXT_PUBLIC_*` bake at
build). MinIO is omitted (not on the login→`/database` path).

## Selectors (data-testid, with fallbacks)

The auth-UI and fitness frontend now ship `data-testid` hooks
(auth-ui#38, fitness-app-frontend#305). The spec targets them via
`getByTestId(...).or(<legacy id/role>)`, so it stays green **whether or not**
those frontend PRs are deployed yet — no cross-repo merge-order dependency:

| Step | `data-testid` | Fallback |
|---|---|---|
| hub login username / password | `login-username` / `login-password` | `#username` / `#password` |
| hub login submit | `login-submit` | `getByRole('button', { name: 'Sign in' })` |
| consent approve (one-time) | `consent-approve` | `getByRole('button', { name: 'Allow' })` |
| logged-in marker (any private page) | `account-menu` | `button[aria-label="Open account menu"]` |
| rendered backend data (`/database`) | `food-result` | `a[aria-label^="View food details:"]` |

## CI (GitHub Actions)

`.github/workflows/e2e-compose.yml` runs this exact self-contained stack on a
runner, two ways:

- **`workflow_dispatch`** — manual, **owner-gated** (`_authorize-owner.yml`).
  Actions tab → *E2E · Full-stack OIDC journey* → *Run workflow*. Proven green
  end-to-end (~4 min).
- **`workflow_call`** — the app repos call it as a **merge gate** (see below).

What it does: mints a short-lived GitHub App token (`contents:read`, scoped to the
four siblings + the SDK repo), checks out all five repos as siblings under
`$GITHUB_WORKSPACE` (so the `../../<repo>` build contexts resolve), then
`python e2e/ci_stack.py up` → `npm test` → uploads the HTML report + traces →
always tears the stack down. Secrets (`KDF_APP_ID` / `KDF_APP_PRIVATE_KEY`) are
auto-masked; CI gets build/wait headroom via `E2E_BUILD_TIMEOUT` / `E2E_WAIT_TIMEOUT`.

## Promoting the E2E to a merge gate

Each E2E-journey repo ships a **dormant** caller workflow,
`.github/workflows/e2e-gate.yml`, that passes the `journey` its changes affect:

| Repo | `journey` | Why |
|---|---|---|
| `fitness-app-backend` / `fitness-app-frontend` | `fitness` | fitness-only change |
| `tiffanys-space` / `tiffanys-space-backend` | `tiffanys` | tiffanys-only change |
| `kriegerdataforge-auth-ui` | `auth` | tests its layer (hosted login/consent + hub + db), a synthetic client, no tenant app |
| `kriegerdataforge` (hub) | — | **no docker gate** — its real-DB integration tests (`test_oidc_e2e_db.py`, `test_auth_lifecycle_db.py`) already gate hub+db auth |

```yaml
on:
  pull_request:
    branches: [main]
jobs:
  e2e:
    if: vars.RUN_E2E_GATE == 'true'   # dormant until you flip this
    uses: Needless2Say/kriegerdataforge-cicd/.github/workflows/e2e-compose.yml@main
    with:
      journey: fitness                # fitness | tiffanys | all (default)
    secrets: inherit
```

While `RUN_E2E_GATE` is unset the job is **skipped** — a near-instant no-op on each
PR, gating nothing. To **turn it on** in a repo (Settings → Secrets and variables →
Actions, and Settings → Branches):

1. **Variable** `RUN_E2E_GATE = true` — activates the caller.
2. **Variable** `USE_GITHUB_APP = true` + **secrets** `KDF_APP_ID`,
   `KDF_APP_PRIVATE_KEY` — the reusable workflow mints its App token from these
   (they live only on the cicd repo today; an org move would make them org-level
   and skip this per-repo step).
3. Add the resulting check (**E2E merge gate / …**) to **branch protection** →
   *Require status checks to pass*.

> **Caveat — cross-repo lockstep.** A PR that must change two repos together (an
> OIDC-contract change in the hub *and* the frontend, an SDK bump) can't go green
> in either repo's gate — each tests against the other's old `main`. So the
> recommended posture is **merge-to-main + nightly** rather than a hard per-PR
> gate; adjust the caller's `on:` accordingly, keeping the fast in-repo contract
> tests as the per-PR gate.

No org move or public repos are required to run it manually — same-account private
repos are clonable with the App token.
