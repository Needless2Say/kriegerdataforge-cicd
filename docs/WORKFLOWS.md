# Workflow Catalog

This document describes every reusable workflow in `kriegerdataforge-cicd`, who calls it,
how to call it, and what environment secrets are required in the calling repo.

---

## Deployment Model — Overview

All deploys are **manual** (`workflow_dispatch` only). There are no automatic deploys on push.
Vercel's git auto-deploy is disabled in Terraform (`git_deployment = false`).

Deployment flow:
1. Developer triggers the CD workflow manually in GitHub Actions UI
2. GitHub pauses at the **Environment gate** — sends an approval notification
3. Required reviewer(s) approve or reject
4. On approval: environment secrets are loaded and the deploy runs
5. On rejection or timeout: workflow is cancelled, nothing deploys

**Approval model by environment:**

| GitHub Environment | Who can approve | Branch restriction |
|---|---|---|
| `development` | Owner + designated collaborators | `main` only |
| `production` | Owner only | `main` only |
| `infrastructure` | Owner only | `main` only |

**Key security property:** `VERCEL_TOKEN`, `DB_DATABASE_URL`, and all other deploy credentials
live only in GitHub Environment secrets. They are never exposed to collaborators, never
in `.env` files, and never visible in logs.

---

## Local Development

Local dev uses Docker — **no Vercel credentials needed**:

```bash
make docker-up     # starts all services locally
```

There is no path to deploy locally. The Vercel CLI cannot run without `VERCEL_TOKEN`, which
only exists inside GitHub Environments.

---

## Workflow 1: `cd-nextjs-vercel.yml`

**Purpose:** Deploy a Next.js app to a Vercel project.

**Called by:** `fitness-app-frontend`, `tiffanys-space`, `arthurs-portfolio`

**What it does:**
1. Activates the GitHub Environment gate (pauses for approval)
2. Checks out the repo
3. Sets up Node.js 22 with npm cache
4. Runs `npm ci`
5. Deploys to Vercel with `npx vercel --prod --yes`

**Caller pattern:**
```yaml
# .github/workflows/cd.yml in the consumer repo
on:
  workflow_dispatch:
    inputs:
      environment:
        description: 'Target environment'
        required: true
        type: choice
        options:
          - development
          - production

jobs:
  deploy:
    uses: Needless2Say/kriegerdataforge-cicd/.github/workflows/cd-nextjs-vercel.yml@main
    with:
      environment: ${{ inputs.environment }}
    secrets: inherit
```

**Required environment secrets (set per environment in the calling repo):**

| Secret | Description |
|---|---|
| `VERCEL_TOKEN` | Vercel API token |
| `VERCEL_ORG_ID` | Vercel team / org ID |
| `VERCEL_PROJECT_ID` | Vercel project ID — **different per environment** (dev vs prod project) |

---

## Workflow 2: `cd-python-vercel.yml`

**Purpose:** Deploy the FastAPI backend to Vercel (serverless) and optionally run Alembic migrations.

**Called by:** `kriegerdataforge`

**What it does:**
1. Activates the GitHub Environment gate
2. Checks out the repo
3. Sets up Python 3.12 with pip cache
4. Runs `pip install -r requirements.txt`
5. Sets up Node.js 22 (needed for the Vercel CLI)
6. Runs `python scripts/vercel_compactor.py` to compact the API for Vercel's file size limits
7. Deploys with `npx vercel --prod --yes`
8. If `run_migrations: true`, runs `alembic upgrade head` against the target database

**Caller pattern:**
```yaml
# .github/workflows/cd.yml in kriegerdataforge
on:
  workflow_dispatch:
    inputs:
      environment:
        description: 'Target environment'
        required: true
        type: choice
        options:
          - development
          - production
      run_migrations:
        description: 'Run Alembic migrations after deploy'
        required: false
        type: boolean
        default: true

jobs:
  deploy:
    uses: Needless2Say/kriegerdataforge-cicd/.github/workflows/cd-python-vercel.yml@main
    with:
      environment: ${{ inputs.environment }}
      run_migrations: ${{ inputs.run_migrations }}
    secrets: inherit
```

**Required environment secrets:**

| Secret | Description |
|---|---|
| `VERCEL_TOKEN` | Vercel API token |
| `VERCEL_ORG_ID` | Vercel team / org ID |
| `VERCEL_PROJECT_ID` | Vercel project ID — different per environment |
| `DB_DATABASE_URL` | SQLAlchemy-compatible Neon psycopg2 connection string |

**Inputs:**

| Input | Type | Default | Description |
|---|---|---|---|
| `environment` | string | required | `"development"` or `"production"` |
| `run_migrations` | boolean | `true` | Whether to run `alembic upgrade head` after deploy |

---

## Workflow 3: `cd-terraform.yml`

**Purpose:** Run `terraform plan` + `terraform apply` to update Vercel infrastructure.

**Called by:** `kriegerdataforge-terraform`

**What it does:**
1. Activates the `infrastructure` environment gate (owner-only approval)
2. Checks out the repo
3. Sets up Terraform `~1.9`
4. `terraform init` (with optional Terraform Cloud auth via `TF_TOKEN_app_terraform_io`)
5. `terraform validate`
6. `terraform plan -out=tfplan -detailed-exitcode`
   - Exit code 0 = no changes → skips apply, logs "No infrastructure changes"
   - Exit code 2 = changes detected → runs apply
7. `terraform apply tfplan` (only if changes detected)

All sensitive Terraform variables are injected as `TF_VAR_*` environment variables
sourced from the `infrastructure` GitHub Environment secrets.

**Caller pattern:**
```yaml
# .github/workflows/cd.yml in kriegerdataforge-terraform
on:
  workflow_dispatch:

jobs:
  apply:
    uses: Needless2Say/kriegerdataforge-cicd/.github/workflows/cd-terraform.yml@main
    with:
      environment: infrastructure
    secrets: inherit
```

**Required environment secrets (in the `infrastructure` environment of `kriegerdataforge-terraform`):**

| Secret | Maps to Terraform variable |
|---|---|
| `VERCEL_API_TOKEN` | `TF_VAR_vercel_api_token` |
| `BACKEND_AUTH_SECRET_KEY` | `TF_VAR_backend_auth_secret_key` |
| `BACKEND_AUTH_ADMIN_EMAIL` | `TF_VAR_backend_auth_admin_email` |
| `BACKEND_AUTH_ADMIN_EMAIL_PASSWORD` | `TF_VAR_backend_auth_admin_email_password` |
| `BACKEND_DB_DATABASE_URL` | `TF_VAR_backend_db_database_url` |
| `DEV_BACKEND_DB_DATABASE_URL` | `TF_VAR_dev_backend_db_database_url` |
| `FRONTEND_AUTH_SECRET_KEY` | `TF_VAR_frontend_auth_secret_key` |
| `TIFFANYS_SPACE_CRON_SECRET` | `TF_VAR_tiffanys_space_cron_secret` |
| `BACKEND_STRIPE_SECRET_KEY` | `TF_VAR_backend_stripe_secret_key` *(optional)* |
| `BACKEND_STRIPE_WEBHOOK_SECRET` | `TF_VAR_backend_stripe_webhook_secret` *(optional)* |
| `FITNESS_APP_SENTRY_AUTH_TOKEN` | `TF_VAR_fitness_app_sentry_auth_token` *(optional)* |
| `TIFFANYS_SPACE_SENTRY_AUTH_TOKEN` | `TF_VAR_tiffanys_space_sentry_auth_token` *(optional)* |
| `TF_TOKEN_APP_TERRAFORM_IO` | Terraform Cloud auth *(optional until remote state is configured)* |

**Required environment variables (non-secret):**

| Variable | Maps to Terraform variable |
|---|---|
| `VERCEL_TEAM_ID` | `TF_VAR_vercel_team_id` |
| `BACKEND_URL_PRODUCTION` | `TF_VAR_backend_url_production` |
| `BACKEND_URL_PREVIEW` | `TF_VAR_backend_url_preview` |
| `DEV_BACKEND_URL` | `TF_VAR_dev_backend_url` |

---

## Workflow 4: `issue-create-repo.yml`

**Purpose:** Automate new repository provisioning. When an issue is opened using the
`new-repo` issue template and the `new-repo` label is applied, this workflow:
1. Parses the issue form fields (repo name, type, visibility, description)
2. Validates inputs
3. Creates a new repo from the appropriate template repo
4. Configures `production` and `development` GitHub Environments with approval gates
5. Enables branch protection on `main` (require PR, dismiss stale reviews, no force push)
6. Posts a completion comment with the remaining manual checklist
7. Closes the issue

**Trigger:** `issues: labeled` — fires when the `new-repo` label is added to any issue.

**Template repos used (must exist):**

| Template repo | Used for |
|---|---|
| `Needless2Say/kriegerdataforge-template-nextjs` | `repo_type: nextjs` |
| `Needless2Say/kriegerdataforge-template-fastapi` | `repo_type: fastapi` |
| `Needless2Say/kriegerdataforge-template-npm-package` | `repo_type: npm-package` |
| `Needless2Say/kriegerdataforge-template-python-package` | `repo_type: python-package` |

**Required repo-level secret (NOT environment-scoped):**

| Secret | Description |
|---|---|
| `CICD_PAT` | Fine-grained GitHub PAT — see `docs/MANUAL_SETUP.md` Phase 6 for required permissions |

**Issue form fields:**

| Field | Values |
|---|---|
| Repository Name | kebab-case, lowercase letters/numbers/hyphens only |
| Repository Type | `nextjs` \| `fastapi` \| `npm-package` \| `python-package` |
| Visibility | `public` \| `private` |
| Description | Free text |

---

## Permissions Reference

### Workflow-level permissions

| Workflow | `contents` | `id-token` | `issues` |
|---|---|---|---|
| `cd-nextjs-vercel.yml` | `read` | `write` (OIDC) | — |
| `cd-python-vercel.yml` | `read` | `write` (OIDC) | — |
| `cd-terraform.yml` | `read` | — | — |
| `issue-create-repo.yml` | `read` | — | `write` |

### `CICD_PAT` required permissions

The fine-grained PAT used by `issue-create-repo.yml` requires:
- **Repository:** Administration (R/W), Contents (R/W), Environments (R/W),
  Secrets (R/W), Variables (R/W), Actions (R/W), Issues (R/W)
- **Account:** Members (Read)

---

## Consumer Repo Summary

| Consumer repo | Workflow called | Environments | Extra inputs |
|---|---|---|---|
| `fitness-app-frontend` | `cd-nextjs-vercel.yml` | `development`, `production` | — |
| `tiffanys-space` | `cd-nextjs-vercel.yml` | `development`, `production` | — |
| `arthurs-portfolio` | `cd-nextjs-vercel.yml` | `development`, `production` | — |
| `kriegerdataforge` | `cd-python-vercel.yml` | `development`, `production` | `run_migrations` |
| `kriegerdataforge-terraform` | `cd-terraform.yml` | `infrastructure` | — |

---

## How to Trigger a Deploy

1. Go to the consumer repo on GitHub
2. Click **Actions** → **CD** (or **CD — Terraform** for terraform)
3. Click **Run workflow** → select environment → click **Run workflow**
4. The workflow pauses with "Waiting for review" — you'll receive an email notification
5. Click the notification link → **Review deployments** → **Approve and deploy**
6. The workflow runs and deploys to the selected environment

For the backend (`kriegerdataforge`), there is an additional **Run migrations** checkbox.
Uncheck it only if you are deploying a non-schema-changing update and want to skip migration time.
