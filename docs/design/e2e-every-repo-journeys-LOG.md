# Implementation log — Every repo owns a distinct E2E journey

Living log for the plan in [`e2e-every-repo-journeys.md`](./e2e-every-repo-journeys.md) (ADR **D-008**).
Append as each PR lands; do not rewrite history. Legend: ✅ done · 🔧 in progress · ⬜ pending.

## Status grid

| # | Scope | Repo / PR | Status |
| --- | --- | --- | --- |
| 1 | Plan + LOG + ADR D-008 + docs index | cicd (this PR) | 🔧 in progress |
| 2 | `fitness-api` journey (backend + identity, headless OIDC) + `e2e.yml`; remove `e2e-gate.yml` | fitness-app-backend | ⬜ pending |
| 3 | `tiffanys-api` journey + `e2e.yml`; remove `e2e-gate.yml` | tiffanys-space-backend | ⬜ pending |
| 4 | `hub` journey (hub + auth-db, extensive) + `e2e.yml` (net-new) | kriegerdataforge | ⬜ pending |
| 5 | Delete `e2e-compose.yml` + reconcile stale refs + finish `e2e-cijob-refactor-LOG` | cicd | ⬜ pending |
| 6 | Fix 3 frontend `e2e/README.md` stale `e2e-gate.yml` lines | fitness-fe / tiffanys / auth-ui | ⬜ pending |

Merge order: 1 → 2/3/4 (any order) → 5 (must be last: it deletes the workflow the backend `e2e-gate.yml`
callers still point at, so those must be replaced first) → 6 (independent, any time).

## Decisions locked (owner, 2026-07-07)

- **Design Y** — every repo owns a **distinct** journey = its dependency subgraph (repo + downstream deps,
  never upstream consumers). Each repo owns its own `manifest.json` + spec.
- **Hub testing is maximal** — the `hub` journey exercises the full OIDC/auth surface against the built
  image + real DB, no compromises (accepts overlap with `test_oidc_e2e_db.py`).
- **`all` is unused** — each repo runs only its own journey; new journeys are `app: false`.
- **No engine change expected** — the `run-e2e` action already reads the caller's manifest. Any additive
  `ci_stack.py` tweak that proves necessary will be recorded here.

## Gotchas / notes (append as they surface)

- Backend journeys have no frontend to run the OIDC callback → the spec is the OIDC client (PKCE, drive the
  auth-UI login, capture `code`, `POST /oauth/token`, call the backend API with the bearer token).
- The tenant compose fragment currently starts all three services (`*-db`, `*-api`, `*-nextjs`); the backend
  journey needs to bring up only `*-api` + `*-db` (a backend-scoped fragment or a compose profile).
- Each new-spec repo needs `e2e` in `tsconfig.json` `exclude` so the `@playwright/test` import doesn't break
  `tsc`/`next build` (frontends already did this).
