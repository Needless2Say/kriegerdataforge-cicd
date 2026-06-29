# Contributor Onboarding — kriegerdataforge-cicd

Welcome. This is the **centralized CI/CD platform library** for the KriegerDataForge (KDF)
ecosystem: a single, **public** home for reusable GitHub Actions workflows and the cross-repo
automation that every tenant repo calls instead of maintaining its own pipelines. A tenant's
`cd.yml` is a thin caller (`uses: Needless2Say/kriegerdataforge-cicd/.github/workflows/<wf>.yml@main`
+ `secrets: inherit`) — all the real logic lives here.

This guide gets you from a fresh clone to a green local gate and your first PR. For the *why* behind
the platform, read [`AGENTS.md`](../../AGENTS.md) first; for the task loop, read
[`WORKFLOW.md`](../../WORKFLOW.md). This doc is the practical setup layer underneath both.

> **The mindset that matters most here:** every workflow in `.github/workflows/` is consumed **live
> from `@main`** by three or more tenant repos. There is no staging copy. A change to a reusable
> workflow's *interface* (inputs, outputs, secrets) can break every consumer's deploy at once. When in
> doubt, **add, don't change** — and treat interface changes as cross-repo Epics. See the breaking-change
> rules in [`CONTRIBUTING.md`](../../CONTRIBUTING.md).

---

## 1. Prerequisites

| Tool | Version | Why | Install |
| --- | --- | --- | --- |
| **Git** | any recent | clone / branch / PR | system package manager |
| **Python** | **3.13** (stdlib-first) | the platform scripts in `scripts/` + their tests | python.org or pyenv |
| **pip** | bundled with Python | install test deps | — |
| **actionlint** | latest | lint all workflow YAML — this is the primary local gate | `brew install actionlint` **or** `go install github.com/rhysd/actionlint/cmd/actionlint@latest` |
| **pre-commit** | latest | local `gitleaks` secret scan before a commit lands | `pip install pre-commit` |
| **GNU Make** | any | the `make` targets (`lint` / `test` / `check-all` / `bump-*`) | system package manager (on Windows use Git Bash / WSL) |
| **GitHub CLI (`gh`)** | latest | watch PR checks, open PRs | cli.github.com |
| **CodeQL CLI** | latest | *optional* — local SAST via `make codeql-*` | github/codeql-cli-binaries |

Notes:

- **`make` on Windows:** the Makefile auto-detects Windows (it uses `py` instead of `python3`), but
  the recipes use POSIX shell (`grep`, `awk`, `printf`, `command -v`). Run `make` from **Git Bash** or
  **WSL**, not raw PowerShell/cmd.
- **`actionlint` is optional-but-expected.** `make lint` *skips* gracefully with a warning if
  `actionlint` isn't on `PATH` — but CI does **not** skip, so install it locally or your PR will fail
  the workflow-lint job after push. Don't rely on the skip.

---

## 2. Clone & install

```bash
git clone https://github.com/Needless2Say/kriegerdataforge-cicd.git
cd kriegerdataforge-cicd

# one-time: install the pre-commit secret-scan hook (PL-027)
pip install pre-commit
pre-commit install
```

The script test dependencies are installed **automatically** by `make test` (it runs
`pip install -r scripts/requirements-test.txt -q` for you). If you prefer to install them up front:

```bash
pip install -r scripts/requirements-test.txt
```

### No `.env` here

This repo deliberately has **no `.env` files and no `.env.example`**. All credentials live as
**GitHub Environment secrets** and are only ever referenced as `${{ secrets.NAME }}` inside
workflows. There is nothing to configure locally to run the lint/test gate. (The runbook for
creating and rotating those secrets in GitHub is [`docs/MANUAL_SETUP.md`](MANUAL_SETUP.md) — that is
owner-operated setup, not something you wire up to develop here.)

---

## 3. Run the gate locally — `make check-all`

There is **no app to "run"** in this repo — the deliverables are reusable workflows (executed by
GitHub Actions on the consumer side) and stdlib Python scripts. "Running it locally" means running the
validation gate:

```bash
make lint        # actionlint over every file in .github/workflows/
make test        # pytest in scripts/ with coverage
make check-all   # both of the above — THE local gate
```

> **`make check-all` is the gate.** In [`WORKFLOW.md`](../../WORKFLOW.md) the universal step is
> `make ci`; **this repo has no `ci` target** — `make ci` maps to **`make check-all`** here. Keep it
> green before you open a PR.

Other useful targets (`make help` lists them all):

| Task | Command |
| --- | --- |
| Lint workflows | `make lint` |
| Run script unit tests + coverage | `make test` |
| **Full local gate** | `make check-all` |
| Bump version (pick by impact) | `make bump-patch` / `make bump-minor` / `make bump-major` |
| Optional local CodeQL scan | `make codeql-db` then `make codeql-scan-all` (or `*-csv` to paste into an AI) |

### Version bump is strict

`bump-version-check.yml` requires `VERSION` to be **exactly one** valid semver increment ahead of
`main` (patch `X.Y.Z+1`, minor `X.Y+1.0`, major `X+1.0.0`). No bump, skip-by-2, downgrade, or bad
format **fails CI**. Always run `make bump-<level>` — **never hand-edit `VERSION`**. Pick the level by
impact: no behavior/contract change → patch; backward-compatible/additive → minor; a breaking
workflow-interface change → major.

---

## 4. Where the code lives — module map

| Path | What's there |
| --- | --- |
| `.github/workflows/cd-nextjs-vercel.yml` | Deploy Next.js → Vercel (fitness-app-frontend, tiffanys-space, arthurs-portfolio) |
| `.github/workflows/cd-python-vercel.yml` | Deploy FastAPI → Vercel + optional Alembic migrations |
| `.github/workflows/cd-terraform.yml` | `terraform plan` + `apply` for Vercel infra |
| `.github/workflows/ci-*.yml` | Reusable per-stack CI (python lint/format/typecheck/tests/security, nextjs build/lint/tests, codeql, npm-audit, vercel-compactor) |
| `.github/workflows/bump-version-check.yml` | Validate `VERSION` is exactly +1 semver ahead of `main` |
| `.github/workflows/create-github-release.yml` | Create a GitHub Release + git tag from `VERSION` |
| `.github/workflows/secret-scan.yml` | Post-push secret-scan backstop over the PR diff |
| `.github/workflows/_authorize-owner.yml` | Owner-gate reused by the privileged ops workflows |
| `.github/workflows/rotate-vercel-tokens.yml`, `distribute-gh-pat.yml`, `check-gh-pat-expiry.yml`, `distribute-kit.yml` | Scheduled / owner-gated secret rotation + kit distribution |
| `.github/workflows/issue-create-repo.yml` | Auto-provision a new repo from the `new-repo` issue template |
| `.github/ISSUE_TEMPLATE/` | `new-repo.yml`, the owner ops templates (`ops-*.yml`), plus the standard bug/feature templates |
| `scripts/check_deployer.py` + `deployer_registry.json` | Per-repo/per-env **deployer authorization gate** (fail closed) |
| `scripts/rotate_vercel_tokens.py`, `rotate_gh_pat.py` | Token/PAT rotation logic (registries: `vercel_token_registry.json`, `gh_pat_registry.json`) |
| `scripts/distribute_kit.py` + `kit_registry.json` | Agentic-kit distribution to tenant repos |
| `scripts/common/bump_version.py`, `check_version.py` | Version bump + CI consistency/increment check |
| `scripts/<tenant>/db_backup.py` | Per-tenant Neon DB backup |
| `scripts/tests/` | pytest suite for everything in `scripts/` (this is what `make test` runs) |
| `kit/common/` | The canonical agentic-kit sources synced byte-identical into every repo (`WORKFLOW.md` etc.) |
| `agents/` | Skeleton for future AI-driven agent workflows — **not yet implemented** |
| `docs/WORKFLOWS.md` | Full per-workflow reference: inputs, secrets, caller patterns, the deployer gate |
| `docs/MANUAL_SETUP.md` | Owner runbook: environments, secrets, PAT/token creation + rotation, tenant onboarding |
| `docs/CHANGELOG_AND_DECISION_LOG.md` | ADRs (`D-NNN`) — record architectural decisions here |

When you touch a workflow YAML, update `docs/WORKFLOWS.md` (and the catalog/consumer tables in
`README.md` + `AGENTS.md`) **in the same PR**.

---

## 5. How reusable workflows are consumed

You'll be editing workflows that other repos call. The consumer side looks like this — a thin caller
that passes inputs and inherits secrets:

```yaml
jobs:
  deploy:
    uses: Needless2Say/kriegerdataforge-cicd/.github/workflows/cd-python-vercel.yml@main
    with:
      environment: ${{ inputs.environment }}
      version: ${{ inputs.version }}
    secrets: inherit
```

Implications for how you change things here:

- **Inputs/outputs/secrets are a public contract.** Adding a `required: true` input, removing or
  renaming an input, changing an input `type:`, renaming a secret, or removing an `output:` **breaks
  callers**. Use `required: false` + `default:`, or coordinate the change across all consumers first
  (see the breaking-change table in [`CONTRIBUTING.md`](../../CONTRIBUTING.md)).
- **Pin every third-party action** to a tag or full SHA — never `@main` / `@latest`.
- **Every deploy workflow sets `environment:`** to activate the GitHub Environment approval gate, and
  sets **minimum `permissions:`** (`id-token: write` only where Vercel OIDC needs it).
- **Deploys fail closed.** A repo/env/actor not in `scripts/deployer_registry.json` is denied — when
  you onboard a tenant, add its registry entry *before* its first deploy. Environment names are exactly
  `dev` / `prod` / `infra` (and `github-pages` for arthurs-portfolio) — these keys must match the
  registry.
- **Privileged ops workflows are owner-gated.** Token/PAT rotation and kit distribution go through
  `_authorize-owner.yml`; don't loosen that gate.

---

## 6. Pick a lane → plan → approve → PR

Every task follows the tiered loop in [`WORKFLOW.md`](../../WORKFLOW.md). Size the ceremony to the work:

- **Quick** — a typo, comment, or a one-file no-behavior fix → implement → `make check-all` → bump →
  branch → PR.
- **Standard** — a one-repo feature or fix → **orient → plan & the owner approves → implement →
  `make check-all` green (+ version bump) → PR → GitHub CI green → owner merges.**
- **Epic** — complex/novel design, or anything spanning more than one repo. **Touching a reusable
  workflow's interface counts as an Epic** even though the edit is in this one repo, because it ripples
  into every consumer. Follow the design gate in
  [`docs/agent/DESIGN_AND_EPICS.md`](../agent/DESIGN_AND_EPICS.md) and the breaking-change rules in
  [`CONTRIBUTING.md`](../../CONTRIBUTING.md).

Non-negotiables: **don't skip the plan-approval gate; don't self-merge.** Branch off `main`
(`{type}/{short-description}`), use Conventional-Commit messages, stage files **explicitly** (never
`git add -A`), self-review your diff, and fill in the PR template
([`.github/PULL_REQUEST_TEMPLATE.md`](../../.github/PULL_REQUEST_TEMPLATE.md)). The full bar is in
[`docs/agent/DEFINITION_OF_DONE.md`](../agent/DEFINITION_OF_DONE.md).

### Before you open a PR (this repo)

- [ ] `make check-all` is green locally (`actionlint` + `pytest` in `scripts/`).
- [ ] New/changed Python in `scripts/` has unit tests in `scripts/tests/`; kept stdlib-first.
- [ ] `VERSION` bumped via `make bump-<level>` — **exactly +1** (the strict `bump-version-check.yml` gate).
- [ ] Workflow interface preserved (inputs/outputs/secrets unchanged) **or** all consumers coordinated.
- [ ] Touched a workflow YAML → updated `docs/WORKFLOWS.md` and the catalog tables in the same PR.
- [ ] Third-party actions pinned to tag/SHA; minimum `permissions:` set; no secret echoed or committed.
- [ ] New tenant/deploy path → `scripts/deployer_registry.json` entry added.
- [ ] Architectural change (new workflow, gate redesign, rotation/auth model) → ADR + owner approval first.

---

## 7. Security work — read `skills.md` first

Before any security-sensitive change — supply-chain/action pinning, the privileged ops/rotation
workflows, secret handling, the deployer gate, or CI/CD changes — open the ecosystem security playbook
[`skills.md`](../../skills.md) and follow the scenario that matches your task. The disclosure process for
vulnerabilities is in [`SECURITY.md`](../../SECURITY.md). Core rules: **fail closed**, **least
privilege**, and **secrets never touch git or logs** — real values live only in GitHub Environment
secrets, and the owner rotates them. If you find a security issue, **verify it's real, then flag it**,
and pause for owner approval before any behavior-changing edit.

---

## 8. Getting unblocked

- **Don't understand the purpose or how your task fits the goal?** Stop and ask — that's step 1 of the
  Standard lane, not a failure.
- **Workflow inputs / secrets / caller pattern?** → [`docs/WORKFLOWS.md`](../reference/WORKFLOWS.md).
- **Environments, secrets, PAT/token setup, tenant onboarding, org migration?** → [`docs/MANUAL_SETUP.md`](MANUAL_SETUP.md).
- **Who can deploy what?** → `scripts/deployer_registry.json`. **Rotation registries** →
  `scripts/vercel_token_registry.json`, `scripts/gh_pat_registry.json`. **Kit distribution** →
  `scripts/kit_registry.json`.
- **What belongs here vs. a tenant repo?** → the two-tier table in [`CONTRIBUTING.md`](../../CONTRIBUTING.md).
- **Past architectural decisions?** → [`docs/CHANGELOG_AND_DECISION_LOG.md`](../CHANGELOG_AND_DECISION_LOG.md).
- **`actionlint` flags YAML you didn't write?** Re-run `make lint`; fix the reported line, or ask if
  the rule conflicts with a deliberate pattern.
- Still stuck? Open a question issue (the bug/feature templates are in `.github/ISSUE_TEMPLATE/`) or
  raise it with the owner. **Never push a guess to `@main` — every consumer deploys from it.**
