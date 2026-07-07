# Implementation log — E2E test decoupling

Living log for the epic in [`e2e-test-decoupling.md`](./e2e-test-decoupling.md) (ADR **D-006**). Append as
each phase lands; do not rewrite history. Status legend: ✅ done · 🔧 in progress · ⬜ pending.

## Status grid

| Phase | Scope | PR(s) | Status |
|---|---|---|---|
| 0 | Spike: cross-repo compose merge | — (throwaway) | ✅ done — 2026-07-07 |
| 0.5 | Scope guardrail + plan + log + ADR | cicd **#111** (merged) | ✅ done — 2026-07-07 |
| 1 | cicd engine: data-driven driver + shared compose + generic seed/workflow; tenant defs restructured into transitional `e2e/tenants/<j>/` | cicd (this PR) | 🔧 in progress |
| 2a | Relocate `tenants/fitness/` → `fitness-app-frontend/e2e/` | fitness-fe | ⬜ pending |
| 2b | Relocate `tenants/tiffanys/` → `tiffanys-space/e2e/` | tiffanys-fe | ⬜ pending |
| 2c | Relocate `tenants/auth/` → `kriegerdataforge-auth-ui/e2e/` | auth-ui | ⬜ pending |
| 3 | cicd cleanup: delete the `e2e/tenants/` transitional dir | cicd | ⬜ pending |

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

## Phase 0.5 — scope guardrail + docs (✅ cicd #111, merged 2026-07-07)

- Added **scope guardrail** to `AGENTS.md` (critical rule #12 + "what does NOT belong here") and
  `CONTRIBUTING.md` (E2E rows + scope smell test) so a future model knows cicd = reusable engine only.
- Added the plan (`e2e-test-decoupling.md`) + this log + ADR **D-006**; indexed in `docs/README.md`.
- No code/behavior change; E2E untouched.

---

## Phase 1 — cicd engine, data-driven (🔧 this PR)

**Refinement to the D-006 plan (deliberate, safer than the literal "fallback"):** instead of keeping the
old hardcoded path as dead fallback code, Phase 1 **restructures the tenant defs into the final
data-driven shape now, but keeps them transitionally in `cicd/e2e/tenants/<journey>/`**. The driver is
fully data-driven immediately (it discovers manifests), which *exercises* the real Phase-2 mechanism
and de-risks it — with no dead code. The E2E stays green because the transitional manifests live right
here. Phase 2 then just **relocates** each `tenants/<j>/` dir into its tenant repo (sibling-repo
discovery wins on collision); Phase 3 deletes the transitional dir. Same end state + safety, less cruft.

What landed:

- **`docker-compose.shared.yml`** — extracted shared identity layer (db + hub + auth-UI + the
  `gh_packages_pat` secret + `e2e-net`). Absolute `${E2E_WORKSPACE}/<repo>` build contexts.
- **`e2e/tenants/{fitness,tiffanys,auth}/`** — each a `manifest.json` (journey declared as data) +
  (fitness/tiffanys) a `docker-compose.e2e.yml` fragment (only its services; `profiles:` removed —
  selection is by which `-f` files the driver includes) + `tests/<j>.spec.ts` (relocated from
  `e2e/tests/`, byte-identical except the auth spec now reads its client id from **env only**, dropping
  the `.e2e-ci.json` read so it stays portable when it moves to the auth-UI repo).
- **`ci_stack.py`** — rewritten: `discover()` scans sibling repos + `tenants/` for `manifest.json`
  (sibling wins); per-journey cred generation keyed by journey (state schema now `{shared,clients}`);
  `up --journey <all|name|csv>` merges `-f shared [-f fragment…]`; **stages** the active journeys'
  specs into gitignored `e2e/staged-tests/` and **writes `e2e/.env`** so `npm test` runs exactly those
  (no `--grep`). New `stage` subcommand for the delegated stack.
- **`seed_shared.py`** (was `seed_e2e.py`) — the client list is now a tenant-agnostic JSON env
  (`E2E_SEED_CLIENTS`) the driver builds from active manifests; no per-tenant knowledge.
- **`playwright.config.ts`** `testDir → ./staged-tests`; `tsconfig.json` include → `tenants`;
  `.gitignore` add `e2e/staged-tests/`; `Makefile` `e2e` target stages first (`JOURNEY` var);
  **`e2e-compose.yml`** passes `--journey` and the grep-resolution step is gone (driver stages).
- Deleted the monolith `docker-compose.e2e.yml`, `seed_e2e.py`, and the old `tests/*.spec.ts`.
- Fixed two stray tool-call closing tags (`</content>`, `</invoke>`) that leaked into this doc + the plan
  doc in #111 (CI is actionlint+pytest, not markdown, so they slipped through).

**Verified locally (the real engine, end to end):** `docker compose config` merges cleanly (9 services
full stack, 3 auth-only, all `${E2E_WORKSPACE}` contexts absolute); `ci_stack.py up --journey auth` →
**2 auth tests pass (7.4s)**; `up --journey fitness` → **fitness test passes (12.6s)** incl. hub+fitness
DB migrate + catalogue seed driven by the manifest's `backend` block; `down` tears down clean.

**Adversarial review (5 lenses × verify pass) → 4 confirmed findings fixed** (1 false positive refuted):

- **SEC-1 (high) — secret in a failure log.** `_run()` echoes the command on non-zero exit; the hub-seed
  exec passed the generated OIDC client secret in argv (`-e E2E_SEED_CLIENTS={…"client_secret"…}`), which
  GitHub does **not** mask (runtime-generated, not a registered secret). A seed failure would leak it to
  the CI log. **Fixed:** the seed inputs now go via the *environment* (bare `-e NAME` pass-through), never
  argv — re-verified the seed + auth journey still pass. This is exactly the failure-path bug a happy-path
  run can't catch; the review earned its keep here.
- **R1 (low)** — `load_or_make_state` crashed on a corrupt/truncated `.e2e-ci.json` (interrupted write)
  instead of regenerating. **Fixed:** `try/except (JSONDecodeError, OSError)` → fall through to regen.
- **R3 (low)** — a manifest with a wrong `tests` path could stage 0 specs yet the driver reported success
  (`npm test` then died with a confusing "no tests found"). **Fixed:** `_stage_specs` returns the count;
  `cmd_up`/`cmd_stage` fail loudly with a clear message on 0.
- **WF-1 (low)** — the SDK-build `GH_PACKAGES_PAT` lacked the `|| secrets.CICD_PAT` fallback its own
  comment (and all 6 sibling checkouts) promised. **Fixed:** fallback restored.
- **R2 (refuted)** — Windows read-only `rmtree` of `staged-tests/`; not reachable (git checkouts are
  read-write), correctly discarded by the verify pass.

---

## Decisions & gotchas discovered during implementation

- **Absolute compose contexts, not relative** (Phase 0) — the multi-`-f` first-file resolution rule makes
  relative cross-repo contexts a trap; `${E2E_WORKSPACE}/<repo>` is the fix.
- **Specs run from a staged dir, not their repo** — a tenant spec can't be run in place by cicd's
  Playwright (module resolution for `@playwright/test` walks up from the spec, and the tenant repo has no
  `node_modules`). The driver **copies** the active journeys' specs into `cicd/e2e/staged-tests/` (under
  the harness, so resolution works) and journey-prefixes them to avoid name collisions.
- **Selection by `-f` file, not compose `profiles`** — dropping `profiles:` and choosing which fragment
  files to merge is cleaner than profile flags and makes a single-tenant `up` trivial.
- **Specs must not read the driver's `.e2e-ci.json`** — that couples them to a cicd path that won't exist
  after the Phase-2 move. The driver writes the client id into `e2e/.env` (loaded by the config); the
  auth spec now reads `process.env.E2E_AUTH_CLIENT_ID` only.
- **Old flat state files are discarded, not migrated** — `load_or_make_state` regenerates if the file
  lacks the new `shared` key (creds are throwaway; regenerating just churns containers once).
- _(append Phase 2/3 findings: sibling-vs-local discovery precedence in practice, App-token scoping.)_
