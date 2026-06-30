# Design — KriegerDataForge "Ops Console" (issue-form front-ends for privileged operations)

> Status: **Approved 2026-06-27** · Tier: Epic · Repos touched: `kriegerdataforge-cicd` (the PRs/changes it
> drives span the ecosystem) · Decision log: D-002 · Owner: Arthur (Needless2Say)

## 1. Overview

- **One sentence:** Issue-form front-ends for privileged ecosystem operations (kit distribution, secret
  rotation) that give a real multi-select UI and an audit trail, layered over the existing engine scripts
  and a single fail-closed owner-only gate.
- **Problem:** `workflow_dispatch` can't multi-select (its `choice` input is single-select); you must type
  exact names. Privileged ops also leave no first-class record of who/what/when. And **this repo is public**
  (not yet an org), so anyone can open an issue — the authorization gate is the load-bearing control.
- **Goal:** A human-friendly, auditable, consistent, **owner-only** interface for ops — without duplicating
  engine logic or weakening security.

## 2. User stories

- As the owner, I want to trigger a kit distribution to a **multi-selected subset** of repos from a
  dropdown, instead of typing comma-separated names.
- As the owner, I want each privileged operation recorded as an **issue** (who/what/when + result links).
- As the owner, I want it to be **impossible for anyone but me to actually run** these operations, even
  though the repo is public.

## 3. Requirements (MoSCoW)

- **Must:** owner-only execution (fail closed); multi-select UI; reuse the existing engine scripts; never
  put a secret value in an issue; injection-safe handling of issue content; comment results back.
- **Should:** manual-label trigger (deliberate "go"); a confirmation checkbox for destructive ops; minimal
  workflow `permissions`.
- **Could:** a CI guard that a form's repo options match `kit_registry.json`.
- **Won't (now):** replacing `workflow_dispatch`/cron (the scheduled drift-alarm and rotation checks need
  them); a custom web UI; auto-generating GitHub PATs (GitHub does not allow it).

## 4. UX / interaction

1. Owner opens the matching **issue form** (`.github/ISSUE_TEMPLATE/ops-*.yml`) and fills the dropdowns.
2. The form applies a benign `ops` label on creation (categorization, **non-triggering**).
3. Owner **manually adds the `ops:<name>` trigger label** — the deliberate "go". (Only users with
   triage/write can label; here that's only the owner.)
4. The parser workflow runs **iff** the actor is the repository owner, parses the selections, calls the
   engine script, **comments the result** (PR links / report) back, and closes the issue.
5. Re-run by re-adding the label.

## 5. Technical design

**Architecture — one engine, many front-ends** (the engine is unchanged):

```text
issue form (multi-select UI) ─┐
workflow_dispatch (CLI/UI)    ─┼─→ distribute_kit.py / rotate_*.py ─→ owner-reviewed PRs / secret writes
schedule (cron drift-alarm)   ─┘        (the only place logic lives)
```

**The gate (`.github/workflows/_authorize-owner.yml`, reusable):** a single fail-closed job that compares
`github.triggering_actor` to `github.repository_owner` (case-insensitive) and `exit 1`s otherwise. Every
ops workflow's privileged job `needs:` it, so a denied check short-circuits. `triggering_actor` (not
`event.sender`) is used so a "Re-run jobs" is attributed to whoever re-ran it. This is the same proven
gate `issue-create-repo.yml` already uses, centralized.

**Injection-safety (critical on a public repo):** issue content is attacker-controllable. Parsed values are
passed only via `env:` (quoted), **never** interpolated into a `run:` script, and are **allow-listed**
before use (repos against `kit_registry.json`; mode against a fixed set; rotation target/apps/envs against
the registries). The engine's `--repos` already ignores unknown tokens, so a stale option degrades safely.

**Form 1 — distribute-kit** (`ops-distribute-kit.yml` form + workflow):

- `dropdown` **mode**: `check` / `distribute`
- `dropdown` **repos** (`multiple: true`): the registry repos + `ALL`
- `input` **only**: optional kit-file filter
- workflow → `distribute_kit.py <mode> [--repos "<selected>"] [--only <file>]` (omit `--repos` if `ALL`).

**Form 2 — rotate-secrets** (`ops-rotate-secrets.yml` form + workflow). Backed by the unified engine
`scripts/rotate_secret.py` + `scripts/secret_registry.json` (one entry per CI-plane secret listing every
GitHub-env-secret / non-Terraform-Vercel target). The form picks **secret(s)** (multi-select), a **mode**,
and **environments** (multi):

- **`generate`:** auto-mint fresh value(s). `VERCEL_DEPLOYMENT_TOKEN` mints **one** shared Vercel token via
  the Vercel API (`VERCEL_MASTER_TOKEN` required) and writes that same value to every target — all app
  repos' `prod`/`dev` env secrets and the terraform repo's `prod`/`dev`; per-environment secrets that are
  not the shared token get a distinct value per env.
- **`paste`:** distribute an owner-supplied value. GitHub can't generate PATs, so `GH_PACKAGES_PAT` is
  paste-only — the owner stages the value in the `SECRET_VALUE_NEW` repo secret first (never in the public
  issue body); the engine reads `STAGED_SECRET_VALUE` and fans it to every target. Single secret only.
- **`check`:** expiry report for tracked secrets; needs no live secret.
- A **Confirm = Yes** is required for generate/paste (both write live credentials).
- **Scope guard:** entries flagged `terraform_managed` are refused — app-plane secrets rotate via the
  terraform `SECRETS_ROTATION` runbook, not here.

## 6. Data / secrets

No new data stores. Secrets used by the workflows (already repo secrets): `CICD_PAT` (the `GH_TOKEN` for
secrets/PR writes), `GH_PACKAGES_PAT_NEW` (owner-supplied new PAT, for GH PAT rotation), `VERCEL_MASTER_TOKEN`
(Vercel rotation). **No secret value ever appears in an issue** — the form only selects *what/where*.

## 7. Cross-repo / blast radius

- **Code:** `kriegerdataforge-cicd` only — 2 issue forms, 2 ops workflows, 1 reusable authz workflow, the
  design doc + ADR, and the `ops:*` labels.
- **Effect:** distribute opens owner-reviewed PRs across repos (existing engine behavior); rotation writes
  environment secrets across repos (existing rotate-script behavior). Both already owner-gated.

## 8. Success metrics

The owner can run every privileged op from a multi-select form; a non-owner who opens or labels an ops
issue is denied (workflow fails closed); every run leaves an issue + result comment as the audit record.

## 9. Risks & mitigation

- *Public repo → anyone can open an issue / try to trigger* → owner-only `triggering_actor` gate + only
  triage can label + label-name pinning. Triple-gated, fail closed.
- *Script-injection via issue content* → values via `env:` only, never inlined; allow-list validation.
- *Form repo list drifts from the registry* → engine ignores unknown tokens; optional CI guard (Should).
- *Accidental rotation* → manual-label trigger + required confirmation checkbox.

## 10. Open questions & assumptions

- Assumes the `ops`, `ops:distribute-kit`, `ops:rotate-secrets` labels exist (created as part of rollout).
- Assumes `GH_PACKAGES_PAT_NEW`, `CICD_PAT`, `VERCEL_MASTER_TOKEN` repo secrets exist for the rotate flows
  (owner-managed; the workflow guards on the owner-supplied one being present).

## 11. Running it (quick reference)

The forms and issue-triggered workflows live on the **default branch**, so they are usable only after
this lands on `main`. Then, as the owner:

1. **Issues → New issue** → pick **"Ops · Distribute Agentic-Workflow Kit"** (or **"Ops · Rotate a secret"**).
2. Fill the dropdowns (multi-select the repos / pick the target) and submit.
3. **Add the trigger label** — `ops:distribute-kit` or `ops:rotate-secrets` — to run. The workflow checks
   you are the repository owner, runs the engine, and comments the result back (sanitized for rotation).
4. Re-add the label to re-run.

If a run is denied, the actor was not the repository owner (the gate fails closed) — that is expected on
this public repo.
