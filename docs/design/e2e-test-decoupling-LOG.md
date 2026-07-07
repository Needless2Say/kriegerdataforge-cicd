# Implementation log — E2E test decoupling

Living log for the epic in [`e2e-test-decoupling.md`](./e2e-test-decoupling.md) (ADR **D-006**). Append as
each phase lands; do not rewrite history. Status legend: ✅ done · 🔧 in progress · ⬜ pending.

## Status grid

| Phase | Scope | PR(s) | Status |
|---|---|---|---|
| 0 | Spike: cross-repo compose merge | — (throwaway) | ✅ done — 2026-07-07 |
| 0.5 | Scope guardrail + plan + log + ADR (this PR) | cicd (docs) | 🔧 in progress |
| 1 | cicd engine: data-driven driver + shared compose + generic seed/workflow (additive, fallback kept) | cicd | ⬜ pending |
| 2a | Move fitness journey → `fitness-app-frontend` (+ be seed ref) | fitness-fe | ⬜ pending |
| 2b | Move tiffanys journey → `tiffanys-space` (+ be seed ref) | tiffanys-fe | ⬜ pending |
| 2c | Move auth journey → `kriegerdataforge-auth-ui` | auth-ui | ⬜ pending |
| 3 | cicd cleanup: delete the hardcoded fallback + old specs | cicd | ⬜ pending |

Merge order: 0.5 → 1 → (2a/2b/2c in any order) → 3. Phase 1 keeps the E2E green with **zero** tenant
changes; each Phase-2 PR is independently verifiable by dispatching that journey; Phase 3 only lands once
all three journeys are moved and green.

---

## Phase 0 — spike (✅ 2026-07-07)

**Question:** does `docker compose -f shared.yml -f <tenant-fragment>.yml` resolve build contexts that point
at *different sibling repos*, given Docker resolves relative contexts against the first `-f` file's dir?

**Method:** minimal two-file merge in the scratchpad — `shared.yml` (kdf-api, context
`${E2E_WORKSPACE}/kriegerdataforge`) + `fitness-fragment.yml` (fitness-app-api/nextjs, contexts
`${E2E_WORKSPACE}/fitness-app-{backend,frontend}`) → `docker compose … config`.

**Result: PASS.** With **absolute `${E2E_WORKSPACE}/<repo>` contexts** every path resolved unambiguously
regardless of which file it came from; `e2e-net` and the `gh_packages_pat` secret merged across files. This
is the sanctioned convention for tenant fragments. Relative contexts were **not** used precisely because
multi-`-f` merge would resolve them against the wrong repo.

---

## Phase 0.5 — scope guardrail + docs (🔧 this PR)

- Added **scope guardrail** to `AGENTS.md` (critical rule + "what does NOT belong here") and
  `CONTRIBUTING.md` (E2E rows in the two-tier table) so a future model knows cicd = reusable engine only,
  before it adds a tenant spec here again.
- Added this plan (`e2e-test-decoupling.md`) + log + ADR **D-006**; indexed the design doc in `docs/README.md`.
- No code/behavior change; E2E untouched. VERSION bump-patch.

---

## Decisions & gotchas discovered during implementation

- **Absolute compose contexts, not relative** (Phase 0) — the multi-`-f` first-file resolution rule makes
  relative cross-repo contexts a trap; `${E2E_WORKSPACE}/<repo>` is the fix.
- _(append new findings here as Phases 1–3 land: state-file schema migration, App-token scoping on
  `workflow_call`, per-journey `--grep` routing, any tenant Dockerfile/seed quirks.)_
</content>
