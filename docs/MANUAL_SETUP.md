# Manual Setup Guide

This document covers every step that cannot be automated by code. Complete these in order.

- Steps marked **ONCE** only need to be done once total.
- Steps marked **PER REPO** need to be repeated for each listed repository.
- **Part 1** (Phases 0–9) is what you need to complete right now (Stage 3 of the overall plan).
- **Part 2** (Phases 10–13) comes later, after Stage 6 (FastAPI separation) is done.

---

## Part 1 — Do Now (Stage 3 of overall plan)

Complete all phases in this section before moving to anything else. They must be done in order — each phase depends on the previous one.

---

## Phase 0 — Prerequisites

Before starting, make sure you have:

- [X] Vercel CLI installed locally (`npm i -g vercel`) and logged in
- [X] Terraform 1.9+ installed locally
- [X] `gh` CLI installed and authenticated (`gh auth login`)
- [X] Your Vercel Team ID handy (Vercel Dashboard → Settings → General → scroll to "Team ID")
- [X] Per-app Vercel tokens created (see step below)

### Create per-app Vercel tokens

> **ONCE** — Each app gets its own uniquely-named Vercel API token. If one token leaks you revoke only that one; the rest of the ecosystem keeps deploying. Tokens are team-scoped on Vercel's end (project-scoped tokens require separate Vercel teams), so the isolation benefit is independent revocation and a clean audit trail in Vercel logs — not hard project-level ACLs.

Go to **Vercel Dashboard → Settings → Tokens → Create Token** and create the following tokens.

For the **per-app deployment tokens** in the table below, use these settings:

| Field | Value |
|---|---|
| **Token Name** | see table below |
| **Scope** | **Arthur's projects** — this restricts the token to your Vercel team's projects only, following least-privilege. |
| **Expiration** | Custom — set ~35 days out. The monthly rotation workflow (Phase 6) will renew them automatically after initial setup. |

> **`kdf-master-rotation` is the exception — see Phase 6.1.** That token must use **Full Account** scope because the Vercel API endpoint for creating/deleting tokens (`/v3/user/tokens`) is a personal account API, not a team API. Tokens scoped to "Arthur's projects" receive a 403 Forbidden when calling it. The per-app tokens here never call that endpoint — they only make deployment calls, so team scope is sufficient and correct.

| Token name to enter in Vercel | Used by |
|---|---|
| `kdf-auth-backend-prod` | `kriegerdataforge` repo, `prod` environment |
| `kdf-auth-backend-dev` | `kriegerdataforge` repo, `dev` environment |
| `kdf-fitness-frontend-prod` | `fitness-app-frontend` repo, `prod` environment |
| `kdf-fitness-frontend-dev` | `fitness-app-frontend` repo, `dev` environment |
| `kdf-tiffanys-frontend-prod` | `tiffanys_space` repo, `prod` environment |
| `kdf-infra` | `kriegerdataforge-terraform` repo, `infra` environment |

Copy each token value immediately — Vercel shows it only once. Keep them in a secure location (e.g. 1Password) until you add them to GitHub Environments in Phase 4.

> **Future apps:** When a new app is provisioned, create tokens `kdf-{app}-{layer}-prod` and `kdf-{app}-{layer}-dev` with scope "Arthur's projects", add them to GitHub, then add the two registry entries in `scripts/vercel_token_registry.json` in this repo. The rotation workflow picks them up automatically on the next run.

---

## Phase 1 — Apply Terraform Changes (Disable Auto-Deploys + Create Dev Projects)

> **ONCE** — Run locally before anything else. This disables auto-deploys on the existing frontend projects and provisions the two new dev Vercel projects.
>
> **Note on database architecture:** Right now all apps share a single Neon project — the `kriegerdataforge` FastAPI backend is the only service that connects to it directly. The frontends (`fitness-app-frontend`, `tiffanys_space`) call the backend API, not the database. The plan to split into 3 separate databases (one per app: fitness, tiffanys-closet, KDF auth) is **Stage 7** of the overall plan and involves data migration. Do not try to set up 3 databases here — Phase 1 only needs a dev branch of the existing single database.

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
   postgresql://user:password@ep-xxxx.region.aws.neon.tech/dbname?sslmode=require
   ```

   > **Note:** Neon gives you `postgresql://`. The `postgresql+psycopg2://` variant is the SQLAlchemy dialect format used internally by the FastAPI app — Terraform stores and passes the raw `postgresql://` string as-is to Vercel.

7. Save it — this is your `dev_backend_db_database_url`

### 1.2 — Add Dev Variables to terraform.tfvars

Open `kriegerdataforge-terraform/terraform.tfvars` and add the following block at the bottom:

```hcl
# ── Development environment ─────────────────────────────────────────────────
dev_backend_db_database_url = "postgresql://user:pass@ep-xxxx.region.aws.neon.tech/dbname?sslmode=require"
dev_backend_url             = "https://placeholder-update-after-first-deploy.vercel.app"
dev_backend_cors_origins    = "http://localhost:3000,http://localhost:3001"
```

Replace the `dev_backend_db_database_url` value with the connection string from step 1.1.

> **Note:** `dev_backend_url` is a placeholder for now. After the first dev backend deploy completes (Phase 8), come back and update it with the actual Vercel URL (e.g. `https://kriegerdataforge-dev.vercel.app`), then re-run `terraform apply`.

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

Save these — you'll need them in Phase 5.

---

## Phase 2 — Set Up Terraform Cloud Remote State

> **⏸ DEFERRED** — Terraform runs locally for now. Remote state will be configured when the business justifies the cost. Do not complete this phase yet — skip directly to Phase 3.

---

## Phase 3 — Fine-Grained PAT for Issue Assistant + Token Rotation

> **ONCE** — Create this token now, before Phase 4. Phase 5 requires it to already exist as the `CICD_PAT` secret.

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
5. Click **Generate token** → copy the token immediately (shown only once)
6. Add it as a repo-level secret in `kriegerdataforge-cicd`:
   - Settings → Secrets and variables → Actions → New repository secret
   - Name: `CICD_PAT`, Value: paste the token

> **Why two names?** `CICD_REPO_ASSISTANT` is the display label for the token in GitHub's Developer Settings — it tells you what the token is for when you look at your token list later. `CICD_PAT` is the secret variable name in the repo, which is what workflows reference as `${{ secrets.CICD_PAT }}`. Same token, two contexts.
>
> This same `CICD_PAT` is used by both the issue assistant workflow and the Vercel token rotation workflow (Phase 6) — no separate PAT is needed for either.

---

## Phase 4 — GitHub Environments (PER REPO)

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

**Environment: `prod`**

1. Click **New environment** → name: `prod` → **Configure environment**
2. Check **Required reviewers** → Add yourself (the account owner)
3. Under **Deployment branches and tags** → select **Selected branches and tags** → Add rule → Branch name pattern: `main`
4. Click **Save protection rules**

**Environment: `dev`**

1. Click **New environment** → name: `dev` → **Configure environment**
2. Check **Required reviewers** → Add yourself
   - After your friend accepts the collaborator invite (Phase 12), come back and add them here too — fitness repos only (`fitness-app-frontend` and `fitness-app-backend`)
3. Under **Deployment branches and tags** → **Selected branches and tags** → Add rule → Branch name: `main`
4. Click **Save protection rules**

### For repo 6 (kriegerdataforge-terraform): Create ONE environment

**Environment: `infra`**

1. Click **New environment** → name: `infra` → **Configure environment**
2. Required reviewers: yourself only
3. Deployment branches: `main` only
4. Click **Save protection rules**

### For arthurs-portfolio: update the existing `github-pages` environment

1. Go to `arthurs-portfolio` → Settings → Environments → `github-pages` (already exists)
2. Check **Required reviewers** → Add yourself
3. Click **Save protection rules**

---

## Phase 5 — Environment Secrets (PER REPO)

> **MANUAL** — Secrets live in GitHub Environments, never in the repo. Add them via **Settings → Environments → [environment name] → Add secret**.
>
> **Prerequisite:** Phase 1 (Terraform) must be done before you can fill in the `dev` environment secrets — you need the dev project IDs from its output and the Neon dev branch connection string. You can add the `prod` secrets now and come back for `dev` after Phase 1.

### kriegerdataforge

**`prod` environment secrets:**
| Secret Name | Value |
|---|---|
| `VERCEL_TOKEN` | The `kdf-auth-backend-prod` token value from Phase 0 |
| `VERCEL_ORG_ID` | Your Vercel Team ID |
| `VERCEL_PROJECT_ID` | `prj_3kiJpapxo5G4Syd4j6i6LkeWXS9s` (prod backend) |
| `DB_DATABASE_URL` | Your production Neon psycopg2 connection string |

**`dev` environment secrets:**
| Secret Name | Value |
|---|---|
| `VERCEL_TOKEN` | The `kdf-auth-backend-dev` token value from Phase 0 |
| `VERCEL_ORG_ID` | Your Vercel Team ID |
| `VERCEL_PROJECT_ID` | The `kriegerdataforge_dev_project_id` from Phase 1.3 output |
| `DB_DATABASE_URL` | The dev Neon branch connection string from Phase 1.1 |

### fitness-app-frontend

**`prod` environment secrets:**
| Secret Name | Value |
|---|---|
| `VERCEL_TOKEN` | The `kdf-fitness-frontend-prod` token value from Phase 0 |
| `VERCEL_ORG_ID` | Your Vercel Team ID |
| `VERCEL_PROJECT_ID` | `prj_cqvUqHUTI2peopP8ZQalqPE3um7u` (prod fitness app) |

**`dev` environment secrets:**
| Secret Name | Value |
|---|---|
| `VERCEL_TOKEN` | The `kdf-fitness-frontend-dev` token value from Phase 0 |
| `VERCEL_ORG_ID` | Your Vercel Team ID |
| `VERCEL_PROJECT_ID` | The `fitness_app_dev_project_id` from Phase 1.3 output |

### tiffanys_space

**`prod` environment secrets:**
| Secret Name | Value |
|---|---|
| `VERCEL_TOKEN` | The `kdf-tiffanys-frontend-prod` token value from Phase 0 |
| `VERCEL_ORG_ID` | Your Vercel Team ID |
| `VERCEL_PROJECT_ID` | `prj_Vwlw8Nts7rFo2Apq25ZhXN3K6fw9` (prod tiffanys) |

**`dev` environment secrets:**
| Secret Name | Value |
|---|---|
| `VERCEL_TOKEN` | *(No dev project for tiffanys yet — skip. When provisioned in Terraform, create `kdf-tiffanys-frontend-dev` in Vercel, add it here, and add the registry entry in `scripts/vercel_token_registry.json`)* |
| `VERCEL_ORG_ID` | *(skip until dev project exists)* |
| `VERCEL_PROJECT_ID` | *(skip until dev project exists)* |

### kriegerdataforge-terraform (`infra` environment)

**Secrets** (use "Add secret" for all of these):
| Secret Name | Value |
|---|---|
| `VERCEL_API_TOKEN` | The `kdf-infra` token value from Phase 0 |
| `BACKEND_AUTH_SECRET_KEY` | Value from `terraform.tfvars` → `backend_auth_secret_key` |
| `BACKEND_AUTH_ADMIN_EMAIL` | Value from `terraform.tfvars` → `backend_auth_admin_email` |
| `BACKEND_AUTH_ADMIN_EMAIL_PASSWORD` | Value from `terraform.tfvars` → `backend_auth_admin_email_password` |
| `BACKEND_DB_DATABASE_URL` | Value from `terraform.tfvars` → `backend_db_database_url` |
| `DEV_BACKEND_DB_DATABASE_URL` | Value from `terraform.tfvars` → `dev_backend_db_database_url` |
| `FRONTEND_AUTH_SECRET_KEY` | Value from `terraform.tfvars` → `frontend_auth_secret_key` |
| `TIFFANYS_SPACE_CRON_SECRET` | Value from `terraform.tfvars` → `tiffanys_space_cron_secret` |
| `VERCEL_TEAM_ID` | Your Vercel Team ID |
| `BACKEND_URL_PRODUCTION` | Value from `terraform.tfvars` → `backend_url_production` |
| `BACKEND_URL_PREVIEW` | Value from `terraform.tfvars` → `backend_url_preview` |
| `DEV_BACKEND_URL` | Placeholder for now — update after Phase 8 first dev deploy |
| `BACKEND_STRIPE_SECRET_KEY` | *(placeholder — skip for now, add when Stripe is enabled)* |
| `BACKEND_STRIPE_WEBHOOK_SECRET` | *(placeholder — skip for now, add when Stripe is enabled)* |
| `FITNESS_APP_SENTRY_AUTH_TOKEN` | *(placeholder — skip for now, add when Sentry is configured)* |
| `TIFFANYS_SPACE_SENTRY_AUTH_TOKEN` | *(placeholder — skip for now, add when Sentry is configured)* |
| ~~`TF_TOKEN_APP_TERRAFORM_IO`~~ | ~~Terraform Cloud API token~~ — **DEFERRED** (see Phase 2) |

> The four placeholder secrets still need to be created as secrets in GitHub — just set their value to an empty string `""` for now. The Terraform CD workflow will pass them through as empty and the apps handle them gracefully (Stripe and Sentry are disabled via their respective feature flags).

> **How to find your production backend URL:** Vercel Dashboard → `kriegerdataforge` project → Domains.

### kriegerdataforge-cicd (repo-level secret, NOT environment-scoped)

1. Go to **Settings → Secrets and variables → Actions → New repository secret**
2. Name: `CICD_PAT` — Value: the fine-grained PAT from Phase 3

---

## Phase 6 — Token Rotation Infrastructure

> **ONCE** — Set up the monthly automated Vercel token rotation. Requires `CICD_PAT` from Phase 3 to already be in place.

### 6.1 — Create the `VERCEL_MASTER_TOKEN` in Vercel

This is a long-lived "meta-token" whose only job is to create and delete the per-app tokens during rotation. It should **not** be used for deployments.

1. Go to **Vercel Dashboard → Settings → Tokens → Create Token**
2. Token name: `kdf-master-rotation`
3. **Scope: Full Account** — this is the required exception. The Vercel API endpoint for creating and deleting tokens (`/v3/user/tokens`) is a personal account API; team-scoped tokens receive a 403 Forbidden. This token is never used for deployments, only for token lifecycle management.
4. Expiration: 1 year (rotate manually on a calendar reminder — set one now)
5. Copy the token value immediately

### 6.2 — Add `VERCEL_MASTER_TOKEN` to `kriegerdataforge-cicd`

1. Go to `kriegerdataforge-cicd` → **Settings → Secrets and variables → Actions → New repository secret**
2. Name: `VERCEL_MASTER_TOKEN`
3. Value: the token from step 6.1

> `CICD_PAT` (added in Phase 3) already has `secrets:write` on all repos — no additional PAT is needed for the rotation script.

### 6.3 — Verify the rotation workflow runs

1. Go to `kriegerdataforge-cicd` → **Actions → Rotate Vercel Tokens**
2. Click **Run workflow** → **Run workflow** (manual trigger, no filter inputs needed — rotates all)
3. The workflow will create a new token for each entry in `scripts/vercel_token_registry.json`, push it to the corresponding GitHub environment secret, and delete the old token
4. After it completes, confirm in Vercel Dashboard → Settings → Tokens that the old tokens are gone and new ones with fresh expiry dates appear

> **Schedule:** The workflow runs automatically on the 1st of every month at 09:00 UTC. You will receive a GitHub Actions failure notification if any rotation fails.
>
> **Targeted rotation:** You can also trigger it for a single app/env after a suspected leak — use the `apps` and `envs` inputs when running manually. See `scripts/rotate_vercel_tokens.py --help` for examples.

---

## Phase 6.5 — GH_PACKAGES_PAT Setup and Rotation

> **ONCE** — Required for any repo that uses `kdf-auth-sdk`. The `GH_PACKAGES_PAT` is a fine-grained PAT used by GitHub Actions (pip install on the runner) and by Vercel (installCommand in vercel.json) to clone the private `kriegerdataforge-python-sdk` repo during builds.

### 6.5.1 — Create the initial `kdf-packages-read` fine-grained PAT

1. Go to **GitHub → Profile → Settings → Developer settings → Personal access tokens → Fine-grained tokens**
2. Click **Generate new token**
3. Configure:
   - **Token name:** `kdf-packages-read`
   - **Expiration:** 1 year
   - **Resource owner:** `Needless2Say`
   - **Repository access:** Only selected repositories → `kriegerdataforge-python-sdk`
   - **Repository permissions:** Contents → **Read-only** (only permission needed)
4. Click **Generate token** → copy the value immediately (shown only once)

### 6.5.2 — Store it as GH_PACKAGES_PAT_NEW in this repo

1. Go to `kriegerdataforge-cicd` → **Settings → Secrets and variables → Actions → New repository secret**
2. Name: `GH_PACKAGES_PAT_NEW`, Value: the token from step 6.5.1

### 6.5.3 — Run the distribute workflow

1. Go to `kriegerdataforge-cicd` → **Actions → Distribute GH_PACKAGES_PAT → Run workflow**
2. This pushes the new PAT to all GitHub environment secrets in all backend repos and all Vercel project env vars listed in `scripts/gh_pat_registry.json`

### 6.5.4 — Update the expiry date in the registry

1. Open `scripts/gh_pat_registry.json` in this repo
2. Update `"pat_expiry"` to the expiry date you set in step 6.5.1 (format: `YYYY-MM-DD`)
3. Commit and push the change — this keeps the check workflow accurate

### 6.5.5 — Clean up and add Vercel project IDs

1. Delete the `GH_PACKAGES_PAT_NEW` secret from repo secrets (it is no longer needed)
2. Open `scripts/gh_pat_registry.json` and fill in any `project_id` values that still say `TODO_*`
   - Vercel project IDs are available in your Vercel Dashboard → each project → Settings → General → Project ID
   - Or from `terraform output` if provisioned via Terraform

### 6.5.6 — Set GH_PACKAGES_PAT in Vercel project settings (first-time only)

For each backend Vercel project that uses `kdf-auth-sdk` and hasn't had the variable set yet:
1. Vercel Dashboard → project → **Settings → Environment Variables → Add New**
2. Name: `GH_PACKAGES_PAT`, Value: the token, Environment: All (Production + Preview + Development)

> After the first distribute run, subsequent rotations will update these automatically via the Vercel API.

### When the check workflow fires (biweekly expiry check)

The `Check GH_PACKAGES_PAT Expiry` workflow runs on the 1st and 15th of each month. If the token is within 14 days of expiry (or already expired), the workflow fails and GitHub sends you an email.

**To rotate:**
1. Create a new fine-grained PAT with the same settings as 6.5.1
2. Add it as `GH_PACKAGES_PAT_NEW` in repo secrets
3. Trigger **Distribute GH_PACKAGES_PAT** workflow
4. Update `pat_expiry` in `scripts/gh_pat_registry.json` and commit
5. Delete `GH_PACKAGES_PAT_NEW` from repo secrets
6. Optionally revoke the old token: GitHub → Settings → Developer settings → Fine-grained tokens → old `kdf-packages-read` → **Revoke**

---

## Developer Local Setup — Installing kdf-auth-sdk

> **PER DEVELOPER** — Each developer on the project creates their own fine-grained PAT to `pip install kdf-auth-sdk` locally. Never share a token between developers — if a developer's token is compromised or their access is revoked, you'd otherwise need to rotate the shared token for everyone.

### One-time setup for each developer

1. **Create a personal fine-grained PAT:**
   - GitHub → Profile → Settings → Developer settings → Personal access tokens → Fine-grained tokens
   - Click **Generate new token**
   - Token name: `kdf-local-dev` (or any descriptive name)
   - Expiration: 1 year (or 90 days — your choice)
   - Resource owner: `Needless2Say`
   - Repository access: Only selected repositories → `kriegerdataforge-python-sdk`
   - Permission: Contents → **Read-only**
   - Generate and copy the token

2. **Configure git to use it for GitHub HTTPS:**
   ```bash
   git config --global url."https://__token__:<YOUR_PAT>@github.com/".insteadOf "https://github.com/"
   ```
   Replace `<YOUR_PAT>` with your token value. This tells git (and pip) to authenticate private GitHub URLs automatically. It applies globally to all git operations from your machine, but the token only has read access to one repo so the blast radius of a leak is minimal.

3. **Verify it works:**
   ```bash
   pip install "kdf-auth-sdk @ git+https://github.com/Needless2Say/kriegerdataforge-python-sdk.git@v0.0.3"
   ```
   This should install without prompting for credentials.

4. **For normal local dev, just run:**
   ```bash
   make docker-up
   ```
   The Docker workflow pre-installs everything; you only need the git config step above if you're running tests or the app outside Docker.

> **When a developer leaves the project:** Go to GitHub → Settings → Collaborators for the relevant repos and remove their access. Their personal PAT only works for the SDK repo (read-only), which becomes inaccessible once their GitHub account no longer has access. No shared token rotation required.

---

## Phase 7 — Remove Old Repo-Level Deployment Secrets

> **ONCE** — After environment secrets are set in Phase 5, remove any stale repo-level deployment secrets.

For `kriegerdataforge`, `fitness-app-frontend`, `tiffanys_space`:

1. Go to **Settings → Secrets and variables → Actions**
2. Delete any of these if they exist at the repo level (not environment level):
   - `VERCEL_TOKEN`
   - `VERCEL_PROJECT_ID`
   - `VERCEL_ORG_ID`

> This ensures workflows always read tokens from the environment scope, not a stale repo-level copy. The rotation workflow only updates environment secrets — any repo-level copies would never be rotated and would go stale.

---

## Phase 8 — First Dev Deploys (Verify the New Projects Work)

> **ONCE** — Deploy to dev for the first time to get the actual Vercel URLs. Requires secrets from Phase 5 to be in place.

### 8.1 — Deploy dev backend

1. Go to `kriegerdataforge` repo → **Actions** → **CD** workflow
2. Click **Run workflow** → Environment: `dev`, Run migrations: ✅ → **Run workflow**
3. Wait for the approval notification → Click **Review deployments** → **Approve**
4. Wait for the deploy to complete → note the Vercel deployment URL from the logs

### 8.2 — Update dev URLs in Terraform + GitHub Variables

1. Open `kriegerdataforge-terraform/terraform.tfvars` and update:

   ```hcl
   dev_backend_url          = "https://kriegerdataforge-dev.vercel.app"
   dev_backend_cors_origins = "http://localhost:3000,http://localhost:3001,https://fitness-app-frontend-dev.vercel.app"
   ```

2. Update the `DEV_BACKEND_URL` GitHub variable in `kriegerdataforge-terraform` → `infra` environment
3. Run `terraform apply` locally (or trigger the Terraform CD workflow)

### 8.3 — Deploy dev frontend

1. Go to `fitness-app-frontend` → **Actions** → **CD** → Run workflow → `dev` → approve → wait

---

## Phase 9 — Verify Everything Works

Run through this checklist to confirm the setup is working end-to-end.

### Dev deploy gate

- [X] Go to `fitness-app-frontend` → Actions → CD → Run workflow → `dev`
- [X] GitHub shows "Waiting for review" notification ✅
- [X] Click Review → Approve → workflow runs → deploys to dev URL ✅
- [X] Dev Vercel URL (`https://fitness-app-frontend-dev.vercel.app`) is accessible ✅

### Prod deploy gate

- [X] Run the same workflow with `prod`
- [X] Only you (owner) can approve ✅

### Token rotation

- [X] Go to `kriegerdataforge-cicd` → Actions → Rotate Vercel Tokens → Run workflow
- [X] Workflow completes without errors ✅
- [X] Vercel Dashboard shows fresh token expiry dates on all `kdf-*` tokens ✅

### Terraform CD

- [X] Go to `kriegerdataforge-terraform` → Actions → CD — Terraform → Run workflow
- [X] `infra` environment gate appears → you approve → `terraform plan` + `apply` runs ✅

### Branch protection

> **⏸ DEFERRED** — Free tier private repos do not support branch protection rules. Revisit after Phase 13 (GitHub Organization migration).

---

## Part 2 — Do Later (Stage 9 of overall plan)

Complete Part 2 **after** Stage 6 (FastAPI separation) is done and the `fitness-app-backend` repo exists. These phases depend on that repo being in place.

> **Note on private repos + reusable workflows:** Currently `kriegerdataforge-cicd` must be **public** so that other repos can call its reusable workflows. If you want all repos private, you need to migrate to a GitHub Organization first (Phase 13). Do Phase 13 before Phase 11 if you want both branch protection and private repos simultaneously.

---

## Phase 10 — Create Template Repositories

> **MANUAL** — Create 4 empty GitHub repos and mark them as templates. These are required before the issue assistant can auto-provision new repos.

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

> **Suggested template content:** Copy the relevant files from an existing repo (e.g., copy `fitness-app-frontend/.github/workflows/ci.yml`, `Makefile`, `AGENTS.md`, `Dockerfile` into `kriegerdataforge-template-nextjs`) and strip out app-specific content.

---

## Phase 11 — Branch Protection

> **⏸ DEFERRED** — Free tier private repositories on GitHub do not support branch protection rules. Complete Phase 13 (GitHub Organization migration) first, then come back here.

---

## Phase 12 — Friend Onboarding

> **MANUAL** — Complete after Phase 10 and after `fitness-app-backend` repo exists (Stage 6 of overall plan).

### 12.1 — Add friend as collaborator (fitness repos only)

Friend gets **Write** access to exactly two repos — no other repos:

1. `fitness-app-frontend` → Settings → Collaborators → Add people → Write role
2. `fitness-app-backend` → Settings → Collaborators → Add people → Write role

> **Do NOT** add the friend to `kriegerdataforge`, `tiffanys-closet-backend`, `kriegerdataforge-terraform`, `kriegerdataforge-cicd`, or any other repo. Fine-grained per-repo access is intentional.

### 12.2 — Add friend as `dev` environment reviewer (fitness repos only)

After the friend accepts the collaborator invite:

1. `fitness-app-frontend` → Settings → Environments → `dev` → Required reviewers → add friend → Save protection rules
2. `fitness-app-backend` → Settings → Environments → `dev` → Required reviewers → add friend → Save protection rules

> Friend should NOT be added as a reviewer on any other repo's environments.

### 12.3 — Send onboarding resources

Share these docs with your friend:

- `kriegerdataforge/docs/SETUP_AND_ONBOARDING.md` — backend local dev setup
- `fitness-app-frontend/docs/SETUP_AND_ONBOARDING.md` — frontend local dev setup
- `docs/LOCAL_DOCKER_WORKFLOW.md` — Docker workflow for the full stack

Key things to communicate:
- Local dev uses `make docker-up` — no Vercel credentials needed
- To deploy to dev, they trigger the CD workflow in GitHub Actions UI and approve it
- They **cannot** deploy locally — `VERCEL_TOKEN` is only in GitHub Environments
- They push feature branches, open PRs to `main`, CI must pass before merging

---

## Quick Reference — Where to Find Secret Values

| Value | Where to find it |
|---|---|
| `kdf-auth-backend-prod` token | Vercel Dashboard → Settings → Tokens (copy when created in Phase 0) |
| `kdf-auth-backend-dev` token | Same |
| `kdf-fitness-frontend-prod` token | Same |
| `kdf-fitness-frontend-dev` token | Same |
| `kdf-tiffanys-frontend-prod` token | Same |
| `kdf-infra` token | Same |
| `kdf-master-rotation` token (`VERCEL_MASTER_TOKEN`) | Vercel Dashboard → Settings → Tokens (created in Phase 6.1) |
| Vercel Team ID (`VERCEL_ORG_ID`) | Vercel Dashboard → Settings → General → Team ID |
| Prod backend project ID | `prj_3kiJpapxo5G4Syd4j6i6LkeWXS9s` (hardcoded) |
| Prod fitness project ID | `prj_cqvUqHUTI2peopP8ZQalqPE3um7u` (hardcoded) |
| Prod tiffanys project ID | `prj_Vwlw8Nts7rFo2Apq25ZhXN3K6fw9` (hardcoded) |
| Dev project IDs | `terraform output` after Phase 1.3 |
| Neon connection strings | Neon Console → Project → Branches → Connection Details → psycopg2 format |
| `AUTH_SECRET_KEY` etc. | Your local `terraform.tfvars` |

---

## Phase 13 — GitHub Organization Migration

> **⏸ DEFERRED** — Do this when you want to keep all repos **private** while still sharing reusable workflows across them, AND to unlock branch protection rules on private repos. **No payment required** — GitHub Organizations are free for public and private repos at the personal/hobby scale (you pay per seat only if you add members who need private repo access beyond collaborator level).

### Why this is needed

GitHub has two separate limitations on personal accounts that go away with an Organization:

| Feature | Personal account (Free/Pro) | GitHub Organization (Free tier) |
|---|---|---|
| Reusable workflows across private repos | ❌ Not allowed | ✅ Allowed (org setting) |
| Branch protection on private repos | ❌ Not allowed | ✅ Allowed |
| Cross-repo workflow calls stay private | ❌ Must make cicd repo public | ✅ All repos stay private |

**GitHub Pro** (paid personal account) does **not** unlock either of these features — they are architectural restrictions on personal accounts, not a paid tier gate.

### Steps

#### 13.1 — Create a GitHub Organization

1. Go to [github.com/organizations/new](https://github.com/organizations/new)
2. Choose **Free** plan
3. Organization name: `KriegerDataForge` (or similar — this becomes part of repo URLs)
4. Contact email: your email
5. Finish setup

#### 13.2 — Enable reusable workflows org-wide

1. Go to `github.com/organizations/KriegerDataForge/settings/actions`
2. Under **Policies** → **Fork pull request workflows** — leave default
3. Under **Workflow permissions** → ensure **Read and write permissions** is selected
4. Look for **Allow reusable workflows from this organization** → enable it ✅
5. Save

#### 13.3 — Transfer repos to the organization

For each repo, go to **Settings → Danger Zone → Transfer ownership** → transfer to `KriegerDataForge` org.

Transfer in this order (dependencies first):

1. `kriegerdataforge-cicd` — must be transferred first; other repos depend on it
2. `kriegerdataforge-terraform`
3. `kriegerdataforge`
4. `fitness-app-frontend`
5. `tiffanys_space`
6. `arthurs-portfolio`
7. `kriegerdataforge-portfolio`

> After transfer, GitHub automatically creates redirects from the old personal URLs to the org URLs. Existing `git remote` URLs in local clones will continue to work.

#### 13.4 — Update workflow `uses:` references

After transfer, the reusable workflow path changes from:
```
Needless2Say/kriegerdataforge-cicd/.github/workflows/cd-python-vercel.yml@main
```
to:
```
KriegerDataForge/kriegerdataforge-cicd/.github/workflows/cd-python-vercel.yml@main
```

Update all `uses:` lines in:
- `kriegerdataforge/.github/workflows/cd.yml`
- `fitness-app-frontend/.github/workflows/cd.yml`
- `tiffanys_space/.github/workflows/cd.yml`
- Any other consumer workflows

#### 13.5 — Make `kriegerdataforge-cicd` private again

Once the org setting is enabled and all consumer repos are in the org:

1. `kriegerdataforge-cicd` → Settings → Danger Zone → Change visibility → **Make private**
2. Re-run a CD workflow in any consumer repo to confirm cross-repo calls still work

#### 13.6 — Re-apply branch protection (Phase 11)

Now that repos are in an org, go back and complete Phase 11.

