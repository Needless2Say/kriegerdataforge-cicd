# Implementation log — Every repo owns a distinct E2E journey

Living log for the plan in [`e2e-every-repo-journeys.md`](./e2e-every-repo-journeys.md) (ADR **D-008**).
Append as each PR lands; do not rewrite history. Legend: ✅ done · 🔧 in progress · ⬜ pending.

## Status grid

| # | Scope | Repo / PR | Status |
| --- | --- | --- | --- |
| 1 | Plan + LOG + ADR D-008 + docs index + engine tweak (`_write_env_file` also emits `secret_env`) | cicd #115 | ✅ done |
| 2 | `fitness-api` journey (backend + identity, headless OIDC) + `e2e.yml`; remove `e2e-gate.yml` | fitness-app-backend #44 | ✅ done |
| 3 | `tiffanys-api` journey + `e2e.yml`; remove `e2e-gate.yml` | tiffanys-space-backend #36 | ✅ done |
| 4 | `hub` journey (hub + auth-db, extensive) + `e2e.yml` (net-new) | kriegerdataforge #264 | ✅ done |
| 5 | Delete `e2e-compose.yml` + reconcile ALL stale refs (Makefile, `e2e/README` CI blurb + enablement table + journeys overview + `if:` template, `ops-setup-e2e` header, ADR anchors) + finish LOGs | cicd #116 | 🔧 in progress |
| 6 | Fix 3 frontend `e2e/README.md` stale `e2e-gate.yml` lines | fitness-fe #310 / tiffanys #139 / auth-ui #43 | ✅ done (PRs open) |
| 7 | Post-merge validation audit (6-dim adversarial) + fix findings + testing docs + CD mode | all repos | 🔧 in progress |

**Each backend/hub journey was proven locally end-to-end** (real Docker stack → spec green) before its PR:
`fitness-api` 2/2, `tiffanys-api` 2/2, `hub` 4/4 (discovery+JWKS, full auth-code+PKCE flow → access/id/refresh
+ userinfo + refresh, wrong-password, bad-token + PKCE-enforcement). The one engine gap the recon surfaced —
the driver injected each journey's client id but not its secret — was fixed in #115 (`_write_env_file` now
emits `secret_env`), which the in-spec confidential token exchange needs.

Merge order: 1 → 2/3/4 (any order) → 5 (must be last: it deletes the workflow the backend `e2e-gate.yml`
callers still point at, so those must be replaced first) → 6 (independent, any time).

## Decisions locked (owner, 2026-07-07)

- **Design Y** — every repo owns a **distinct** journey = its dependency subgraph (repo + downstream deps,
  never upstream consumers). Each repo owns its own `manifest.json` + spec.
- **Hub testing is maximal** — the `hub` journey exercises the full OIDC/auth surface against the built
  image + real DB, no compromises (accepts overlap with `test_oidc_e2e_db.py`).
- **`all` is unused** — each repo runs only its own journey; new journeys are `app: false`.
- **One additive engine tweak (recorded, as anticipated)** — the recon confirmed the driver injects each
  journey's generated OIDC client *id* into `e2e/.env` but **not** the *secret*. Backend/hub specs do the
  code→token exchange themselves (no frontend BFF) and the seeded clients are `confidential`, so they need
  the secret. Fix (PR #115): `_write_env_file` now also emits `oidc_client.secret_env`. Tenant-agnostic; no
  new manifest field, no new action input. Exercised end-to-end by the backend journey validation (a spec
  that can't read the secret `test.skip`s, so a regression is caught immediately).

## Gotchas / notes (append as they surface)

- Backend journeys have no frontend to run the OIDC callback → the spec is the OIDC client (PKCE, drive the
  auth-UI login, capture `code`, `POST /oauth/token`, call the backend API with the bearer token).
- The tenant compose fragment currently starts all three services (`*-db`, `*-api`, `*-nextjs`); the backend
  journey needs to bring up only `*-api` + `*-db` (a backend-scoped fragment or a compose profile).
- Each new-spec repo needs `e2e` in `tsconfig.json` `exclude` so the `@playwright/test` import doesn't break
  `tsc`/`next build` (frontends already did this).
