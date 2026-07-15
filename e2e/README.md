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
> GitHub Actions via each repo's own `e2e.yml` job (the `run-e2e` composite
> action) — see [CI (GitHub Actions)](#ci-github-actions).

## The journeys under test

Two tenants share the hub + auth-UI, each with a **distinct OIDC client** — the
same browser-only integration, proven per tenant. Each journey's spec lives in
**its own repo** (`fitness-app-frontend/e2e/tests/fitness.spec.ts` `@fitness`,
`tiffanys-space/e2e/tests/tiffanys.spec.ts` `@tiffanys`):

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

A third journey, **`auth`** (`kriegerdataforge-auth-ui/e2e/tests/auth.spec.ts`
`@auth`), tests the shared identity layer at its own level — auth-UI + hub + db, a
**synthetic** OIDC client and **no tenant app** (login → consent → an authorization
code, plus a wrong-password case).

**Per-repo journeys (ADR D-008).** Every repo owns a *distinct* journey scoped to its
dependency subgraph — the repo plus what it depends on downstream, never its upstream
consumers. Beyond the three browser journeys above, three **headless** journeys
(`app: false`, opt-in) exercise the backends + hub directly: the spec itself mints a
**real** hub token via a headless OIDC login (no frontend BFF), then calls the target's
API:

```
hub          (kriegerdataforge)        hub + auth-db — OIDC discovery/JWKS + full
                                        auth-code+PKCE flow → access/id/refresh tokens,
                                        userinfo, refresh, and negatives
fitness-api  (fitness-app-backend)     fitness backend + identity, no frontend →
                                        protected endpoints serve the seeded catalogue
tiffanys-api (tiffanys-space-backend)  tiffanys backend + identity, no frontend → a
                                        protected route (/cart) served WITH the token,
                                        rejected WITHOUT it
```

**Data-driven, tenant-agnostic (ADR D-006 / D-008).** Each journey is declared by an
`e2e/manifest.json` the driver *discovers* in its **own repo** — nothing repo-specific
lives in cicd, so onboarding a repo never edits this one.
`ci_stack.py up --journey fitness` (or `tiffanys`, `auth`, `hub`, `fitness-api`,
`tiffanys-api`, a comma-list, or `all` for the app browser journeys) reads that
manifest, merges the shared compose with the journey's fragment, brings up only what it
needs, and **stages that journey's spec** into `staged-tests/` so `npm test` runs
exactly it — no `--grep`. See
[`docs/design/e2e-every-repo-journeys.md`](../docs/design/e2e-every-repo-journeys.md).

## Prerequisites

- **Node ≥ 20** and **Docker Desktop**.
- The four sibling repos checked out next to each other (`kriegerdataforge`,
  `kriegerdataforge-auth-ui`, `fitness-app-backend`, `fitness-app-frontend`),
  each with its `.env.local` provisioned (RSA dev keypair, `GH_PACKAGES_PAT`,
  a seeded fitness OIDC client). See each repo's `.env.local.example`.
- For the **browser journeys** (`fitness`, `tiffanys`): `GH_NPM_TOKEN` in the
  frontend repo's `.env.local` (or exported) — the frontend images `npm ci` the
  private `@needless2say/report-form` package and fail-closed (npm E401) without it.

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

`docker-compose.shared.yml` (db + hub + auth-UI) + each journey's fragment
(`<tenant-repo>/e2e/docker-compose.e2e.yml`) + `ci_stack.py` are the hermetic
sibling. `ci_stack.py`:

- **discovers** each journey's `manifest.json` (no hardcoded tenant list) and, for
  the requested `--journey`, generates a throwaway RS256 keypair + session secret +
  DB password (shared) and a fixed-per-run OIDC `client_id`/`secret` **per journey**
  (persisted to `e2e/.e2e-ci.json`, gitignored), threading them through the compose
  so the hub, each frontend, and the seed all agree — no capture-and-inject dance;
- merges `-f docker-compose.shared.yml` with the active journeys' fragments, builds
  every service from source (the `dev` image targets, source COPY'd in, **no**
  bind-mounts), brings them up on their own network with healthcheck gating,
  migrates the hub DB + each journey's backend, then seeds the active login user +
  one OIDC client per journey (hub) and each catalogue;
- **stages** the active journeys' specs into `e2e/staged-tests/` (the Playwright
  `testDir`) and writes `e2e/.env`, so `npm test` runs exactly those journeys;
- sources `GH_PACKAGES_PAT` from the environment (the CI secret), falling back to
  `fitness-app-backend/.env.local` locally so you needn't export it by hand; likewise
  `GH_NPM_TOKEN` (env → `fitness-app-frontend`/`tiffanys-space` `.env.local`) for the
  frontends' private-npm `npm ci` (classic-PAT-only — GH Packages npm rejects App tokens).

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

## CI (GitHub Actions) — a per-repo job, via a composite action (ADR D-007)

The E2E is **not** a callable workflow. cicd ships a reusable **composite action**,
[`.github/actions/run-e2e`](../.github/actions/run-e2e/action.yml), and each tenant
repo owns a thin CI job (`.github/workflows/e2e.yml`) that `uses:` it. The action is
tenant-agnostic — it reads the **calling repo's `e2e/manifest.json`** for the sibling
repos, so cicd never learns tenant names.

What the action does: reads the caller's manifest → mints a short-lived App token
(`contents:read`, scoped to `{hub, auth-ui, sdk}` + the manifest's `repos`) → checks
out cicd + those repos as siblings under `$GITHUB_WORKSPACE` (a token clone loop; the
caller repo is already checked out by the job) → `python e2e/ci_stack.py up --journey
<j>` → `npm test` → uploads the report → always tears down. Secrets are auto-masked;
CI gets headroom via `E2E_BUILD_TIMEOUT` / `E2E_WAIT_TIMEOUT`.

## Enabling E2E in a repo — CI gate, CD/nightly, or on demand

Each E2E-journey repo ships a **dormant** CI job, `.github/workflows/e2e.yml`, that
`uses:` the `run-e2e` action and passes the `journey` the repo owns:

| Repo | `journey` | What it exercises |
|---|---|---|
| `fitness-app-frontend` | `fitness` | fitness tenant — full browser journey (login → `/database`) |
| `fitness-app-backend` | `fitness-api` | fitness backend + identity, no frontend — headless OIDC → protected API serves seeded data |
| `tiffanys-space` | `tiffanys` | tiffanys tenant — full browser journey (login → `/shop`) |
| `tiffanys-space-backend` | `tiffanys-api` | tiffanys backend + identity, no frontend — headless OIDC → protected `/cart` served with the token, rejected without |
| `kriegerdataforge-auth-ui` | `auth` | shared identity layer (hosted login/consent + hub + db), a synthetic client, no tenant app |
| `kriegerdataforge` (hub) | `hub` | shared identity core — OIDC discovery/JWKS + full auth-code+PKCE flow + userinfo + refresh + negatives, vs. the built image + real DB |

### Three run modes (two variables)

The job stays dormant until you opt into a mode. It reacts to two repo **variables**
(Settings → Secrets and variables → Actions → Variables):

| Mode | Set | When E2E runs | Use it when |
|---|---|---|---|
| **CI gate** | `RUN_E2E_GATE = true` | every PR to `main` | you want E2E to **block** merges (hard per-PR gate) |
| **CD / nightly** | `RUN_E2E_CD = true` | on **push to `main`** (post-merge) + **weekly** | you **don't** want E2E on every PR, but want it before/after deploy + on a schedule |
| **On demand** | *(neither)* | only a manual **`workflow_dispatch`** | you want to run it yourself, ad hoc |

A manual `workflow_dispatch` **always** runs, regardless of the variables (repo
write-access is the gate). The two variables are independent — set both for a per-PR
gate *and* a nightly safety net, or just `RUN_E2E_CD` to keep PRs fast.

```yaml
# <repo>/.github/workflows/e2e.yml
on:
  pull_request: { branches: [main] }   # CI gate  — opt in with RUN_E2E_GATE
  push: { branches: [main] }           # CD       — opt in with RUN_E2E_CD
  schedule: [{ cron: "0 6 * * 1" }]    # weekly   — opt in with RUN_E2E_CD
  workflow_dispatch:                   # manual   — always runs
permissions: { contents: read }
jobs:
  e2e:
    if: >-
      github.event_name == 'workflow_dispatch' ||
      (github.event_name == 'pull_request' && vars.RUN_E2E_GATE == 'true') ||
      ((github.event_name == 'push' || github.event_name == 'schedule') && vars.RUN_E2E_CD == 'true')
    runs-on: ubuntu-latest
    timeout-minutes: 45
    steps:
      - uses: actions/checkout@<sha>
        with: { path: ${{ github.event.repository.name }} }   # sibling layout
      - uses: Needless2Say/kriegerdataforge-cicd/.github/actions/run-e2e@main
        with:
          journey: fitness   # ← this repo's journey
          app-id: ${{ secrets.KDF_APP_ID }}
          app-private-key: ${{ secrets.KDF_APP_PRIVATE_KEY }}
```

**Secrets (needed for any mode that actually runs):** `KDF_APP_ID`,
`KDF_APP_PRIVATE_KEY` — the action mints its App token from these (they live only on
the cicd repo today; an org move would make them org-level and skip this per-repo
step). Browser journeys whose frontend consumes `@needless2say/*` npm packages also
pass `gh-npm-token: <the repo's GH_NPM_TOKEN secret>` (classic PAT, `read:packages`) —
the App token cannot authenticate to GH Packages npm. The `ops-setup-e2e` issue flow copies the secrets and sets `RUN_E2E_GATE=false`;
set `RUN_E2E_GATE`/`RUN_E2E_CD=true` when ready. For the CI-gate mode, also add the
resulting **E2E** check to branch protection → *Require status checks to pass*.

> **Caveat — cross-repo lockstep.** A PR that must change two repos together (an
> OIDC-contract change in the hub *and* the frontend, an SDK bump) can't go green in
> either repo's per-PR gate — each tests against the other's old `main`. So for the
> tightly-coupled repos the recommended posture is the **CD / nightly** mode
> (`RUN_E2E_CD`) rather than a hard per-PR gate, keeping the fast in-repo contract
> tests as the per-PR check.

No org move or public repos are required to run it manually — same-account private
repos are clonable with the App token.
