# Design note — Every repo owns a distinct E2E journey (its dependency subgraph)

**Status: APPROVED — owner decided 2026-07-07 (Design Y; maximum-robustness hub testing; `all` unused).**
Implementation in progress. Live status + PR links: [`e2e-every-repo-journeys-LOG.md`](./e2e-every-repo-journeys-LOG.md).

Third step of the E2E epic. [D-006](../CHANGELOG_AND_DECISION_LOG.md) relocated each journey's assets
into its tenant repo and made the driver data-driven; [D-007](../CHANGELOG_AND_DECISION_LOG.md) turned
the gate into a per-repo CI job that `uses:` the `run-e2e` composite action (which reads the **caller's**
`e2e/manifest.json`). This step gives **every** repo its own journey — including the two tenant backends and
the hub, which had none.

See ADR **D-008** in [`CHANGELOG_AND_DECISION_LOG.md`](../CHANGELOG_AND_DECISION_LOG.md).

---

## Principle (from the owner's dependency graph)

Each repo's E2E stands up **itself + everything downstream it depends on** (toward the auth DB), and
**never its upstream consumers**. The owner specified the exact downstream set per repo; mapped to the real
compose services (`shared` = `kdf-db` [auth DB] + `kdf-api` [hub] + `kdf-auth-ui`; each tenant fragment adds
its own `*-db` + `*-api` + `*-nextjs`):

| Repo | Journey name | Stack it brings up | Assertion | Test kind |
| --- | --- | --- | --- | --- |
| `kriegerdataforge` (hub) | `hub` | `kdf-api` + `kdf-db` | OIDC discovery + JWKS + full register→login→authorize→token→introspect/refresh against the built image + real DB | API (Playwright request) |
| `kriegerdataforge-auth-ui` | `auth` | + `kdf-auth-ui` | login form → consent → auth code (+ wrong-password) | browser — **exists** |
| `fitness-app-backend` | `fitness-api` | `fitness-app-api` + `fitness-app-db` + identity | headless OIDC login → mint real token → assert protected backend endpoints (+ reject bad/absent token) | browser-login + API |
| `fitness-app-frontend` | `fitness` | + `fitness-app-nextjs` | full browser journey (login → `/database` renders backend data) | browser — **exists** |
| `tiffanys-space-backend` | `tiffanys-api` | `tiffanys-space-api` + `tiffanys-space-db` + identity | headless OIDC login → assert protected backend endpoints | browser-login + API |
| `tiffanys-space` | `tiffanys` | + `tiffanys-space-nextjs` | full browser journey (login → `/shop`) | browser — **exists** |

**Not duplication (D-006 holds).** Each journey is a genuinely different stack + assertion, so each repo
owning its own `manifest.json` + spec is single-ownership, not a copy. `fitness-api` (backend + identity, no
frontend) ≠ `fitness` (full browser).

**Downstream-only** is the key property: a backend PR's gate depends only on the stable identity layer, not
on its frontend's `main`. That is the deliberate escape from the cross-repo-lockstep trap — gates reach only
downstream, never up.

## The engine and the action do not change

The `run-e2e` composite action already (D-007) reads the **caller's** manifest, checks out its `repos`, runs
`ci_stack.py up --journey <j>` then `npm test` on the staged spec. So a new repo just needs, **in its own
repo**:

- `e2e/manifest.json` — its subgraph (see fields in `ci_stack.py::_load_manifest`),
- `e2e/docker-compose.e2e.yml` — its own service(s); `shared` supplies hub + auth-ui + auth-db,
- `e2e/tests/*.spec.ts` — a Playwright spec,
- `.github/workflows/e2e.yml` — the thin job (same template as D-007), `journey: <its own>`,
- `tsconfig.json` → `exclude: ["node_modules", "e2e"]` (so `tsc`/`next build` skips the spec's `@playwright/test` import).

No new manifest field and no new action input are required. **One small, additive engine tweak *is*
included** (the "additive `ci_stack.py` change, recorded in the LOG" this plan anticipated): the driver now
also writes the generated **client *secret*** (`oidc_client.secret_env`) to `e2e/.env`, symmetric to the
client id it already wrote. The browser-app journeys never read it, but a backend/hub spec — which performs
the OIDC code→token exchange **itself** (no frontend BFF) — needs it to authenticate at the token endpoint
(the seeded clients are `confidential` / `client_secret_basic`). It is an ephemeral per-run secret for a
throwaway client in a disposable DB, and `e2e/.env` is gitignored. Tenant-agnostic — a generic engine
capability, not tenant content.

## How the backend / hub specs get a real token (headless OIDC)

The backend and hub journeys have **no frontend** to run the OIDC callback, so the spec plays the OIDC client
itself, entirely inside Playwright:

1. Generate a PKCE pair; open the hub `/authorize` URL for a **synthetic client** the seed created (same
   mechanism as the `auth` journey's synthetic client).
2. Drive the **auth-UI** login form + one-time consent in a real browser context (reusing the existing
   `data-testid` selectors) → capture the `code` off the redirect to a throwaway `redirect_uri`.
3. `POST` the hub `/oauth/token` (code + PKCE verifier) via Playwright's request context → a real access
   token.
4. Call the backend's protected endpoints with `Authorization: Bearer <token>` and assert the data; assert a
   missing/garbage token is rejected (401/403).

The **hub** journey skips the app entirely — it exercises the hub's OIDC surface directly (discovery, JWKS,
the register→login→authorize→token→refresh/introspect lifecycle) against the built image + real Postgres,
the coverage the in-process `test_oidc_e2e_db.py` cannot give (image, config, network). "Extensive, no
compromises" per the owner.

## Naming & `all`

- Journey names are unique registry keys (`discover()` keys on `journey`): `hub`, `fitness-api`,
  `tiffanys-api` (the existing `fitness`, `tiffanys`, `auth` are unchanged).
- All new journeys are **`app: false`** (opt-in). `journey: all` is **not used** — every repo runs only its
  own journey. (`all` remains meaningful only as "the app browser journeys" for any ad-hoc local run.)

## Phasing / PRs (each: `make check-all`/`make ci` + version bump; owner merges)

1. **cicd (this PR):** plan doc + LOG + ADR **D-008** + docs index. No code.
2. **fitness-app-backend:** `e2e/` journey (`fitness-api`) + thin `e2e.yml`; **remove** its `e2e-gate.yml`.
   Proven locally (`ci_stack.py up --journey fitness-api` → spec green) before PR.
3. **tiffanys-space-backend:** same shape (`tiffanys-api`).
4. **kriegerdataforge (hub):** `e2e/` journey (`hub`) + `e2e.yml`. (Hub had **no** `e2e-gate.yml` — this is
   net-new.)
5. **cicd cleanup:** now that no repo references it, **delete** `e2e-compose.yml`; reconcile the stale refs
   it leaves (`ops-setup-e2e.yml`, `e2e/README.md`, `Makefile` comment, the `if:` template in
   `e2e-cijob-refactor.md`); finish `e2e-cijob-refactor-LOG.md`.
6. **frontend doc fix:** the 3 frontend `e2e/README.md` lines that still say `e2e-gate.yml` → `e2e.yml`.

Steps 2–4 are independent (any order); **5 must be last** (deleting `e2e-compose.yml` before the backend
`e2e-gate.yml` callers are replaced would dangle a reference on those repos' PRs).

## Risks

| Risk | Mitigation |
| --- | --- |
| Headless code→token exchange in a spec is fiddly (PKCE, redirect capture) | reuse the `auth` journey's synthetic-client + selector patterns; prove locally before PR |
| Backend fragment must bring up backend **without** the frontend | the tenant's current fragment builds all three services — the backend journey needs a fragment that starts only `*-api` + `*-db` (compose profiles or a backend-scoped fragment); resolved per repo in step 2/3 |
| Hub journey overlaps `test_oidc_e2e_db.py` | intentional — the stack journey adds built-image/network coverage; owner wants maximum |
| `shared` starts `auth-ui` even for the hub journey (hub needs only hub+db) | acceptable extra service, or gate `auth-ui` behind a compose profile — decided in step 4 |
| New spec's `@playwright/test` import breaks the repo's `tsc`/`next build` | add `e2e` to `tsconfig.json` `exclude` (the one edit each frontend already made) |
