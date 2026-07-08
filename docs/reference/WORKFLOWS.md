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

**Key security property:** `VERCEL_DEPLOYMENT_TOKEN`, `DB_DATABASE_URL`, and all other deploy credentials
live only in GitHub Environment secrets. They are never exposed to collaborators, never
in `.env` files, and never visible in logs.

---

## Deployer Authorization Gate

GitHub cannot restrict **who** may trigger a `workflow_dispatch` — anyone with write access
to a repo can. The Environment approval gate covers *prod* (owner-only reviewer), but on
*dev* a collaborator is also an allowed reviewer and could self-approve. To enforce an
explicit per-repo allow-list of who may deploy, every CD workflow runs a **deployer
authorization gate** as its first job.

**How it works:**
1. Each reusable CD workflow (`cd-nextjs-vercel.yml`, `cd-python-vercel.yml`,
   `cd-terraform.yml`) starts with an `authorize` job that the `deploy`/`apply` job
   `needs:`. `arthurs-portfolio` (self-contained GitHub Pages deploy) has the same job,
   gating its `build`.
2. `authorize` checks out this repo (sparse — `scripts/` only) and runs
   [`scripts/check_deployer.py`](../../scripts/check_deployer.py).
3. The script looks up `github.triggering_actor` (the user who clicked **Run workflow**)
   against [`scripts/deployer_registry.json`](../../scripts/deployer_registry.json), keyed by
   `github.repository` and the target environment. Username matching is case-insensitive.
4. **Not authorized → the job fails → the deploy job never runs.** Because `authorize`
   has **no `environment:`**, it runs *before* the Environment approval is even requested —
   an unauthorized dispatch fails fast, with no approval notification and no secrets loaded.

**Decision (fail closed):** a repo not in the registry, an environment not listed for that
repo, or an actor not in the list → **denied**. When a new repo is provisioned, add it to
`deployer_registry.json` before its first deploy.

**Registry shape** (`scripts/deployer_registry.json`):
```json
{
  "deployers": {
    "Needless2Say/fitness-app-frontend": {
      "dev":  ["Needless2Say", "Ascensionn"],
      "prod": ["Needless2Say"]
    },
    "Needless2Say/arthurs-portfolio": {
      "github-pages": ["Needless2Say"]
    }
  }
}
```
Environment keys must match the value the caller passes to the reusable workflow's
`environment` input (`dev`/`prod` for Vercel + Terraform; `github-pages` for
`arthurs-portfolio`).

**Repo access for the gate:** the `authorize` job checks out `kriegerdataforge-cicd` with the
default `github.token`. Because this repo is **public**, that built-in token clones it — nothing
to configure. If `kriegerdataforge-cicd` is ever made private (after the org move), this checkout
would need a read-only token with access to it; that is tracked in the central roadmap
(`KDF docs/engineering/GITHUB_FUTURE_ENHANCEMENTS.md`).

**To change who can deploy:** edit `scripts/deployer_registry.json` and commit. No workflow
edits are needed — all consumers read the registry live from `main` at deploy time.

`check_deployer.py` is standard-library only and unit-tested in
`scripts/tests/test_check_deployer.py` (`pytest tests/test_check_deployer.py`).

---

## Local Development

Local dev uses Docker — **no Vercel credentials needed**:

```bash
make docker-up     # starts all services locally
```

There is no path to deploy locally. The Vercel CLI cannot run without `VERCEL_DEPLOYMENT_TOKEN`, which
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
| `VERCEL_DEPLOYMENT_TOKEN` | Shared Vercel deploy/management token |
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
| `VERCEL_DEPLOYMENT_TOKEN` | Shared Vercel deploy/management token |
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

**Layout:** The consumer is **directory-per-environment** — reusable modules under
`modules/`, one deployable root per environment under `environments/<env>/`, and **no
Terraform workspaces**. The workflow runs every command with
`-chdir=environments/<environment>`.

**What it does:**
1. Activates the `${{ inputs.environment }}` (dev or prod) environment gate (owner-only approval)
2. Checks out the consumer repo at the requested version tag
3. Sets up Terraform `~1.9`
4. `terraform -chdir=environments/<env> init` (remote backend auth via `TF_TOKEN_app_terraform_io`)
5. `terraform -chdir=environments/<env> validate`
6. `terraform -chdir=environments/<env> plan -out=tfplan -detailed-exitcode`
   - Exit code 0 = no changes → skips apply, logs "No infrastructure changes"
   - Exit code 2 = changes detected → runs apply
7. `terraform -chdir=environments/<env> apply tfplan` (only if changes detected)

The env root auto-loads its committed, non-secret `common.auto.tfvars`. All per-environment
secret and non-secret values are injected as `TF_VAR_*` environment variables from the
matching GitHub Environment (no `-var-file` is used). `vercel_team_id`, JWT issuer/audience,
TTLs, feature-flag defaults, and the error-tracking service DSNs come from `common.auto.tfvars` and are **not** injected.

> **State:** `terraform init` in CI has no local state, so a remote backend (Terraform
> Cloud / S3) must be configured in `environments/<env>/providers.tf` before running this
> against live projects.

**Caller pattern:**
```yaml
# .github/workflows/cd.yml in kriegerdataforge-terraform
on:
  workflow_dispatch:
    inputs:
      environment: { type: choice, options: [dev, prod] }
      version: { type: string }

jobs:
  apply:
    uses: Needless2Say/kriegerdataforge-cicd/.github/workflows/cd-terraform.yml@main
    with:
      environment: ${{ inputs.environment }}
      version: ${{ inputs.version }}
    secrets: inherit
```

**Required environment secrets (per `dev` / `prod` GitHub Environment):**

| Secret | Maps to Terraform variable |
|---|---|
| `VERCEL_DEPLOYMENT_TOKEN` | `TF_VAR_vercel_api_token` |
| `BACKEND_AUTH_PRIVATE_KEY` | `TF_VAR_backend_auth_private_key` (RSA PEM, PKCS#8) |
| `BACKEND_AUTH_PUBLIC_KEY` | `TF_VAR_backend_auth_public_key` |
| `FRONTEND_AUTH_PUBLIC_KEY` | `TF_VAR_frontend_auth_public_key` (== `BACKEND_AUTH_PUBLIC_KEY`) |
| `BACKEND_AUTH_ADMIN_EMAIL` | `TF_VAR_backend_auth_admin_email` |
| `BACKEND_AUTH_ADMIN_EMAIL_PASSWORD` | `TF_VAR_backend_auth_admin_email_password` |
| `KDF_AUTH_DB_DATABASE_URL` | `TF_VAR_kdf_auth_db_database_url` |
| `FITNESS_APP_BACKEND_DB_DATABASE_URL` | `TF_VAR_fitness_app_backend_db_database_url` |
| `TIFFANYS_SPACE_BACKEND_DB_DATABASE_URL` | `TF_VAR_tiffanys_space_backend_db_database_url` |
| `FITNESS_APP_SERVICE_KEY` | `TF_VAR_fitness_app_service_key` |
| `TIFFANYS_SPACE_SERVICE_KEY` | `TF_VAR_tiffanys_space_service_key` |
| `TIFFANYS_SPACE_CRON_SECRET` | `TF_VAR_tiffanys_space_cron_secret` *(optional)* |
| `BACKEND_STRIPE_SECRET_KEY` | `TF_VAR_backend_stripe_secret_key` *(optional)* |
| `BACKEND_STRIPE_WEBHOOK_SECRET` | `TF_VAR_backend_stripe_webhook_secret` *(optional)* |
| `TF_TOKEN_APP_TERRAFORM_IO` | Terraform Cloud auth *(once remote state is configured)* |

**Required environment variables (non-secret, per `dev` / `prod`):**

| Variable | Maps to Terraform variable |
|---|---|
| `BACKEND_URL` | `TF_VAR_backend_url` (KDF auth service URL) |
| `FITNESS_APP_BACKEND_URL` | `TF_VAR_fitness_app_backend_url` (fitness app's own backend) |
| `TIFFANYS_SPACE_BACKEND_URL` | `TF_VAR_tiffanys_space_backend_url` (tiffany's own backend) |
| `KDF_AUTH_SERVICE_PROJECT_NAME` | `TF_VAR_kdf_auth_service_project_name` |
| `FITNESS_APP_PROJECT_NAME` | `TF_VAR_fitness_app_project_name` |
| `FITNESS_APP_BACKEND_PROJECT_NAME` | `TF_VAR_fitness_app_backend_project_name` |
| `TIFFANYS_SPACE_PROJECT_NAME` | `TF_VAR_tiffanys_space_project_name` |
| `TIFFANYS_SPACE_BACKEND_PROJECT_NAME` | `TF_VAR_tiffanys_space_backend_project_name` |
| `KDF_AUTH_CORS_ORIGINS` | `TF_VAR_kdf_auth_cors_origins` *(optional)* |
| `FITNESS_APP_BACKEND_CORS_ORIGINS` | `TF_VAR_fitness_app_backend_cors_origins` *(optional)* |
| `TIFFANYS_SPACE_BACKEND_CORS_ORIGINS` | `TF_VAR_tiffanys_space_backend_cors_origins` *(optional)* |

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

## Workflow 5: `ci-python-security.yml`

**Purpose:** Reusable Python security scanning — runs two jobs:
- **bandit** (SAST) over the configured source paths.
- **pip-audit** (SCA) against `requirements.txt` for known CVEs.

**Trigger:** `workflow_call` only. Consumers call it from their own `ci.yml`
(PR-time) and/or `security.yml` (push + weekly schedule).

**Inputs:**

| Input | Type | Default | Description |
|---|---|---|---|
| `python_version` | string | `3.13` | Python version for both jobs |
| `bandit_paths` | string | `api/ scripts/ vercel_api/` | Space-separated paths passed to `bandit -r` |
| `needs_sdk_auth` | boolean | `false` | Configure git credentials for the private SDK so pip-audit can resolve it (requires `GH_PACKAGES_PAT`) |

**Secrets:** pass `secrets: inherit` when `needs_sdk_auth: true` (for `GH_PACKAGES_PAT`).

**Consumers:** `kriegerdataforge` (`bandit_paths: api/ scripts/ vercel_api/ generate_openapi.py`, `needs_sdk_auth: true`), `kriegerdataforge-sdk` (`bandit_paths: src/`).

---

## Workflow 6: `ci-codeql.yml`

**Purpose:** Reusable CodeQL static analysis (SAST). Initializes CodeQL, autobuilds,
analyzes, and uploads results to the consumer repo's **Security ▸ Code scanning** tab.

> ⚠️ **Entitlement:** CodeQL code scanning runs only on **public** repos (free) or
> **private** repos with **GitHub Code Security** (formerly GitHub Advanced
> Security — an Enterprise add-on). GitHub Pro / Copilot do **not** include it.
> Because most KDF repos are private, consumers **gate** the calling job behind the
> `ENABLE_CODEQL` repo/org Actions *variable*, so it stays skipped (green) until the
> entitlement exists. Set `ENABLE_CODEQL=true` to turn it on — no workflow change.

**Trigger:** `workflow_call` only. Consumers call it from `codeql.yml` on
push/PR to `main` + a weekly schedule, with the job gated on `vars.ENABLE_CODEQL`.

**Inputs:**

| Input | Type | Default | Description |
|---|---|---|---|
| `language` | string | `python` | CodeQL language (e.g. `python`, `javascript-typescript`) |
| `config_file` | string | `""` | Path to a CodeQL config file in the consumer repo (optional) |
| `queries` | string | `security-extended,security-and-quality` | Query suites to run |

**Permissions:** the reusable job requests `security-events: write` (+ `actions:read`,
`contents:read`); the consumer caller must grant the same.

**Consumer caller pattern:**

```yaml
# .github/workflows/codeql.yml in the consumer repo
jobs:
  codeql:
    if: ${{ vars.ENABLE_CODEQL == 'true' }}
    permissions:
      actions: read
      contents: read
      security-events: write
    uses: Needless2Say/kriegerdataforge-cicd/.github/workflows/ci-codeql.yml@main
    with:
      language: python
      config_file: ./.github/codeql/codeql-config.yml
```

**Consumers:** `kriegerdataforge`, `kriegerdataforge-sdk`.

---

## Workflow 7: `ci-python-integration.yml`

**Purpose:** Reusable **integration-test lane** for KDF Python backends. Unlike
`ci-python-tests.yml` (the fast, DB-free *unit* lane), this workflow provisions an
ephemeral **Postgres** service, migrates it to head, optionally seeds app-specific
fixtures, then runs the caller's DB-backed suite. It exists because a backend's
`-m requires_postgres` tests silently green-skip when no `KDF_TEST_DATABASE_URL` is set —
so the integration guarantees never actually run (finding **PL-166**).

**Trigger:** `workflow_call` only. Callers opt in with a **separate** job so the fast
unit lane stays DB-free.

**How it works:**
1. Spins up a `postgres:16` service (`kdf` / `kdf` / `kdf_test`, health-checked).
2. The same connection string is exported under **two** names so both the SDK/alembic
   (`DB_DATABASE_URL`, `env_prefix=DB_`) and the pytest conftest gate
   (`KDF_TEST_DATABASE_URL`) point at the one ephemeral DB.
3. Installs deps → migrates to head → (optional) runs `seed_command` → runs `test_command`.

This file is **public**, so it stays schema-free: anything app-specific (e.g. an
auth-owned `kdfusers` table) is provisioned by the caller via `seed_command`, whose
SQL/script lives in the caller's **private** repo and is present at runtime because
`checkout` pulls the caller repo.

**Inputs:**

| Input | Type | Default | Description |
|---|---|---|---|
| `python_version` | string | `3.14` | Python version for the job |
| `install_command` | string | `pip install -r requirements.txt` | Dependency install command |
| `migrate_command` | string | `alembic upgrade head` | Migrates the ephemeral DB to head |
| `seed_command` | string | `""` | Optional app-specific seed run after migrate (empty string skips) |
| `test_command` | string | `python -m pytest -m requires_postgres -q --tb=short` | Full pytest command for the integration suite |
| `needs_sdk_auth` | boolean | `false` | Configure git creds for the private SDK (requires `GH_PACKAGES_PAT`) |

**Secrets:** pass `secrets: inherit` when `needs_sdk_auth: true` (for `GH_PACKAGES_PAT`).

**Consumer caller pattern:**

```yaml
# .github/workflows/ci.yml in the consumer repo — a job separate from the unit lane
jobs:
  integration:
    uses: Needless2Say/kriegerdataforge-cicd/.github/workflows/ci-python-integration.yml@main
    with:
      needs_sdk_auth: true
      seed_command: psql "$KDF_TEST_DATABASE_URL" -f tests/sql/seed_kdfusers.sql
    secrets: inherit
```

---

## End-to-end (E2E) engine

cicd also hosts the ecosystem's **reusable E2E engine** — the data-driven `e2e/ci_stack.py`
driver, the shared identity compose, the Playwright suite, and a composite action that ties
them together. It is **tenant-agnostic**: each tenant repo owns its own journey (an
`e2e/manifest.json` + Playwright spec, in *that* repo) and ships a thin `.github/workflows/e2e.yml`
caller — cicd holds no per-tenant content (ADR **D-006** / **D-007**;
[`docs/design/e2e-test-decoupling.md`](../design/e2e-test-decoupling.md)).

### `.github/actions/run-e2e` (composite action)

The reusable engine, `uses:`-d by each tenant's `e2e.yml`. The calling job checks **itself**
out into a path named after its repo (sibling layout); the action then reads that repo's
`e2e/manifest.json` to learn which **other** repos the journey needs (so it never hardcodes a
tenant list), mints a scoped GitHub App token (`contents:read` on just those repos + the SDK),
checks out cicd + the sibling repos, and runs
`python e2e/ci_stack.py up --journey <journey>` → `npm test` (Playwright) → `down`. The App
token also serves as the `GH_PACKAGES_PAT` git credential for the private-SDK clone during the
image build.

**Inputs:**

| Input | Required | Default | Description |
|---|---|---|---|
| `journey` | yes | — | Journey to run; must match the caller's `e2e/manifest.json` `journey` |
| `app-id` | yes | — | GitHub App ID — pass `${{ secrets.KDF_APP_ID }}` (composite actions can't read secrets) |
| `app-private-key` | yes | — | GitHub App private key — pass `${{ secrets.KDF_APP_PRIVATE_KEY }}` |
| `cicd-ref` | no | `main` | Ref of `kriegerdataforge-cicd` to run the engine from |

### `ops-setup-e2e.yml` (secret-distribution workflow)

Issue-triggered provisioner that arms a target E2E-journey repo to run its (dormant) `e2e.yml`.
Fires **only** when the owner-applied `ops:setup-e2e` label is added, is owner-gated via the
reusable fail-closed authorize gate, and validates the target against a fixed allow-list of the
six E2E-journey repos. It writes, to the target repo: variable `RUN_E2E_GATE=false` (the dormant
on/off switch), variable `USE_GITHUB_APP=true`, and copies of the `KDF_APP_ID` + `KDF_APP_PRIVATE_KEY`
secrets (which the `e2e.yml` job passes to the `run-e2e` action). Secret *values* never touch the
issue/comment. (Post-org-move, `KDF_APP_*` become org secrets and the per-repo copy is retired.)

### Caller run modes

A tenant's `.github/workflows/e2e.yml` runs its journey in one of three modes, each gated by a
repo Actions **variable** so the engine stays dormant until the owner flips it on:

- **CI gate** (`RUN_E2E_GATE=true`) — on every PR, as a hard merge gate;
- **CD / nightly** (`RUN_E2E_CD=true`) — on push-to-`main` + a weekly schedule, for teams that
  **don't** want E2E on every PR (avoids the cross-repo-lockstep cost);
- **On demand** — a manual `workflow_dispatch` (always available).

See [`docs/guides/E2E_TESTING.md`](../guides/E2E_TESTING.md) for the full model and
[`e2e/README.md`](../../e2e/README.md) for the engine internals + local run.

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

The fine-grained PAT used by `issue-create-repo.yml` (and the rotation/kit engine) requires, over
**All repositories (incl. future)**:
- **Repository:** Administration (R/W), Contents (R/W), Environments (R/W),
  Secrets (R/W), Variables (R/W), Actions (R/W), Issues (R/W), Pull requests (R/W)
- **Metadata:** Read

It is a manual/hand-rotated PAT on a tracked **30-day expiry** (next: `2026-07-30`).

---

## Consumer Repo Summary

Every repo below runs the [Deployer Authorization Gate](#deployer-authorization-gate) and
must have a matching entry in `scripts/deployer_registry.json`.

| Consumer repo | Workflow called | Environments | Extra inputs |
|---|---|---|---|
| `fitness-app-frontend` | `cd-nextjs-vercel.yml` | `dev`, `prod` | — |
| `tiffanys-space` | `cd-nextjs-vercel.yml` | `dev`, `prod` | — |
| `fitness-app-backend` | `cd-python-vercel.yml` | `dev`, `prod` | `run_migrations` |
| `tiffanys-space-backend` | `cd-python-vercel.yml` | `dev`, `prod` | `run_migrations` |
| `kriegerdataforge` | `cd-python-vercel.yml` | `dev`, `prod` | `run_migrations` |
| `kriegerdataforge-terraform` | `cd-terraform.yml` | `dev`, `prod` | `version` |
| `arthurs-portfolio` | self-contained (`nextjs.yml` → GitHub Pages) | `github-pages` | `version` |

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
