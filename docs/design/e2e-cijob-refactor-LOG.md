# Implementation log — E2E as a per-repo CI job (composite action)

Living log for the plan in [`e2e-cijob-refactor.md`](./e2e-cijob-refactor.md) (ADR **D-007**). Append as
each PR lands; do not rewrite history. Legend: ✅ done · 🔧 in progress · ⬜ pending.

## Status grid

| # | Scope | Repo / PR | Status |
|---|---|---|---|
| 1 | Plan + log + ADR D-007 + composite action `run-e2e` + deprecate `e2e-compose.yml` + docs | cicd (this PR) | 🔧 in progress |
| 2a | `e2e-gate.yml` → thin `e2e.yml` + slim manifest | fitness-app-frontend | ⬜ pending |
| 2b | `e2e-gate.yml` → thin `e2e.yml` + slim manifest | tiffanys-space | ⬜ pending |
| 2c | `e2e-gate.yml` → thin `e2e.yml` + slim manifest | kriegerdataforge-auth-ui | ⬜ pending |
| 3 | Delete `e2e-compose.yml` (once no caller references it) | cicd | ⬜ pending |
| 4 | Validate by first owner dispatch of a tenant `e2e.yml` | (owner) | ⬜ pending |

Merge order: 1 (cicd, additive — keeps `e2e-compose.yml` so the dormant callers still resolve) →
2a/2b/2c (any order) → 3 (delete the now-unreferenced workflow). Nothing breaks in between: the old
`e2e-gate.yml` callers stay dormant (skipped) and still point at a workflow that still exists until step 3.

## Decisions locked (owner, 2026-07-07)

- **Composite action**, not a callable workflow — the reusable run-logic lives in cicd as
  `.github/actions/run-e2e`; each tenant repo owns a thin CI job that `uses:` it.
- **No central registry** — control is the per-repo `RUN_E2E_GATE` variable; the job reads the tenant's own
  `e2e/manifest.json` for the sibling repos. cicd holds no tenant list.
- **Manifest cleanup** = remove the non-functional `$comment` (every other field is read by the driver /
  action). Default-valued fields kept explicit unless the owner asks to trim them.

## Gotchas / notes (append as they surface)

- Composite actions cannot access `secrets` → the caller passes `KDF_APP_ID` / `KDF_APP_PRIVATE_KEY` as
  action inputs.
- Sibling layout: the tenant job must check itself out into `path: <repo-name>` so `${E2E_WORKSPACE}`
  (= `$GITHUB_WORKSPACE`) + `<repo>` build contexts resolve; the action clones the rest as siblings.
- The checkout/token leg is only provable on a runner → validated by the first owner dispatch.
