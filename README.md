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

All credentials are stored as GitHub Environment secrets. There are no `.env` files, no hardcoded values, and no repository-level secrets for deployment credentials. The environment gate is the enforcement point — secrets only become available after an approved reviewer allows the deployment to proceed.

---

## Repo Structure

```
.github/
  workflows/
    cd-nextjs-vercel.yml
    cd-python-vercel.yml
    cd-terraform.yml
    create-github-release.yml
    bump-version-check.yml
    issue-create-repo.yml
    rotate-vercel-tokens.yml
docs/
  WORKFLOWS.md       # Full calling syntax and secrets reference for each workflow
  MANUAL_SETUP.md    # Setup guide: environments, secrets, PAT configuration
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

- [docs/WORKFLOWS.md](docs/reference/WORKFLOWS.md) — complete workflow reference, inputs, outputs, and secrets for each reusable workflow
- [docs/MANUAL_SETUP.md](docs/guides/MANUAL_SETUP.md) — initial setup instructions for environments, secrets, and PAT configuration in a new consumer repo
