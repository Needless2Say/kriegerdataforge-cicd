# Design note — E2E as a per-repo CI job (composite action), not a callable workflow

**Status: APPROVED — owner decided 2026-07-07 (composite action + no central registry).**
Implementation in progress. Live status + PR links: [`e2e-cijob-refactor-LOG.md`](./e2e-cijob-refactor-LOG.md).

Follow-on to the E2E-decoupling epic (ADR D-006). That epic put each journey's **test assets** in its
tenant repo and made the driver data-driven; this one fixes the last non-generic piece — the **reusable
workflow** — and reshapes how a tenant *invokes* the E2E.

---

## Problem

Today a tenant repo's `e2e-gate.yml` is a job that **`uses:` cicd's reusable workflow**
(`e2e-compose.yml`, `workflow_call`). That reusable workflow still **hardcodes per-tenant content** that
grows every time a tenant is onboarded:

- the journey dropdown `options: [all, fitness, tiffanys, auth]`,
- the App-token `repositories:` list (all tenant repos),
- **6 `actions/checkout` steps**, one per repo.

So adding a tenant still requires editing cicd — the exact scope creep the decoupling epic set out to kill,
just relocated to the workflow. The owner also wants the E2E to be a **real CI job** in the tenant repo,
enabled by that repo's own GitHub **variable**, rather than a callable-workflow indirection.

## Decisions (owner, 2026-07-07)

1. **The E2E is a per-repo CI job, not a callable workflow.** Each tenant repo owns a thin
   `.github/workflows/e2e.yml` job, gated by its own `vars.RUN_E2E_GATE`.
2. **The shared run-logic is a cicd *composite action*** (`.github/actions/run-e2e`) — reusable (fits
   cicd's scope, frozen size), invoked as a *step* inside the tenant's job (not `workflow_call`).
3. **No central registry.** Control is fully per-repo: the `RUN_E2E_GATE` variable is the on/off switch,
   and the job reads the tenant's own `e2e/manifest.json` for the siblings to check out. cicd keeps **no
   tenant list anywhere.** The manifest stays the single "how to run" source of truth, in the tenant repo.

## Target architecture

### cicd (reusable, tenant-agnostic — frozen size)

- **`.github/actions/run-e2e/action.yml`** (NEW, composite) — the whole run-logic, generic. Inputs:
  `journey`, `app-id`, `app-private-key` (composite actions can't read `secrets` directly, so the caller
  passes them), optional `caller-path`. Steps:
  1. free disk; read `<caller>/e2e/manifest.json` → the journey's `repos`;
  2. mint an App token scoped to **`{hub, auth-ui, sdk}` (ecosystem constants) + the manifest's repos**
     (dynamic `repositories:`, not a hardcoded list);
  3. check out cicd + those repos into the sibling layout (a token-authenticated clone loop replaces the
     6 fixed `actions/checkout` steps; the caller repo is already checked out by the job);
  4. set up Python + Node + Playwright; `ci_stack.py up --journey <journey>` → `npm test`; dump logs on
     failure; upload the report; tear down.
- **`e2e/ci_stack.py`, `docker-compose.shared.yml`, `seed_shared.py`, harness** — unchanged engine.
- **`.github/workflows/e2e-compose.yml`** — **deleted** (no more callable workflow).

### Each tenant repo

- **`.github/workflows/e2e.yml`** (replaces `e2e-gate.yml`) — a ~15-line CI job:
  ```yaml
  on:
    pull_request: { branches: [main] }
    workflow_dispatch:            # owner manual runs (repo write-access gates it)
  jobs:
    e2e:
      # Auto-gate on PRs via the variable; a manual dispatch always runs (so the
      # owner can validate on demand without flipping the hard PR gate on).
      if: github.event_name == 'workflow_dispatch' || vars.RUN_E2E_GATE == 'true'
      runs-on: ubuntu-latest
      steps:
        - uses: actions/checkout@SHA
          with: { path: <this-repo-name> }        # sibling layout
        - uses: Needless2Say/kriegerdataforge-cicd/.github/actions/run-e2e@main
          with:
            journey: fitness
            app-id: ${{ secrets.KDF_APP_ID }}
            app-private-key: ${{ secrets.KDF_APP_PRIVATE_KEY }}
  ```
- **`e2e/manifest.json`** — unchanged in role; **cleaned** (see below).

## Manifest cleanup (directive #2)

The driver reads every functional field — `journey`, `app`, `repos`, `compose`, `tests`, `backend`,
`oidc_client`, `env` (verified in `ci_stack.py::_load_manifest`) — and the composite action reads `repos`
to know what to check out. So those all stay (the manifest remains the single SoT the scripts work with).

The one **non-functional / legacy** item is the verbose **`$comment`** string (JSON has no comments; it's
narration now fully covered by the tenant repo's `e2e/README.md`). **Remove `$comment` from all three
manifests.** Nothing else is dead code. *(If you'd also like the default-valued fields trimmed — e.g.
`"tests": "tests"` or `"app": true`, which equal the driver's defaults — say so and I'll drop them too;
I've kept them explicit so the manifest stays self-documenting.)*

## Control model (what you keep)

- **On/off per repo:** set the repo **variable** `RUN_E2E_GATE=true` (Settings → Secrets and variables →
  Actions → Variables). Unset → the job is skipped (a near-instant green no-op).
- **Secrets per repo:** `KDF_APP_ID` + `KDF_APP_PRIVATE_KEY` (the `ops-setup-e2e` issue flow already
  copies these). The job passes them to the action.
- **Owner manual run:** `workflow_dispatch` on the tenant repo's `e2e.yml` (repo write-access is the gate;
  no `_authorize-owner` needed — that was only because cicd is public).

## Phasing / PRs (each: `make check-all` + version bump; owner merges)

- **PR 1 (cicd):** add the composite action + **deprecate** `e2e-compose.yml` (keep it, don't delete yet)
  + update `e2e/README.md` / `docs/reference/WORKFLOWS.md` / `AGENTS.md` + ADR **D-007**. Additive —
  the dormant `e2e-gate.yml` callers still resolve.
- **PRs 2–4 (tenant repos):** replace `e2e-gate.yml` → `e2e.yml` (thin job using the action) + remove
  `$comment` from the manifest. fitness-fe, tiffanys-space, auth-ui.
- **PR 5 (cicd):** delete `e2e-compose.yml` — safe once no caller references it. (Deleting it while a
  tenant still had a `uses:` pointing at it could dangle a reference on that repo's PRs, so it goes last.)
- **Validation:** the composite-action checkout/token leg is Actions-runtime — proven by the **first owner
  dispatch** of a tenant `e2e.yml` (same pattern that validated the original workflow). The driver itself
  is already proven locally + in CI.

**Net:** onboarding a tenant = its own `e2e/` assets + a ~15-line `e2e.yml` + flip `RUN_E2E_GATE`. **Zero
cicd edits** — the composite action reads the tenant's manifest, so it never learns tenant names.

## Risks

| Risk | Mitigation |
|---|---|
| Dynamic checkout (clone loop) replaces `actions/checkout` | plain `git clone --depth 1` with the App token is enough (build contexts just need files); validated by first dispatch |
| App-token `repositories:` from a runtime value | it's a string input that accepts expressions; the resolve step outputs the list |
| Composite action can't read `secrets` | caller passes `app-id`/`app-private-key` as inputs (standard pattern) |
| `jq` availability on the runner | `ubuntu-latest` ships `jq` |
| Interim window | old `e2e-gate.yml` callers stay dormant until swapped; gates remain off |

See ADR **D-007** in [`CHANGELOG_AND_DECISION_LOG.md`](../CHANGELOG_AND_DECISION_LOG.md).
