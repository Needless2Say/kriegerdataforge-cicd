# Implementation log — E2E as a per-repo CI job (composite action)

Living log for the plan in [`e2e-cijob-refactor.md`](./e2e-cijob-refactor.md) (ADR **D-007**). Append as
each PR lands; do not rewrite history. Legend: ✅ done · 🔧 in progress · ⬜ pending.

## Status grid

| # | Scope | Repo / PR | Status |
| --- | --- | --- | --- |
| 1 | Plan + log + ADR D-007 + composite action `run-e2e` + deprecate `e2e-compose.yml` + docs | cicd #114 | ✅ done |
| 2a | `e2e-gate.yml` → thin `e2e.yml` + slim manifest | fitness-app-frontend #309 | ✅ done |
| 2b | `e2e-gate.yml` → thin `e2e.yml` + slim manifest | tiffanys-space #138 | ✅ done |
| 2c | `e2e-gate.yml` → thin `e2e.yml` + slim manifest | kriegerdataforge-auth-ui #42 | ✅ done |
| 3 | Delete `e2e-compose.yml` (once no caller references it) | cicd (D-008 step 5) | ✅ done |
| 4 | Validate by first owner dispatch of a tenant `e2e.yml` | (owner) | ⬜ pending |

Merge order: 1 (cicd, additive — keeps `e2e-compose.yml` so the dormant callers still resolve) →
2a/2b/2c (any order) → 3 (delete the now-unreferenced workflow).

**Update (2026-07-07):** step 3 is **deferred into D-008**. The sweep for the D-007 cleanup found that the
two tenant **backends** (`fitness-app-backend`, `tiffanys-space-backend`) *also* have dormant `e2e-gate.yml`
callers of `e2e-compose.yml` — so deleting `e2e-compose.yml` now must wait until they (and the hub) are moved
onto real `e2e.yml` jobs under [D-008](./e2e-every-repo-journeys.md) (its step 5 = this step 3). Nothing
breaks meanwhile: every `e2e-gate.yml` caller stays dormant (skipped) and still points at a workflow that
still exists.

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
