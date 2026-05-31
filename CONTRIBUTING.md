# Contributing to kriegerdataforge-cicd

This is the **platform CI/CD library** for the KriegerDataForge ecosystem — a centralized
home for reusable GitHub Actions workflows that every tenant repo calls.

---

## Two-Tier Model

```
Tier 1 — this repo                   Tier 2 — each tenant repo
──────────────────────               ─────────────────────────────────
Reusable workflow YAMLs     ←────── .github/workflows/cd.yml (caller)
Platform scripts                     .github/workflows/ci.yml (app CI)
Issue templates                      .github/workflows/release.yml
docs/, prompts/                      App source, Dockerfile, Makefile
```

Every tenant repo delegates deployment to a reusable workflow here. The tenant's `cd.yml`
is a thin caller — all deploy logic lives in this repo.

---

## What Belongs Here vs. in a Tenant Repo

| Thing | Here (`kriegerdataforge-cicd`) | Tenant repo |
| --- | --- | --- |
| Reusable deploy logic | `cd-nextjs-vercel.yml`, `cd-python-vercel.yml`, `cd-terraform.yml` | — |
| Version bump validation | `bump-version-check.yml` | — |
| Release tag + GitHub Release | `create-github-release.yml` | — |
| Internal platform automation | `issue-create-repo.yml`, `rotate-vercel-tokens.yml` | — |
| Deployment caller workflow | — | `.github/workflows/cd.yml` |
| App CI (lint / typecheck / tests) | — | `.github/workflows/ci.yml` |
| Release trigger | — | `.github/workflows/release.yml` |
| Platform scripts (token rotation, DB backups) | `scripts/` | — |
| App source code | — | `api/`, `src/`, etc. |
| App-specific Docker / Makefile | — | `Dockerfile`, `Makefile` |
| Issue templates for repo provisioning | `.github/ISSUE_TEMPLATE/` | — |
| Onboarding and setup docs | `docs/MANUAL_SETUP.md` | — |

**Rule of thumb:** if the same logic would need to exist in more than one tenant repo,
it belongs here. If it's specific to one app's stack, it stays in that tenant repo.

---

## Adding a New Reusable Workflow

1. Create `.github/workflows/<name>.yml` with `on: workflow_call`.
2. Add `permissions:` at the workflow level — minimum necessary only.
3. All secrets must flow via `secrets: inherit` from the caller; never hard-code values.
4. All inputs must have explicit `type:` and `description:` fields.
5. Document it in `docs/WORKFLOWS.md`:
   - Purpose and what it does (numbered steps).
   - Caller pattern (copy-paste YAML).
   - Required secrets table.
   - Inputs table.
   - Add to the Consumer Repo Summary table.
6. Add to the Implemented Workflows table in `AGENTS.md`.
7. Run `make lint` to validate the YAML.

---

## Modifying an Existing Workflow — Breaking Change Rules

Every change to a reusable workflow is a potential breaking change because all consumer
repos call them live from `@main`.

| Change type | Safe? | Rule |
| --- | --- | --- |
| Add an optional input with a `default:` | Yes | Always backwards-compatible |
| Add a required input (`required: true`) | **No** | Breaks all callers that don't pass it — coordinate first |
| Remove or rename an input | **No** | Breaks callers passing the old name |
| Change an input's `type:` | **No** | Breaks callers — types must not change |
| Rename a secret | **No** | Coordinate across all repo environments first |
| Change step behavior / runtime | Caution | Test on a feature branch using a consumer caller |

When in doubt: add, don't change. Deprecate old inputs by keeping them optional and
ignoring them rather than removing them. The cost of a broken deploy across three consumer
repos is much higher than the cost of an extra unused input.

---

## PR Process

- One logical change per PR.
- If the change touches a workflow YAML, also update `docs/WORKFLOWS.md` in the same PR.
- If the change is a breaking change: open a tracking issue on every affected consumer repo
  and coordinate the update before merging here.
- Run `make lint` before opening the PR.

---

## Adding a New Consumer (Tenant) Repo

1. Create the repo via the issue template: open a `new-repo` issue in this repo — the
   `issue-create-repo.yml` workflow handles provisioning automatically.
2. In the new repo's `cd.yml`, call the appropriate reusable workflow:
   ```yaml
   jobs:
     deploy:
       uses: Needless2Say/kriegerdataforge-cicd/.github/workflows/cd-*.yml@main
       with:
         environment: ${{ inputs.environment }}
         version: ${{ inputs.version }}
       secrets: inherit
   ```
3. Add the new repo to the Consumer Repo Summary table in `docs/WORKFLOWS.md`.
4. Add it to the "Called by" column of the matching workflow in `AGENTS.md`.

---

## Deferred: `scripts_dir` Input

Reusable workflows currently assume the standard KDF project layout
(compactor at `scripts/vercel_compactor.py`, Alembic at project root, `vercel_api/` output dir).
A `scripts_dir` input to support non-standard layouts is **deferred** until the first tenant
that actually needs it.
