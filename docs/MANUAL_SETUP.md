# Manual Setup Guide

This document covers every step that cannot be automated by code. Complete these in order. Steps marked **ONCE** only need to be done once total; steps marked **PER REPO** need to be repeated for each listed repository.

---

## Phase 0 — Prerequisites

Before starting, make sure you have:

- [X] Vercel CLI installed locally (`npm i -g vercel`) and logged in
- [X] Terraform 1.9+ installed locally
- [X] `gh` CLI installed and authenticated (`gh auth login`)
- [X] Your Vercel API token handy (Vercel Dashboard → Settings → Tokens → Create)
- [X] Your Vercel Team ID handy (Vercel Dashboard → Settings → General → scroll to "Team ID")

---

## Phase 1 — Apply Terraform Changes (Disable Auto-Deploys + Create Dev Projects)

> **ONCE** — Run locally before anything else. This disables auto-deploys on the existing frontend projects and provisions the two new dev Vercel projects.

### 1.1 — Provision the Neon Dev Database

Before running Terraform, you need the dev database connection string.

1. Go to [console.neon.tech](https://console.neon.tech)
2. Open your existing KriegerDataForge Neon project
3. Click **Branches** → **New Branch**
   - Branch name: `dev`
   - Branch from: `main` (this copies the live schema without copying data)
4. After the branch is created, click the branch name → **Connection Details**
5. Select **psycopg2** from the connection format dropdown
6. Copy the full connection string. It looks like:

   ```bash
   postgresql+psycopg2://user:password@ep-xxxx.region.aws.neon.tech/dbname?sslmode=require
   ```

7. Save it — this is your `dev_backend_db_database_url`

### 1.2 — Add Dev Variables to terraform.tfvars

Open `kriegerdataforge-terraform/terraform.tfvars` and add the following block at the bottom:

```hcl
# ── Development environment ─────────────────────────────────────────────────
dev_backend_db_database_url = "postgresql+psycopg2://user:pass@ep-xxxx.region.aws.neon.tech/dbname?sslmode=require"
dev_backend_url             = "https://placeholder-update-after-first-deploy.vercel.app"
dev_backend_cors_origins    = "http://localhost:3000,http://localhost:3001"
```

Replace the `dev_backend_db_database_url` value with the connection string from step 1.1.

> **Note:** `dev_backend_url` is a placeholder for now. After the first dev backend deploy completes (Phase 5), come back and update it with the actual Vercel URL (e.g. `https://kriegerdataforge-dev.vercel.app`), then re-run `terraform apply`.

### 1.3 — Run Terraform Apply

```bash
cd kriegerdataforge-terraform
terraform init
terraform plan   # review the changes — should show 2 new projects + auto-deploy disabled on 2 existing ones
terraform apply
```

After apply completes, note the new project IDs printed in the outputs:

```bash
kriegerdataforge_dev_project_id   = "prj_..."
fitness_app_dev_project_id        = "prj_..."
```

Save these — you'll need them in Phase 3.

---

## Phase 2 — Set Up Terraform Cloud Remote State (Recommended)

> **ONCE** — Without this, the Terraform CD workflow has no state file to work with. Free tier is sufficient.

1. Go to [app.terraform.io](https://app.terraform.io) → Create account (or sign in)
2. Create an organization (e.g. `kriegerdataforge`)
3. Create a workspace:
   - Name: `kriegerdataforge-infrastructure`
   - Execution mode: **CLI-driven** (NOT VCS-driven)
4. Open `kriegerdataforge-terraform/providers.tf` and uncomment the `backend "remote"` block (Option A):

   ```hcl
   backend "remote" {
     hostname     = "app.terraform.io"
     organization = "kriegerdataforge"   # your org name
     workspaces {
       name = "kriegerdataforge-infrastructure"
     }
   }
   ```

5. Create a Terraform Cloud API token:
   - In Terraform Cloud: User icon → User Settings → Tokens → Create an API token
   - Name: `github-actions-cd`
   - Copy the token value
6. Migrate local state to Terraform Cloud:

   ```bash
   cd kriegerdataforge-terraform
   terraform login   # paste the token when prompted
   terraform init -migrate-state  # confirm "yes" when asked to copy state
   ```

7. Verify the state was migrated: go to Terraform Cloud → your workspace → States — you should see a state version.

---

## Phase 3 — GitHub Environments (PER REPO × 7)

> **MANUAL** — GitHub doesn't expose environment creation with required reviewers via the standard Actions API without a PAT. Repeat for each repo listed.

Repos to configure:

1. `kriegerdataforge`
2. `fitness-app-frontend`
3. `tiffanys_space`
4. `arthurs-portfolio`
5. `kriegerdataforge-cicd`
6. `kriegerdataforge-terraform`

For each repo, go to **Settings → Environments** and create the environments below.

### For repos 1–5 (app repos): Create TWO environments

**Environment: `production`**

1. Click **New environment** → name: `production` → **Configure environment**
2. Check **Required reviewers** → Add yourself (the account owner)
3. Under **Deployment branches and tags** → select **Selected branches and tags** → Add rule → Branch name pattern: `main`
4. Click **Save protection rules**

**Environment: `development`**

1. Click **New environment** → name: `development` → **Configure environment**
2. Check **Required reviewers** → Add yourself
   - After your friend accepts the collaborator invite (Phase 7), come back and add them here too
3. Under **Deployment branches and tags** → **Selected branches and tags** → Add rule → Branch name: `main`
4. Click **Save protection rules**

### For repo 6 (kriegerdataforge-terraform): Create ONE environment

**Environment: `infrastructure`**

1. Click **New environment** → name: `infrastructure` → **Configure environment**
2. Required reviewers: yourself only
3. Deployment branches: `main` only
4. Click **Save protection rules**

### For arthurs-portfolio: update the existing `github-pages` environment

1. Go to `arthurs-portfolio` → Settings → Environments → `github-pages` (already exists)
2. Check **Required reviewers** → Add yourself
3. Click **Save protection rules**

---

## Phase 4 — Environment Secrets (PER REPO)

> **MANUAL** — Secrets live in GitHub Environments, never in the repo. Add them via Settings → Environments → [environment name] → Add secret.

### kriegerdataforge

**`production` environment secrets:**
| Secret Name | Value |
|---|---|
| `VERCEL_TOKEN` | Your Vercel API token |
| `VERCEL_ORG_ID` | Your Vercel Team ID |
| `VERCEL_PROJECT_ID` | `prj_3kiJpapxo5G4Syd4j6i6LkeWXS9s` (prod backend) |
| `DB_DATABASE_URL` | Your production Neon psycopg2 connection string |

**`development` environment secrets:**
| Secret Name | Value |
|---|---|
| `VERCEL_TOKEN` | Your Vercel API token |
| `VERCEL_ORG_ID` | Your Vercel Team ID |
| `VERCEL_PROJECT_ID` | The `kriegerdataforge_dev_project_id` from Phase 1.3 output |
| `DB_DATABASE_URL` | The dev Neon branch connection string from Phase 1.1 |

### fitness-app-frontend

**`production` environment secrets:**
| Secret Name | Value |
|---|---|
| `VERCEL_TOKEN` | Your Vercel API token |
| `VERCEL_ORG_ID` | Your Vercel Team ID |
| `VERCEL_PROJECT_ID` | `prj_cqvUqHUTI2peopP8ZQalqPE3um7u` (prod fitness app) |

**`development` environment secrets:**
| Secret Name | Value |
|---|---|
| `VERCEL_TOKEN` | Your Vercel API token |
| `VERCEL_ORG_ID` | Your Vercel Team ID |
| `VERCEL_PROJECT_ID` | The `fitness_app_dev_project_id` from Phase 1.3 output |

### tiffanys_space

**`production` environment secrets:**
| Secret Name | Value |
|---|---|
| `VERCEL_TOKEN` | Your Vercel API token |
| `VERCEL_ORG_ID` | Your Vercel Team ID |
| `VERCEL_PROJECT_ID` | `prj_Vwlw8Nts7rFo2Apq25ZhXN3K6fw9` (prod tiffanys) |

**`development` environment secrets:**
| Secret Name | Value |
|---|---|
| `VERCEL_TOKEN` | Your Vercel API token |
| `VERCEL_ORG_ID` | Your Vercel Team ID |
| `VERCEL_PROJECT_ID` | *(No dev project for tiffanys yet — skip until one is created in Terraform)* |

### kriegerdataforge-terraform (`infrastructure` environment)

**Secrets:**
| Secret Name | Value |
|---|---|
| `VERCEL_API_TOKEN` | Your Vercel API token |
| `BACKEND_AUTH_SECRET_KEY` | Value from `terraform.tfvars` → `backend_auth_secret_key` |
| `BACKEND_AUTH_ADMIN_EMAIL` | Value from `terraform.tfvars` → `backend_auth_admin_email` |
| `BACKEND_AUTH_ADMIN_EMAIL_PASSWORD` | Value from `terraform.tfvars` → `backend_auth_admin_email_password` |
| `BACKEND_DB_DATABASE_URL` | Production Neon psycopg2 connection string |
| `DEV_BACKEND_DB_DATABASE_URL` | Dev Neon branch connection string |
| `FRONTEND_AUTH_SECRET_KEY` | Value from `terraform.tfvars` → `frontend_auth_secret_key` |
| `TIFFANYS_SPACE_CRON_SECRET` | Value from `terraform.tfvars` → `tiffanys_space_cron_secret` |
| `BACKEND_STRIPE_SECRET_KEY` | Value from `terraform.tfvars` (or leave empty if not set) |
| `BACKEND_STRIPE_WEBHOOK_SECRET` | Value from `terraform.tfvars` (or leave empty if not set) |
| `FITNESS_APP_SENTRY_AUTH_TOKEN` | Value from `terraform.tfvars` (or leave empty) |
| `TIFFANYS_SPACE_SENTRY_AUTH_TOKEN` | Value from `terraform.tfvars` (or leave empty) |
| `TF_TOKEN_APP_TERRAFORM_IO` | Terraform Cloud API token (from Phase 2 step 5) |

**Variables** (non-secret — use "Add variable" not "Add secret"):
| Variable Name | Value |
|---|---|
| `VERCEL_TEAM_ID` | Your Vercel Team ID |
| `BACKEND_URL_PRODUCTION` | Your production backend URL (e.g. `https://kriegerdataforge.vercel.app`) |
| `BACKEND_URL_PREVIEW` | Your preview backend URL (same as prod if no dedicated preview) |
| `DEV_BACKEND_URL` | The dev backend Vercel URL (set after first dev deploy in Phase 5) |

> **How to find your production backend URL:** Go to Vercel Dashboard → `kriegerdataforge` project → Domains. It will be something like `https://kriegerdataforge.vercel.app` or your custom domain.

### kriegerdataforge-cicd (repo-level secret, NOT environment-scoped)

1. Go to **Settings → Secrets and variables → Actions → New repository secret**
2. Name: `CICD_PAT` — Value: the fine-grained PAT you create in Phase 6

---

## Phase 5 — First Dev Deploys (Verify the New Projects Work)

> **ONCE** — Deploy to dev for the first time to get the actual Vercel URLs.

### 5.1 — Deploy dev backend

1. Go to `kriegerdataforge` repo → **Actions** → **CD** workflow
2. Click **Run workflow** → Environment: `development`, Run migrations: ✅ → **Run workflow**
3. Wait for approval notification (you'll get one since you're the reviewer)
4. Click **Review deployments** → **Approve**
5. Wait for the deploy to complete → note the Vercel deployment URL from the logs

### 5.2 — Update dev URLs in Terraform + GitHub Variables

1. Open `kriegerdataforge-terraform/terraform.tfvars` and update:

   ```hcl
   dev_backend_url          = "https://kriegerdataforge-dev.vercel.app"
   dev_backend_cors_origins = "http://localhost:3000,http://localhost:3001,https://fitness-app-frontend-dev.vercel.app"
   ```

2. Update the `DEV_BACKEND_URL` GitHub variable in `kriegerdataforge-terraform` → `infrastructure` environment (Phase 4)
3. Run `terraform apply` locally (or trigger the Terraform CD workflow)

### 5.3 — Deploy dev frontend

1. Go to `fitness-app-frontend` → **Actions** → **CD** → Run workflow → `development` → approve → wait

---

## Phase 6 — Fine-Grained PAT for Issue Assistant

> **ONCE** — Creates the token the issue assistant uses to provision new repos.

1. Go to GitHub → Profile picture → **Settings → Developer settings → Personal access tokens → Fine-grained tokens**
2. Click **Generate new token**
3. Configure:
   - **Token name:** `CICD_REPO_ASSISTANT`
   - **Expiration:** 1 year (set a calendar reminder to rotate it)
   - **Resource owner:** `Needless2Say`
   - **Repository access:** All repositories
4. **Repository permissions:**
   | Permission | Access |
   |---|---|
   | Actions | Read and write |
   | Administration | Read and write |
   | Contents | Read and write |
   | Environments | Read and write |
   | Issues | Read and write |
   | Secrets | Read and write |
   | Variables | Read and write |
5. **Account permissions:** Members → Read-only
6. Click **Generate token** → copy the token immediately (shown only once)
7. Add it as a repo-level secret in `kriegerdataforge-cicd`:
   - Settings → Secrets and variables → Actions → New repository secret
   - Name: `CICD_PAT`, Value: paste the token

---

## Phase 7 — Branch Protection (PER REPO × 7)

> **MANUAL** — Enable on `main` for every repo.

For each repo in the list, go to **Settings → Branches → Add branch protection rule**:

**Branch name pattern:** `main`

Checkboxes to enable:

- [x] **Require a pull request before merging**
  - Required number of approvals: `1`
  - [x] Dismiss stale pull request approvals when new commits are pushed
- [x] **Require status checks to pass before merging**
  - Click "Search for status checks" after the first CI run completes — add all job names (e.g. `lint`, `type-check`, `unit-tests`, `build`)
- [x] **Do not allow bypassing the above settings**
- [x] **Restrict who can push to matching branches** → leave empty (no direct pushes from anyone)

> **Note:** The status check names won't appear until the first CI run has completed on a PR. Set up the rule without status checks first, then edit it and add them after.

---

## Phase 8 — Remove Old Repo-Level Deployment Secrets

> **ONCE** — After environment secrets are set in Phase 4, remove any repo-level deployment secrets to avoid confusion.

For `kriegerdataforge`, `fitness-app-frontend`, `tiffanys_space`:

1. Go to **Settings → Secrets and variables → Actions**
2. Delete any of these if they exist at the repo level (not environment level):
   - `VERCEL_TOKEN`
   - `VERCEL_PROJECT_ID`
   - `VERCEL_ORG_ID`

---

## Phase 9 — Create Template Repositories

> **MANUAL** — Create 4 empty GitHub repos and mark them as templates.

For each of the 4 template repos:

1. Go to [github.com/new](https://github.com/new)
2. Repository name: (see table below)
3. Visibility: **Private**
4. Initialize with a README: ✅
5. Click **Create repository**
6. After creation: **Settings** → scroll to **Template repository** → check it → **Save**

| Repo Name | Purpose |
|---|---|
| `kriegerdataforge-template-nextjs` | Starting point for new Next.js apps |
| `kriegerdataforge-template-fastapi` | Starting point for new FastAPI backends |
| `kriegerdataforge-template-npm-package` | Starting point for new npm packages |
| `kriegerdataforge-template-python-package` | Starting point for new Python packages |

After creating each template repo, add the baseline files (CI workflow, Makefile, AGENTS.md, Dockerfile stub, etc.). The issue assistant workflow will fail gracefully until these templates exist and have content.

> **Suggested template content:** Copy the relevant files from an existing repo (e.g., copy `fitness-app-frontend/.github/workflows/ci.yml`, `Makefile`, `AGENTS.md`, `Dockerfile` into `kriegerdataforge-template-nextjs`) and strip out app-specific content. The template should represent the skeleton a new project starts from.

---

## Phase 10 — Friend Onboarding

> **MANUAL** — After your friend accepts GitHub invite.

### 10.1 — Add collaborator to all repos

For each of the 7 repos, go to **Settings → Collaborators and teams → Add people**:

- Add friend's GitHub username with **Write** role

### 10.2 — Add friend as development environment reviewer

After friend accepts the collaborator invite, for each of these repos:
`kriegerdataforge`, `fitness-app-frontend`, `tiffanys_space`, `arthurs-portfolio`, `kriegerdataforge-cicd`

1. Go to **Settings → Environments → development → Required reviewers**
2. Add friend's GitHub username
3. Click **Save protection rules**

### 10.3 — Send onboarding resources

Share these docs with your friend:

- `kriegerdataforge/docs/SETUP_AND_ONBOARDING.md` — backend local dev setup
- `fitness-app-frontend/docs/SETUP_AND_ONBOARDING.md` — frontend local dev setup
- `docs/LOCAL_DOCKER_WORKFLOW.md` — Docker workflow for the full stack

Key things to communicate:
- Local dev uses `make docker-up` — no Vercel credentials needed
- To deploy to dev, they trigger the CD workflow in GitHub Actions UI and you (or they) approve it
- They **cannot** deploy locally — `VERCEL_TOKEN` is only in GitHub Environments
- They push feature branches, open PRs to `main`, CI must pass before merging

---

## Phase 11 — Verify Everything

Run through this checklist to confirm the setup is working end-to-end:

### Local dev (friend perspective)

- [ ] Clone `fitness-app-frontend`
- [ ] Copy `.env.example` → `.env.development`, fill in local values
- [ ] Run `make docker-up` — app loads at `http://localhost:3000`
- [ ] No Vercel token or prod secrets needed ✅

### Branch protection

- [ ] Attempt `git push origin main` directly → rejected ✅
- [ ] Open a PR with a lint error → merge button stays greyed out until CI passes ✅

### Dev deploy gate

- [ ] Go to `fitness-app-frontend` → Actions → CD → Run workflow → `development`
- [ ] GitHub shows "Waiting for review" notification ✅
- [ ] Click Review → Approve → workflow runs → deploys to dev URL ✅
- [ ] Dev Vercel URL (`https://fitness-app-frontend-dev.vercel.app`) is accessible ✅

### Prod deploy gate

- [ ] Run the same workflow with `production`
- [ ] Only you (owner) can approve ✅
- [ ] Friend's account has no "Approve" button for the `production` environment ✅

### No local deploy

- [ ] Friend runs `make vercel-deploy` locally → fails with "not logged in" / no token ✅

### Terraform CD

- [ ] Go to `kriegerdataforge-terraform` → Actions → CD — Terraform → Run workflow
- [ ] `infrastructure` environment gate appears → you approve → `terraform plan` + `apply` runs ✅

---

## Quick Reference — Secret Values Location

| Value | Where to find it |
|---|---|
| Vercel API Token | Vercel Dashboard → Settings → Tokens |
| Vercel Team ID | Vercel Dashboard → Settings → General → Team ID |
| Prod backend project ID | `prj_3kiJpapxo5G4Syd4j6i6LkeWXS9s` (already in Terraform outputs) |
| Prod fitness project ID | `prj_cqvUqHUTI2peopP8ZQalqPE3um7u` |
| Prod tiffanys project ID | `prj_Vwlw8Nts7rFo2Apq25ZhXN3K6fw9` |
| Dev project IDs | `terraform output` after Phase 1.3 |
| Neon connection strings | Neon Console → Project → Branches → Connection Details → psycopg2 format |
| Terraform Cloud token | app.terraform.io → User Settings → Tokens |
| `AUTH_SECRET_KEY` etc. | Your local `terraform.tfvars` |
