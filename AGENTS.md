# kriegerdataforge-cicd — Agent Guide

> **This is the canonical agent guide for this repo.** `CLAUDE.md`, `.cursorrules`, and
> `.github/copilot-instructions.md` all point here. Read this first, then follow
> [`WORKFLOW.md`](./WORKFLOW.md) for every task and [`skills.md`](./skills.md) for
> security-sensitive work.

## Vision & purpose — what you're building toward

`kriegerdataforge-cicd` is the **centralized CI/CD platform library** for the KriegerDataForge (KDF)
ecosystem — a single, public home for reusable GitHub Actions workflows and the cross-repo automation
that every tenant repo calls instead of maintaining its own pipelines. KDF's hub (`kriegerdataforge`)
is the auth/identity service, and the ultimate goal is a large multi-tenant data platform that other
apps (fitness-app, tiffanys-space, arthurs-portfolio, and future tenants) build on top of. This repo
is the connective tissue that makes that scale possible: deploy behavior, security gates, version
discipline, and secret handling are defined **once** here and propagate to every consumer at once. A
tenant's `cd.yml` is a thin caller (`uses: Needless2Say/kriegerdataforge-cicd/.github/workflows/<wf>.yml@main`
+ `secrets: inherit`); all the real logic lives here.

The owner's vision is **safe, uniform, least-privilege automation that one person can run and onboard
collaborators into**: every deploy is manual (`workflow_dispatch` only — Vercel git auto-deploy is off),
pauses at a GitHub Environment approval gate before any secret loads, and is fenced by a per-repo
**deployer authorization gate** that fails closed. Credentials never live in `.env` or code — only in
GitHub Environment secrets — and the shared Vercel deploy token plus the `GH_PACKAGES_PAT` are rotated on
a schedule by scripts in this repo. As KDF grows, this library is also the planned home for AI-driven
agent workflows (`agents/`, skeleton only) so automation scales with the platform.

## Tech stack

- **GitHub Actions** — reusable workflows (`on: workflow_call`), called by every tenant repo.
- **Vercel CLI** — a pinned `vercel@48.0.0` CLI (`npm install -g` → `vercel --prod --yes`) for Next.js + FastAPI serverless deploys.
- **Terraform `~1.9`** (`hashicorp/setup-terraform`) — `cd-terraform.yml` runs `plan`/`apply`.
- **Python 3.14 (stdlib-first)** — platform scripts in `scripts/` (token/PAT rotation, DB backup,
  deployer gate, version bump/check); tested with `pytest` + coverage.
- **actionlint** — local + CI lint for all workflow YAML.
- **CodeQL** (`javascript-typescript`) — optional local SAST via the Makefile.

## Module map

| Path | Purpose |
| --- | --- |
| `.github/workflows/cd-nextjs-vercel.yml` | Deploy Next.js → Vercel (fitness-app-frontend, tiffanys-space, arthurs-portfolio) |
| `.github/workflows/cd-python-vercel.yml` | Deploy FastAPI → Vercel + optional Alembic migrations (kriegerdataforge, app backends) |
| `.github/workflows/cd-terraform.yml` | `terraform plan` + `apply` for Vercel infra (kriegerdataforge-terraform) |
| `.github/workflows/bump-version-check.yml` | Validate `VERSION` is exactly +1 semver ahead of `main` |
| `.github/workflows/create-github-release.yml` | Create GitHub Release + git tag from `VERSION` |
| `.github/workflows/ci-*.yml` | Reusable per-stack CI (python lint/typecheck/tests/security/integration, nextjs build/lint/tests, codeql, npm-audit, vercel-compactor) |
| `.github/workflows/issue-create-repo.yml` | Auto-provision new repos from the `new-repo` issue template |
| `.github/workflows/rotate-vercel-tokens.yml`, `distribute-gh-pat.yml`, `check-secret-expiry.yml` | Scheduled secret rotation/distribution + weekly expiry monitor |
| `.github/actions/run-e2e/`, `e2e/`, `.github/workflows/ops-setup-e2e.yml` | Reusable E2E engine (composite action + data-driven `ci_stack.py` driver + secret-distribution workflow) |
| `scripts/check_deployer.py` + `deployer_registry.json` | Per-repo/per-env deployer authorization gate (fail closed) |
| `scripts/rotate_secret.py` + `secret_registry.json` | Unified CI-plane secret rotation engine (modes: generate / paste / check; env-aware) |
| `scripts/common/bump_version.py`, `check_version.py` | Version bump + CI consistency/increment check |
| `scripts/*/db_backup.py` | Per-tenant Neon DB backup |
| `docs/reference/WORKFLOWS.md`, `docs/guides/MANUAL_SETUP.md` | Workflow catalog (inputs/secrets/callers) + manual setup runbook |
| `agents/` | Skeleton for future AI-driven agent workflows — **not yet implemented** |
| `CONTRIBUTING.md` | Two-tier model + breaking-change governance |

## Critical rules

1. **Never commit secrets.** Use `${{ secrets.NAME }}` exclusively — never hardcode, never `echo` a secret.
2. **Pin all third-party actions to a specific tag or SHA** (e.g. `@v6` / full SHA) — never `@main` or `@latest`.
3. **Every deployment workflow MUST set `environment:`** to activate the GitHub Environment approval gate.
4. **Treat every change to an existing workflow as a breaking-change candidate** — all consumer repos
   call these live from `@main`. When in doubt, add a new workflow rather than mutate an existing one.
5. **Adding a `required: true` input, removing/renaming an input, changing an input `type:`, renaming
   a secret, or removing an `output:` is a breaking change** — use `required: false` + `default:`, or
   coordinate the update across all affected consumers first.
6. **Set minimum `permissions:` on every workflow.** `id-token: write` only where Vercel OIDC needs it.
7. **`secrets: inherit` is the standard caller pattern** for passing environment secrets to a reusable workflow.
8. **Never use `pull_request_target` with an untrusted code checkout.**
9. **Environment names are `dev` / `prod`** (plus `github-pages` for GitHub Pages deploys) — NEVER `development` / `production` / `infrastructure` / `infra`.
   (`arthurs-portfolio` uses `github-pages`.) These keys must match `deployer_registry.json`.
10. **Deploys fail closed.** A repo/env/actor not in `scripts/deployer_registry.json` is denied — when you
    onboard a tenant, add its registry entry *before* its first deploy.
11. **`scripts/` is stdlib-first** and unit-tested; keep `make check-all` green before opening a PR.
12. **This repo is the reusable engine ONLY — nothing tenant-specific lives here.** A tenant's app source,
    its E2E/browser spec, its Docker services, its seed data, or any per-tenant list/enum/`case` belongs in
    **that tenant's repo**, never here. **Litmus test:** *if onboarding a new tenant would require editing a
    file in this repo, that's a design smell — make the file data-driven (a manifest the engine discovers)
    instead of adding another hardcoded entry.* This is why the E2E harness is being decoupled: see
    [`docs/design/e2e-test-decoupling.md`](docs/design/e2e-test-decoupling.md) and ADR **D-006**. Keeping
    cicd tenant-agnostic is what lets it scale to N tenants without bloating.

## Commands

| Task | Command |
| --- | --- |
| Lint workflows | `make lint` (actionlint) |
| Run script unit tests | `make test` (pytest in `scripts/`, with coverage) |
| **Full local CI (the gate)** | `make check-all` (runs `lint` + `test`) — **there is no `make ci` target** |
| Type-check | _none in this repo_ (workflow YAML + stdlib scripts; rely on `make lint` + tests) |
| Version bump (patch / minor / major) | `make bump-patch` / `make bump-minor` / `make bump-major` |
| CodeQL local scan (optional) | `make codeql-db` then `make codeql-scan-all` (or `*-csv` variants) |
| List targets | `make help` |

> **Version gate is strict.** `bump-version-check.yml` requires `VERSION` to be **exactly one** valid
> semver increment ahead of `main` (patch `X.Y.Z+1`, minor `X.Y+1.0`, major `X+1.0.0`). No bump,
> skip-by-2, downgrade, or bad format **fails CI**. Always run `make bump-<level>` — never hand-edit.

## Required reading

1. [`README.md`](./README.md) — what this library is, the workflow catalog, deployment + environment-gate model.
2. [`docs/WORKFLOWS.md`](docs/reference/WORKFLOWS.md) — full per-workflow reference: inputs, secrets, caller patterns,
   the **deployer authorization gate**, and the consumer-repo summary.
3. [`docs/MANUAL_SETUP.md`](docs/guides/MANUAL_SETUP.md) — the runbook for everything that can't be automated:
   GitHub Environments, environment secrets, PAT/token creation + rotation, tenant onboarding, org migration.
4. [`CONTRIBUTING.md`](./CONTRIBUTING.md) — the two-tier model (what belongs here vs. a tenant repo) and the
   breaking-change rules for modifying a reusable workflow.
5. [`agents/README.md`](agents/README.md) — the (not-yet-built) AI-agent vision for where this repo is heading.

Quick lookups: workflow inputs/secrets → `docs/reference/WORKFLOWS.md`; setup/secrets/PAT steps → `docs/guides/MANUAL_SETUP.md`; **rotating a secret** (repo / environment) → `docs/guides/SECRET_ROTATION.md`; who can deploy → `scripts/deployer_registry.json`; rotation registry → `scripts/secret_registry.json`.

## How to work in this repo — the agent kit

**Every task follows the tiered loop in [`WORKFLOW.md`](./WORKFLOW.md)** — pick a lane:

- **Quick** — tiny, no-behavior change → implement → `make check-all` → PR.
- **Standard** — a one-repo feature → orient → **plan & owner approves** → implement → `make ci`
  green (+ version bump) → PR → **GitHub CI green** → **owner merges**.
- **Epic** — complex/novel design or anything that **spans repos** → the design gate + cross-repo
  coordination below.

Don't skip the plan-approval gate; don't self-merge. The supporting kit:

- [`docs/agent/DESIGN_AND_EPICS.md`](docs/agent/DESIGN_AND_EPICS.md) — the **design gate** (design
  doc + ADR, owner-approved before code) and the **cross-repo epic playbook** (blast-radius,
  contract-first ordering, flag-gated slices). **Cross-repo epic trackers live in the ecosystem hub
  at `kriegerdataforge/docs/epics/`.**
- [`docs/agent/DEFINITION_OF_DONE.md`](docs/agent/DEFINITION_OF_DONE.md) — the change-type-scaled
  **Definition of Done** (checkbox form in
  [`.github/PULL_REQUEST_TEMPLATE.md`](.github/PULL_REQUEST_TEMPLATE.md)).
- [`docs/agent/templates/`](docs/agent/templates/) — copy-paste **design-spec**, **ADR**, and
  **epic-tracker** templates. ADRs land in `docs/CHANGELOG_AND_DECISION_LOG.md` (create if absent).

> **Note:** this repo is `workflow_call`-shaped — `make ci` maps to **`make check-all`** here (there is
> no plain `ci` target). Because every workflow is consumed live from `@main`, a "one-repo feature" here
> can still ripple into all consumers — when you touch a reusable workflow's interface, treat it as an
> **Epic** (cross-repo) and follow `CONTRIBUTING.md`'s breaking-change rules.

### Before opening a PR (this repo)

- [ ] `make check-all` is green locally (`make lint` actionlint + `make test` pytest in `scripts/`).
- [ ] New/changed Python in `scripts/` has unit tests (`scripts/tests/`); stdlib-first kept.
- [ ] `VERSION` bumped via `make bump-<level>` — **exactly +1** (the strict `bump-version-check.yml` gate).
- [ ] Workflow interface preserved (inputs/outputs/secrets unchanged) **or** all consumers coordinated;
      breaking changes follow `CONTRIBUTING.md`.
- [ ] Touched a workflow YAML → updated `docs/reference/WORKFLOWS.md` (and the consumer/catalog tables) in the same PR.
- [ ] Third-party actions pinned to tag/SHA; minimum `permissions:` set; no secret echoed or committed.
- [ ] New tenant/deploy path → `scripts/deployer_registry.json` entry added.
- [ ] Architectural change (new workflow, gate redesign, rotation/auth model) → ADR + owner approval first.

## Security — read [`skills.md`](./skills.md)

This repo follows the KriegerDataForge ecosystem **security playbook** in [`skills.md`](./skills.md).
**Before any security-sensitive work** — auth/OIDC/tokens, BFF/proxy/CSP/cookies, backend authz/endpoints,
secrets/env/config, Terraform/infra, CI/CD, or dependencies — open `skills.md` and follow the **scenario**
that matches your task.

Non-negotiables (full detail + the scenario rules are in `skills.md`):

- **Fail closed, never open.** The **server is authoritative** — recompute security/$-relevant values
  (totals, prices, roles, status); never trust client-sent ones.
- **Never trust client input** for a security decision — IPs (use the edge header, not raw `X-Forwarded-For`),
  hostnames / `request.url` (the internal bind, not the browser host), `Origin`, ownership (exact check, not a
  substring/regex).
- **Secrets never touch git or logs** — real values only in gitignored files; `.example` holds placeholders;
  never echo a secret; the owner rotates.
- **Least privilege** — closed request schemas + field allow-lists (no blind `setattr`), distinct per-client
  OIDC audiences, validated `iss`/`aud`.
- Found a security issue? **Verify it's real, then flag it** — and **pause for owner approval before any
  architectural, destructive, or behavior-changing edit** (OIDC protocol changes get a design note first).
