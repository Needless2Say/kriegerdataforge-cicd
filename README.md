# kriegerdataforge-cicd

Centralized shared GitHub Actions workflow library for the KriegerDataForge ecosystem. Consumer repos call these reusable workflows instead of maintaining their own deploy pipelines.

This repository is **public** on GitHub. All other KriegerDataForge repos are private.

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

Three environments are used across all repos. Names are fixed — do not use aliases.

| Environment | Approvers | Used for |
|---|---|---|
| `dev` | Owner + collaborators | Development deployments |
| `prod` | Owner only | Production deployments |
| `infra` | Owner only | Terraform infrastructure changes |

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

## Security

All **deployment/runtime** credentials are stored as GitHub **Environment** secrets — there are no `.env` files, no hardcoded values, and no repository-level deployment secrets. The environment gate is the enforcement point: secrets only become available after an approved reviewer allows the deployment to proceed. The only **repository-level** secrets are the ops/control-plane credentials this repo uses to *manage* the others (`CICD_PAT`, `VERCEL_MASTER_TOKEN`, and staging slots) — see Secret Rotation below.

---

## Secret Rotation

GitHub secrets come in two scopes and rotate differently:

- **Environment secrets** (`prod` / `dev` / `infra`) — all deploy/runtime credentials. The ones in
  [`scripts/secret_registry.json`](scripts/secret_registry.json) (`VERCEL_DEPLOYMENT_TOKEN`, `GH_PACKAGES_PAT`) are
  rotated by the **engine** ([`scripts/rotate_secret.py`](scripts/rotate_secret.py)) in two modes —
  `generate` (auto-mint) or `paste` (distribute an owner-staged value) — selectable per environment.
  Drive it from the **`Ops · Rotate a secret`** issue form (add the `ops:rotate-secrets` label) or the CLI.
- **Repository secrets** — the cicd ops/control plane (`CICD_PAT`, `VERCEL_MASTER_TOKEN`, …). Rotated
  **by hand**, since they authenticate the engine itself.

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
