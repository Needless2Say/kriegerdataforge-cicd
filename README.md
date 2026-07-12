# kriegerdataforge-cicd

Centralized shared GitHub Actions workflow library for the KriegerDataForge ecosystem. Consumer repos call these reusable workflows instead of maintaining their own deploy pipelines.

This repository is **public** on GitHub. All other KriegerDataForge repos are private.

---

## New here? Start with onboarding

This is the ecosystem's **CI/CD platform repo**: the reusable-workflow library every KDF repo calls,
the per-repo E2E engine (`run-e2e`), the ops console (secret rotation, repo provisioning), and the
**canonical source of the agentic-workflow kit** (`kit/common/` — synced to every repo; see
[`docs/agent/`](docs/agent/)). Nothing tenant-specific lives here — tenant journeys, specs, and app
code belong in the tenant repos.

- **To work in this repo → [`docs/guides/CONTRIBUTOR_ONBOARDING.md`](docs/guides/CONTRIBUTOR_ONBOARDING.md)**
  (clone → `make check-all` green → PR → owner merges; the gate *is* the run here).
- **To understand the kit and how it propagates → [`docs/features/agentic-workflow-kit-sync.md`](docs/features/agentic-workflow-kit-sync.md).**

---

## Documentation & the agentic workflow kit

All documentation lives under [`docs/`](docs/), indexed one-line-per-doc at
[**`docs/README.md`**](docs/README.md). Each subdirectory carries its own README explaining what
belongs there and how to use it:

| Directory | Purpose |
| --- | --- |
| [`docs/agent/`](docs/agent/) | **The agentic-workflow kit** — the shared operating standard (kit-synced; its [README](docs/agent/README.md) explains every kit file and the reading order) |
| [`docs/guides/`](docs/guides/README.md) | How-to walkthroughs: onboarding, E2E testing, secret rotation, manual setup |
| [`docs/reference/`](docs/reference/README.md) | Source-verified contracts: the reusable-workflow catalog |
| [`docs/features/`](docs/features/README.md) | One doc per shipped feature (kit-sync engine, ops console, …) |
| [`docs/design/`](docs/design/README.md) | Design specs from the design gate, paired with ADRs |
| [`docs/security/`](docs/security/README.md) | Security posture and audit notes |
| [`docs/prompts/`](docs/prompts/README.md) | Documentation-authoring prompt toolkit (docs only, never code) |
| [`docs/CHANGELOG_AND_DECISION_LOG.md`](docs/CHANGELOG_AND_DECISION_LOG.md) | The append-only ADR (`D-NNN`) register |

**How to work here:** read [`AGENTS.md`](AGENTS.md) (this repo's vision + critical rules) →
[`WORKFLOW.md`](WORKFLOW.md) (the three-lane task loop) → [`skills.md`](skills.md) (the security
playbook, before any security-sensitive work). Those three plus `docs/agent/` are the kit —
centrally synced from `kit/common/` in this repo; never edit the synced copies locally.

---

## Why Centralized

Keeping CI/CD logic in one place means deploy behavior is consistent across all services, security controls are applied uniformly, and fixes or improvements propagate to every consumer at once. Consumer repos stay clean — their workflow files are just callers with no inline logic.

---

## Workflow Catalog

| Workflow | Purpose | Consumers |
|---|---|---|
| `cd-nextjs-vercel.yml` | Deploy Next.js app to Vercel | fitness-app-frontend, tiffanys-space, arthurs-portfolio |
| `cd-python-vercel.yml` | Deploy FastAPI app to Vercel with optional Alembic migrations | kriegerdataforge, fitness-app-backend, tiffanys-space-backend |
| `cd-terraform.yml` | Run `terraform plan` and `terraform apply` | kriegerdataforge-terraform |
| `create-github-release.yml` | Create a GitHub Release and git tag from the `VERSION` file | All repos with a `release.yml` caller |
| `bump-version-check.yml` | Validate that `VERSION` has been bumped on a PR | All versioned repos |
| `ci-python-security.yml` | Bandit SAST + pip-audit CVE scan for Python repos | kriegerdataforge, kriegerdataforge-sdk |
| `ci-codeql.yml` | CodeQL static analysis (gated by `ENABLE_CODEQL`; needs public repo or Code Security) | kriegerdataforge, kriegerdataforge-sdk |
| `issue-create-repo.yml` | Auto-provision new repositories from an issue template | Internal |
| `rotate-vercel-tokens.yml` | Scheduled rotation of Vercel tokens | Internal |
| `distribute-gh-pat.yml` | Distribute a staged `GH_PACKAGES_PAT` to all targets | Internal |
| `check-secret-expiry.yml` | Weekly credential-expiry monitor → opens/closes a deduped rotation issue | Internal |
| `ops-rotate-secrets.yml` | Owner-only on-demand secret rotation (driven by the `Ops · Rotate a secret` issue form) | Internal |

---

## Deployment Model

All deployments are **manual** (`workflow_dispatch` only). There is no auto-deploy on push to any branch. Vercel's built-in git integration is disabled across all consumer projects (managed via Terraform).

Every deploy job pauses at a GitHub Environment approval gate before secrets are loaded and the deploy runs. No credentials are accessible until a required reviewer approves the deployment.

### Environment Gate Model

Three environment names are used across all repos. Names are fixed — do not use aliases.

| Environment | Approvers | Used for |
|---|---|---|
| `dev` | Owner + collaborators | Development deployments (Vercel apps + Terraform `plan`/`apply`) |
| `prod` | Owner only | Production deployments (Vercel apps + Terraform `plan`/`apply`) |
| `github-pages` | Owner only | GitHub Pages deploy (arthurs-portfolio) |

---

## Consumer Calling Pattern

Consumer repos reference workflows by the full `owner/repo/.github/workflows/filename@ref` path. Secrets are passed through with `secrets: inherit` — the caller never handles credentials directly.

```yaml
jobs:
  deploy:
    uses: Needless2Say/kriegerdataforge-cicd/.github/workflows/cd-python-vercel.yml@main
    with:
      environment: ${{ inputs.environment }}
      version: ${{ inputs.version }}
    secrets: inherit
```

For full input/output references and available secrets for each workflow, see [docs/WORKFLOWS.md](docs/reference/WORKFLOWS.md).

---

## End-to-end (E2E) testing

cicd also hosts the ecosystem's reusable **E2E engine** — the `ci_stack.py` driver, the
shared identity compose, and the **`run-e2e` composite action**. Each repo owns its own
full-stack journey (an `e2e/manifest.json` + a Playwright spec, in *that* repo) and ships
a thin `.github/workflows/e2e.yml` that `uses:` the action — cicd holds no per-repo
content. Every repo runs its journey in one of three modes:

- **CI gate** (`RUN_E2E_GATE=true`) — on every PR (a hard merge gate);
- **CD / nightly** (`RUN_E2E_CD=true`) — on push-to-`main` + weekly, for teams that
  **don't** want E2E on every PR;
- **On demand** — a manual `workflow_dispatch` (always available).

See **[docs/guides/E2E_TESTING.md](docs/guides/E2E_TESTING.md)** for the full model + how
to enable it, and [e2e/README.md](e2e/README.md) for the engine + local run.

---

## Security

Most **deployment/runtime** credentials are stored as GitHub **Environment** secrets — there are no `.env` files and no hardcoded values — so the environment gate is the enforcement point: those secrets only become available after an approved reviewer allows the deployment to proceed. Two shared credentials are the deliberate exception: the account-wide `VERCEL_DEPLOYMENT_TOKEN` (consolidated 2026-06-30) and the build-time `GH_PACKAGES_PAT` (the repo-vs-env split) now live as **repository-level** Actions secrets in the consumer repos, because CI jobs that declare no `environment:` — the reusable `ci-python-*.yml` SDK install and the integration/E2E lanes — must be able to read them (a value written only to an environment is invisible to those jobs, and a same-named env secret would *shadow* the repo value). The per-environment deploy secrets (`VERCEL_PROJECT_ID`, DB URLs, signing keys) stay environment-scoped behind the gate. cicd's **own** repository-level secrets are the ops/control-plane credentials it uses to *manage* the others (`CICD_PAT`, `VERCEL_MASTER_TOKEN`, the `KDF_APP_*` App creds, and staging slots) — see Secret Rotation below.

---

## Secret Rotation

GitHub secrets come in two scopes and rotate differently:

- **Repository secrets** — the store every job can read, *including* CI jobs that declare no
  `environment:`. The shared deploy/build credentials in
  [`scripts/secret_registry.json`](scripts/secret_registry.json) (`VERCEL_DEPLOYMENT_TOKEN`,
  `GH_PACKAGES_PAT`) live here — as **repository-level** Actions secrets in the consumer repos, *not*
  per-environment (a same-named env secret would shadow the repo value). They are rotated by the
  **engine** ([`scripts/rotate_secret.py`](scripts/rotate_secret.py)) — `generate` (auto-mint the Vercel
  token) or `paste` (distribute the owner-staged PAT) — and the engine reaps any retired per-environment
  copies as it goes. Drive it from the **`Ops · Rotate a secret`** issue form (add the
  `ops:rotate-secrets` label) or the CLI. The cicd ops/control-plane secrets that authenticate the engine
  itself (`CICD_PAT`, `VERCEL_MASTER_TOKEN`, `KDF_APP_PRIVATE_KEY`) are also repository-level but rotated
  **by hand**.
- **Environment secrets** (`prod` / `dev` / `github-pages`) — the remaining per-environment deploy credentials
  (`VERCEL_PROJECT_ID`, DB URLs, signing keys) that stay behind the approval gate; owner-managed (most via
  Terraform).

The rotation + kit workflows are migrating off the long-lived `CICD_PAT` to a **GitHub App** that mints
short-lived, scoped installation tokens per run (auto-revoked at job end). Phase 1 is wired behind the
`USE_GITHUB_APP` flag with a `CICD_PAT` fallback — see
[docs/design/github-app-migration.md](docs/design/github-app-migration.md) and
[docs/guides/MANUAL_SETUP.md](docs/guides/MANUAL_SETUP.md) Phase 6.7 to switch it on.

> **Scope:** this engine is **CI-plane only**. App-plane secrets owned by Terraform (DB URLs, the RS256
> keypair, `KDF_SERVICE_KEY`, `STRIPE_*`, OIDC client secrets, `CRON_SECRET`) are rotated via the
> terraform `SECRETS_ROTATION` runbook — the engine refuses `terraform_managed` entries.

**Full step-by-step instructions** (repo secrets, environment secrets, the issue form, the `gh` CLI,
adding a secret to the registry, verification & troubleshooting): **[docs/guides/SECRET_ROTATION.md](docs/guides/SECRET_ROTATION.md)**.

---

## Repo Structure

```
.github/
  workflows/             # reusable CD + CI workflows, scheduled rotation, ops issue handlers
  ISSUE_TEMPLATE/        # new-repo + owner ops forms (ops-rotate-secrets, ops-distribute-kit)
docs/
  guides/
    MANUAL_SETUP.md      # first-time setup: environments, secrets, PATs
    SECRET_ROTATION.md   # rotation runbook: repository + environment secrets
  reference/
    WORKFLOWS.md         # calling syntax + secrets reference per workflow
scripts/
  rotate_secret.py       # unified secret-rotation engine
  secret_registry.json   # which secrets live where (rotation source of truth)
Makefile
```

---

## Local Validation

Workflow files can be linted locally with [actionlint](https://github.com/rhysd/actionlint):

```bash
make lint
```

This runs actionlint against all workflow files in `.github/workflows/`. Fix any reported errors before pushing.

---

## Further Reading

- [docs/reference/WORKFLOWS.md](docs/reference/WORKFLOWS.md) — complete workflow reference, inputs, outputs, and secrets for each reusable workflow
- [docs/guides/MANUAL_SETUP.md](docs/guides/MANUAL_SETUP.md) — initial setup instructions for environments, secrets, and PAT configuration in a new consumer repo
- [docs/guides/SECRET_ROTATION.md](docs/guides/SECRET_ROTATION.md) — **rotation runbook**: how to rotate repository secrets and environment secrets (engine + by hand), emergency-leak triage, per-secret recipes, and the automated monitoring cadence
- [docs/design/github-app-migration.md](docs/design/github-app-migration.md) — move to a GitHub App (ephemeral tokens) to retire the long-lived PATs (**Phase 1 implemented**, behind the `USE_GITHUB_APP` flag)
