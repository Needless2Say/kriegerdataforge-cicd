# Reusable-workflow catalog

Interface reference for every **reusable GitHub Actions workflow** (`on: workflow_call`) and the
**`run-e2e` composite action** in `kriegerdataforge-cicd`. Every tenant repo calls these live from
`@main`, so the inputs / secrets / outputs / permissions below are a **public contract** — changing
one is a breaking-change candidate for all consumers (see `CONTRIBUTING.md` and AGENTS.md rules 4–6).

Enumerated strictly from `.github/workflows/*.yml` and `.github/actions/run-e2e/action.yml` as of
this writing. Each entry cites `file:line`.

- **Overview + consumption rules** — this section.
- **The contract** — [Reusable workflow catalog](#reusable-workflow-catalog) (per-workflow inputs,
  secrets, outputs, permissions, caller snippet) + [`run-e2e` composite action](#run-e2e-composite-action).
- **Deploy gate / approval model** — [Deployment model](#deployment-model) + [Deployer authorization gate](#deployer-authorization-gate).
- **Live vs. not-`uses:`-able** — [Repo-internal event-triggered workflows](#repo-internal-event-triggered-workflows) (the ops / rotation / provisioning workflows that are **not** `workflow_call`).

---

## How reusable workflows are consumed

A consumer repo's workflow references one of these by full path + ref:

```yaml
jobs:
  <job>:
    uses: Needless2Say/kriegerdataforge-cicd/.github/workflows/<workflow>.yml@main
    with:      # inputs (only if the workflow declares any)
      ...
    secrets: inherit   # required whenever the workflow reads ${{ secrets.* }}
```

Two facts hold for **every** workflow in this repo:

1. **No workflow declares an explicit `secrets:` block** under `on: workflow_call:`. Each reads
   secrets directly via `${{ secrets.NAME }}`, so a caller that needs to pass any secret **must**
   use `secrets: inherit`. The "Secrets" column below lists the secrets each workflow reads at
   runtime — they are supplied by the caller's repo/environment, not declared as workflow inputs.
2. **Third-party actions are SHA-pinned** (`actions/checkout@9c091bb…` = v7.0.0, `setup-python@ece7cb06…`
   = v6, `setup-node@48b55a01…` = v6, etc.) per AGENTS.md rule 2. Bump via Dependabot.

> **Ref-pinning note.** All examples use `@main` (the live contract), matching how tenants call today.
> A consumer that wants change-isolation may pin `@vX.Y.Z` instead; this repo publishes tags via
> [`create-github-release.yml`](#create-github-releaseyml).

---

## Deployment model

All deploys are **manual** (`workflow_dispatch` in the consumer, which then calls the reusable CD
workflow). There are no push-triggered deploys; Vercel git auto-deploy is off. Flow:

1. A deployer clicks **Run workflow** in the consumer repo, choosing `environment` (+ `version`).
2. The reusable CD workflow's **`authorize`** job runs *first* (before any approval or secret load)
   and fails closed if the actor is not an approved deployer — see
   [Deployer authorization gate](#deployer-authorization-gate).
3. The `deploy`/`apply` job declares `environment: ${{ inputs.environment }}`, which activates the
   GitHub **Environment approval gate** — the run pauses for a required reviewer.
4. On approval, environment-scoped secrets load and the deploy runs. On rejection/timeout, nothing
   deploys.

### Environment approval model

The GitHub Environments and their required reviewers are provisioned by
[`issue-create-repo.yml:168-223`](../../.github/workflows/issue-create-repo.yml) and documented in
[`MANUAL_SETUP.md` Phase 4](../guides/MANUAL_SETUP.md). The **only** environment names in use — and the
keys the deployer registry is keyed on — are:

| GitHub Environment | Required reviewer(s) | Deployment branch policy |
|---|---|---|
| `dev` | Owner (provisioned owner-only; a collaborator may be **added manually** to the `dev` required-reviewers list — `issue-create-repo.yml:198-223`, completion checklist line 277) | `main` only |
| `prod` | Owner only (`issue-create-repo.yml:168-196`) | `main` only |
| `github-pages` | Owner (`arthurs-portfolio` only — self-contained Pages deploy; `MANUAL_SETUP.md` Phase 4 "For arthurs-portfolio") | GitHub Pages (no `dev`/`prod`) |

> **There is no `infra` / `infrastructure` / `development` / `production` environment.** The Terraform
> CD workflow deploys to `dev`/`prod` like the others (`cd-terraform.yml:99`; `deployer_registry.json`
> `kriegerdataforge-terraform` → `{dev, prod}`; `MANUAL_SETUP.md` Phase 4 "For repo 6"). Use the short
> names `dev` / `prod` / `github-pages` exactly (AGENTS.md rule 9).
>
> **Source caveat (follow-up, not fixed here):** the `environment` input *description* strings in
> `cd-nextjs-vercel.yml:33` and `cd-python-vercel.yml:40` still read `"development" or "production"`.
> Those are stale doc-strings — the value a caller passes must be `dev`/`prod` to match the registry
> keys and the real GitHub Environments. `cd-terraform.yml:99` already says `(dev or prod)`.

**Key security property:** `VERCEL_DEPLOYMENT_TOKEN`, `DB_DATABASE_URL`, the RSA PEMs, and every other
deploy credential live only in GitHub repo/Environment secrets — never in `.env`, never echoed
(deploy steps log only the token's trimmed length, e.g. `cd-nextjs-vercel.yml:133`).

---

## Deployer authorization gate

GitHub cannot restrict **who** may `workflow_dispatch` a run — anyone with write access can. The
Environment gate covers `prod` (owner-only reviewer), but on `dev` a collaborator is also an allowed
reviewer and could self-approve. So every reusable CD workflow runs a **deployer authorization gate**
as its first job.

**How it works:**

1. `cd-nextjs-vercel.yml`, `cd-python-vercel.yml`, and `cd-terraform.yml` each start with an
   `authorize` job that the `deploy`/`apply` job `needs:`. (`arthurs-portfolio`'s self-contained
   `nextjs.yml` runs the same gate before its build.)
2. `authorize` sparse-checks-out this repo's `scripts/` and runs
   [`scripts/check_deployer.py`](../../scripts/check_deployer.py) (`cd-nextjs-vercel.yml:47-70`).
3. The script matches `github.triggering_actor` (whoever clicked **Run workflow**) against
   [`scripts/deployer_registry.json`](../../scripts/deployer_registry.json), keyed by
   `github.repository` and the target `environment`. Matching is case-insensitive.
4. **Not authorized → the job fails → the deploy job never runs.** Because `authorize` has **no
   `environment:`**, it runs *before* the approval is even requested — an unauthorized dispatch fails
   fast, no approval notification, no secrets loaded (fail closed).

**Registry shape** (`scripts/deployer_registry.json`) — `repo → environment → [usernames]`:

```json
{
  "deployers": {
    "Needless2Say/fitness-app-frontend": { "dev": ["Needless2Say", "Ascensionn"], "prod": ["Needless2Say"] },
    "Needless2Say/arthurs-portfolio":    { "github-pages": ["Needless2Say"] }
  }
}
```

A repo not in the registry, an environment not listed for that repo, or an actor not in the list →
**denied**. When onboarding a tenant, add its entry *before* its first deploy. Environment keys must
match the value the caller passes to the reusable workflow's `environment` input.

**Repo access for the gate:** the `authorize` job checks out `kriegerdataforge-cicd` with the default
`github.token`. Because this repo is **public**, that built-in token clones it. If cicd ever goes
private (post org-move), this checkout needs a read-only token — tracked in
`KDF docs/engineering/GITHUB_FUTURE_ENHANCEMENTS.md`.

`check_deployer.py` is stdlib-only and unit-tested in `scripts/tests/test_check_deployer.py`.

---

## Reusable workflow catalog

19 workflows are `on: workflow_call`. None declares an explicit `secrets:` block, so callers pass
`secrets: inherit`. Permissions are stated as declared in each file (top-level and/or per-job); an
undeclared scope means the workflow relies on the caller's / default token.

### Deployment (CD)

These three share the [Deployer authorization gate](#deployer-authorization-gate) (`authorize` job:
`permissions: contents: read`); the two Vercel ones also pin the Vercel CLI to `vercel@48.0.0`. Every one has a **required
`version`** input — the deploy job checks out `ref: v${{ inputs.version }}` (i.e. pass `1.2.0`, the
workflow prepends `v`), enabling rollback to an older tag.

#### `cd-nextjs-vercel.yml`

Deploy a Next.js app to a Vercel project (`npm ci` → `vercel --prod --yes --token …`).

| Input | Type | Default | Required |
|---|---|---|---|
| `environment` | string | — | **yes** — `dev` or `prod` (`:32-35`) |
| `version` | string | — | **yes** — tag to deploy, e.g. `1.2.0` (`:36-39`) |

- **Secrets read (via `inherit`):** `VERCEL_DEPLOYMENT_TOKEN` (repo-level), `VERCEL_ORG_ID`,
  `VERCEL_PROJECT_ID` (per-environment; job fails fast if unset — `:101-113`).
- **Outputs:** none.
- **Permissions:** `deploy` job — `contents: read`, `id-token: write` (Vercel OIDC) (`:82-84`).
- **Consumers:** `fitness-app-frontend`, `tiffanys-space` (and `kriegerdataforge-auth-ui`,
  `kriegerdataforge-template-nextjs` per the registry). `arthurs-portfolio` deploys self-contained to
  GitHub Pages, not via this workflow.

```yaml
# .github/workflows/cd.yml in the consumer repo
on:
  workflow_dispatch:
    inputs:
      environment: { description: Target environment, required: true, type: choice, options: [dev, prod] }
      version:     { description: "Version to deploy (e.g. 1.2.0)", required: true, type: string }
jobs:
  deploy:
    uses: Needless2Say/kriegerdataforge-cicd/.github/workflows/cd-nextjs-vercel.yml@main
    with:
      environment: ${{ inputs.environment }}
      version: ${{ inputs.version }}
    secrets: inherit
```

#### `cd-python-vercel.yml`

Deploy a FastAPI backend to Vercel: install deps (with private-SDK git auth) → compact `api/` into
`vercel_api/` via `scripts/vercel_compactor.py` → `vercel --prod` → optional Alembic migration.

| Input | Type | Default | Required |
|---|---|---|---|
| `environment` | string | — | **yes** — `dev` or `prod` (`:38-42`) |
| `run_migrations` | **string** | `'true'` | no — gate is `if: inputs.run_migrations == 'true'`; pass the **string** `'true'`/`'false'` (`:43-47`, `:169`, `:175`) |
| `version` | string | — | **yes** — tag to deploy (`:48-51`) |

- **Secrets read (via `inherit`):** `VERCEL_DEPLOYMENT_TOKEN`, `GH_PACKAGES_PAT` (private-SDK clone —
  `:112-115`), `VERCEL_ORG_ID`, `VERCEL_PROJECT_ID`, `DB_DATABASE_URL` (only when `run_migrations`,
  `:178`).
- **Outputs:** none.
- **Permissions:** `deploy` job — `contents: read`, `id-token: write` (`:94-96`).
- **Consumers:** `kriegerdataforge` (hub). Registry also lists `fitness-app-backend`,
  `tiffanys-space-backend`, `kriegerdataforge-template-fastapi`.

```yaml
jobs:
  deploy:
    uses: Needless2Say/kriegerdataforge-cicd/.github/workflows/cd-python-vercel.yml@main
    with:
      environment: ${{ inputs.environment }}   # dev | prod
      run_migrations: ${{ inputs.run_migrations }}   # string 'true' | 'false'
      version: ${{ inputs.version }}
    secrets: inherit
```

#### `cd-terraform.yml`

`terraform init` → `validate` → `plan -detailed-exitcode` → advisory conftest policy gate → `apply`
(only when the plan reports changes, exit code 2). Runs every command with
`-chdir=environments/${{ inputs.environment }}` (directory-per-environment; no workspaces).

| Input | Type | Default | Required |
|---|---|---|---|
| `environment` | string | — | **yes** — `dev` or `prod`; selects `environments/<env>/` **and** the Environment gate (`:98-101`) |
| `version` | string | — | **yes** — tag to deploy; note rolling back reverts config, not state (`:102-105`) |

- **Secrets read (via `inherit`)** — injected as `TF_VAR_*` env (`:153-201`):

  | Secret | → Terraform var |
  |---|---|
  | `VERCEL_DEPLOYMENT_TOKEN` | `vercel_api_token` |
  | `BACKEND_AUTH_PRIVATE_KEY` / `_PUBLIC_KEY` / `FRONTEND_AUTH_PUBLIC_KEY` | `backend_auth_private_key` / `_public_key` / `frontend_auth_public_key` |
  | `BACKEND_AUTH_ADMIN_EMAIL` / `_PASSWORD` | `backend_auth_admin_email` / `_password` |
  | `KDF_AUTH_DB_DATABASE_URL`, `FITNESS_APP_BACKEND_DB_DATABASE_URL`, `TIFFANYS_SPACE_BACKEND_DB_DATABASE_URL` | matching `*_db_database_url` |
  | `FITNESS_APP_SERVICE_KEY`, `TIFFANYS_SPACE_SERVICE_KEY`, `KDF_AUTH_UI_SERVICE_KEY` | matching `*_service_key` |
  | `FITNESS_OIDC_CLIENT_SECRET`, `TIFFANYS_SPACE_OIDC_CLIENT_SECRET` | matching `*_oidc_client_secret` |
  | *Optional:* `TIFFANYS_SPACE_CRON_SECRET`, `BACKEND_STRIPE_SECRET_KEY`, `BACKEND_STRIPE_WEBHOOK_SECRET`, `TF_TOKEN_APP_TERRAFORM_IO` | matching vars / TF Cloud auth |

- **Non-secret vars read (`vars.*` → `TF_VAR_*`, `:177-199`):** `BACKEND_URL`,
  `FITNESS_APP_BACKEND_URL`, `TIFFANYS_SPACE_BACKEND_URL`, `KDF_AUTH_SERVICE_PROJECT_NAME`,
  `FITNESS_APP_PROJECT_NAME`, `FITNESS_APP_BACKEND_PROJECT_NAME`, `TIFFANYS_SPACE_PROJECT_NAME`,
  `TIFFANYS_SPACE_BACKEND_PROJECT_NAME`, `KDF_AUTH_UI_URL`, `FITNESS_OIDC_CLIENT_ID`,
  `FITNESS_OIDC_REDIRECT_URI`, `TIFFANYS_SPACE_OIDC_CLIENT_ID`, `TIFFANYS_SPACE_OIDC_REDIRECT_URI`;
  optional `KDF_AUTH_CORS_ORIGINS`, `FITNESS_APP_BACKEND_CORS_ORIGINS`,
  `TIFFANYS_SPACE_BACKEND_CORS_ORIGINS`. Non-secret shared values (`vercel_team_id`, JWT issuer/aud,
  TTLs, feature flags) come from the committed `environments/<env>/common.auto.tfvars`, **not** injected.
- **Outputs:** none. **Permissions:** `apply` job — `contents: read` (no `id-token`) (`:147-148`).
- **Consumer:** `kriegerdataforge-terraform`.

> **State:** `terraform init` in CI starts with empty local state — a remote backend must be configured
> in `environments/<env>/providers.tf` before running live (`:88-91`). The conftest gate is currently
> **advisory** (`continue-on-error: true`, `:245-246`).

```yaml
jobs:
  apply:
    uses: Needless2Say/kriegerdataforge-cicd/.github/workflows/cd-terraform.yml@main
    with:
      environment: ${{ inputs.environment }}   # dev | prod
      version: ${{ inputs.version }}
    secrets: inherit
```

### Release & version

#### `bump-version-check.yml`

Validates the PR branch's `VERSION` is **exactly one** valid semver increment ahead of `main`
(patch `X.Y.Z+1`, minor `X.Y+1.0`, or major `X+1.0.0`); any no-bump / skip-by-2 / downgrade / bad
format fails.

- **Inputs:** none. **Secrets:** none. **Outputs:** none.
- **Permissions:** `version-check` job — `contents: read` (`:31-32`). Checks out with `fetch-depth: 0`.
- **Consumers:** every versioned repo (called from `ci.yml`, typically `if: github.event_name == 'pull_request'`).

```yaml
jobs:
  version-check:
    if: github.event_name == 'pull_request'
    uses: Needless2Say/kriegerdataforge-cicd/.github/workflows/bump-version-check.yml@main
```

#### `create-github-release.yml`

Reads `VERSION`, creates a GitHub Release tagged `v{VERSION}` with auto-generated notes; **skips**
gracefully if the tag already exists (avoids the double-release race from two PRs on the same version).

- **Inputs:** none. **Secrets:** `GITHUB_TOKEN` (default). **Outputs:** none.
- **Permissions:** `release` job — `contents: write` (**the caller must grant this**) (`:35-36`).
- **Consumers:** every repo with a `release.yml` caller (fires on push to `main` touching `VERSION`).

```yaml
on:
  push: { branches: ["main"], paths: ["VERSION"] }
jobs:
  release:
    permissions: { contents: write }
    uses: Needless2Say/kriegerdataforge-cicd/.github/workflows/create-github-release.yml@main
```

### Next.js / Node CI

All four check out, set up Node (`cache: npm`), `npm ci`, then run a `make` target. None declares a
`permissions:` block (relies on the caller/default token). None reads secrets.

| Workflow | Inputs (all `type: string` unless noted) | Runs | Notes |
|---|---|---|---|
| `ci-nextjs-build.yml` | `node_version`=`"22"`; `upload_artifact` (boolean)=`false`; `artifact_name`=`"static-export"`; `artifact_path`=`"out/"`; `artifact_retention_days` (number)=`3` | `make ci-build` | uploads artifact only when `upload_artifact` (`:46-52`) |
| `ci-nextjs-lint-typecheck.yml` | `node_version`=`"22"` | `make ci-lint` + `make ci-typecheck` | |
| `ci-nextjs-tests.yml` | `node_version`=`"22"` | `make ci-unit-tests` (Jest) | |
| `ci-npm-audit.yml` | `node_version`=`"22"` | `make ci-npm-audit` | fails on high/critical prod-dep CVEs |

```yaml
jobs:
  build:
    uses: Needless2Say/kriegerdataforge-cicd/.github/workflows/ci-nextjs-build.yml@main
    with:
      upload_artifact: true          # optional
      artifact_name: static-export   # optional
```

### Python CI

The command-driven lanes let the caller override the install/run commands. `needs_sdk_auth: true`
(where present) configures a `git insteadOf` credential from **`GH_PACKAGES_PAT`** so `pip` can
resolve the private SDK — the only secret these lanes read (pass `secrets: inherit`). Several install
`libpq-dev` so source-built `psycopg2` compiles on the slim runner.

| Workflow | Inputs (`string` unless noted) → default | `needs_sdk_auth`? | Top-level `permissions` |
|---|---|---|---|
| `ci-python-format.yml` | `python_version`=`3.14`; `install_command`=`pip install -e ".[dev]"`; `format_command`=`python -m ruff format --check src/ tests/` | no | `contents: read` (`:4-5`) |
| `ci-python-lint.yml` | `python_version`=`3.14`; `install_command`=`pip install -r requirements.txt`; `lint_command`=`python -m ruff check .`; `needs_sdk_auth` (bool)=`false` | yes | `contents: read` |
| `ci-python-typecheck.yml` | + `typecheck_command`=`python -m mypy api/` (same shape as lint) | yes | `contents: read` |
| `ci-python-tests.yml` | + `test_command`=`python -m pytest unit_tests/ -q --tb=short` (fast, DB-free unit lane) | yes | `contents: read` |
| `ci-python-integration.yml` | `python_version`=`3.14`; `install_command`=`pip install -r requirements.txt`; `migrate_command`=`alembic upgrade head`; `seed_command`=`""`; `test_command`=`python -m pytest -m requires_postgres -q --tb=short`; `needs_sdk_auth` (bool)=`false` | yes | `contents: read` |
| `ci-python-security.yml` | `python_version`=`3.14`; `bandit_paths`=`api/ scripts/ vercel_api/`; `needs_sdk_auth` (bool)=`false` | yes | `contents: read` |
| `ci-vercel-compactor.yml` | `python_version`=`3.14` | no | *(none declared)* |

None of these declares outputs.

**`ci-python-integration.yml`** additionally provisions a `postgres:16` **service** (`kdf`/`kdf`/
`kdf_test`, health-checked) and exports the connection string under **two** names —
`DB_DATABASE_URL` (SDK/alembic, `env_prefix=DB_`) and `KDF_TEST_DATABASE_URL` (the pytest conftest
gate) — so a `-m requires_postgres` suite actually runs instead of silently green-skipping (finding
PL-166). App-specific schema (e.g. a `kdfusers` table) is provisioned by the caller's `seed_command`,
whose SQL lives in the caller's private repo (`:59-107`).

**`ci-python-security.yml`** runs two jobs: `bandit` SAST over `bandit_paths` and `pip-audit` (CVE
check) against `requirements.txt` — no SARIF upload, hence no `security-events: write`.

**`ci-vercel-compactor.yml`** runs `scripts/vercel_compactor.py --check --skip-import-check` — a dry
run that fails if regenerating `vercel_api/` from `api/` would change any file (blocks deploying a
stale Vercel artifact).

```yaml
# consumer ci.yml — integration lane as a job SEPARATE from the unit lane
jobs:
  integration:
    uses: Needless2Say/kriegerdataforge-cicd/.github/workflows/ci-python-integration.yml@main
    with:
      needs_sdk_auth: true
      seed_command: psql "$KDF_TEST_DATABASE_URL" -f tests/sql/seed_kdfusers.sql
    secrets: inherit
```

#### `ci-codeql.yml`

CodeQL SAST — init → autobuild → analyze → upload to the consumer's **Security ▸ Code scanning** tab.

| Input | Type | Default |
|---|---|---|
| `language` | string | `python` (`:31-34`) |
| `config_file` | string | `""` (`:35-38`) |
| `queries` | string | `security-extended,security-and-quality` (`:39-42`) |

- **Secrets:** none. **Outputs:** none.
- **Permissions:** `analyze` job — `actions: read`, `contents: read`, `security-events: write`
  (`:50-53`); the **caller must grant the same**.
- **Entitlement:** CodeQL runs only on **public** repos (free) or **private** repos with GitHub Code
  Security. Because most KDF repos are private, consumers gate the calling job on the `ENABLE_CODEQL`
  repo/org Actions **variable** — it stays skipped (green) until the entitlement exists.
- **Consumers:** `kriegerdataforge`, `kriegerdataforge-sdk`.

```yaml
jobs:
  codeql:
    if: ${{ vars.ENABLE_CODEQL == 'true' }}
    permissions: { actions: read, contents: read, security-events: write }
    uses: Needless2Say/kriegerdataforge-cicd/.github/workflows/ci-codeql.yml@main
    with:
      language: python
      config_file: ./.github/codeql/codeql-config.yml
```

### Security scanning

#### `secret-scan.yml`

Runs **gitleaks** over the consumer's working tree **and** git history to catch any committed secret.

| Input | Type | Default | Required |
|---|---|---|---|
| `fetch-depth` | number | `0` (full history) | no (`:20-25`) |

- **Secrets:** `GITHUB_TOKEN` (default). **Outputs:** none.
- **Permissions:** top-level **and** job — `contents: read`, `pull-requests: read` (`:27-29`, `:36-38`).
- **Consumers:** any repo (from `ci.yml`); no `GITLEAKS_LICENSE` needed for public/individual use.

```yaml
jobs:
  secret-scan:
    uses: Needless2Say/kriegerdataforge-cicd/.github/workflows/secret-scan.yml@main
```

### Internal owner gate (not for tenant `uses:`)

#### `_authorize-owner.yml`

A reusable fail-closed gate that other **privileged ops workflows in *this* repo** call as a job via
the local path `./.github/workflows/_authorize-owner.yml` and `needs:`. It compares
`github.triggering_actor` to `github.repository_owner` (case-insensitive) and fails closed on a
mismatch. The leading `_` + local-path usage signal it is **internal** — tenants do not call it.

- **Inputs:** none. **Secrets:** none.
- **Output:** `authorized` — `'true'` only when the actor is the repo owner (`:16-19`, job output
  `:28-29`).
- **Permissions:** top-level `contents: read` (`:21-22`).
- **Callers (this repo):** `ops-rotate-secrets.yml`, `ops-distribute-kit.yml`, `ops-setup-e2e.yml`,
  `distribute-kit.yml`, `distribute-gh-pat.yml`, `rotate-vercel-tokens.yml`.

```yaml
# consumed only within kriegerdataforge-cicd
jobs:
  authorize:
    uses: ./.github/workflows/_authorize-owner.yml
  privileged:
    needs: authorize
    if: needs.authorize.outputs.authorized == 'true'
```

---

## `run-e2e` composite action

`.github/actions/run-e2e/action.yml` — the reusable Tier-2 E2E engine, invoked as a **step** inside a
tenant repo's `.github/workflows/e2e.yml` job (composite action, not `workflow_call`). It is
**tenant-agnostic**: it reads the *caller's* `e2e/manifest.json` to learn which sibling repos the
journey needs, so it hardcodes no tenant list (ADR D-006/D-007).

**What it does** (`action.yml:25-197`): free disk → read the caller's manifest (`:38-63`) → mint a
GitHub App token scoped `contents:read` to just this journey's repos + the SDK (`:65-73`) → check out
cicd + the sibling repos into the sibling layout (`:75-103`) → set up Python/Node/Playwright →
`python e2e/ci_stack.py up --journey <journey>` → `npm test` (with a fail-closed "≥1 test ran" gate,
N2e, `:148-166`) → dump compose logs on failure → upload the Playwright report (1-day retention, GOOD-6)
→ tear the stack down.

**Inputs:**

| Input | Required | Default | Description |
|---|---|---|---|
| `journey` | **yes** | — | Journey to run; must match the caller's `e2e/manifest.json` `journey` (`:11-13`) |
| `app-id` | **yes** | — | GitHub App ID — pass `${{ secrets.KDF_APP_ID }}` (composite actions can't read secrets directly) (`:14-16`) |
| `app-private-key` | **yes** | — | GitHub App private key — pass `${{ secrets.KDF_APP_PRIVATE_KEY }}` (`:17-19`) |
| `cicd-ref` | no | `main` | Ref of `kriegerdataforge-cicd` to run the engine from (`:20-23`) |

- **Outputs:** none declared.
- **Permissions:** none in the action (a composite action inherits the calling **job's** permissions;
  the App token supplies its own scopes).
- **Secrets:** none read directly — the App credentials arrive as the `app-id` / `app-private-key`
  inputs; the minted App token doubles as `GH_PACKAGES_PAT` for the private-SDK clone during the image
  build (`:135`).

**Caller job** (verified against `action.yml` + ADR D-007 `docs/design/e2e-cijob-refactor.md`): the
job **checks itself out into a path equal to its own repo name** (sibling layout) — the action reads
`${repo}/e2e/manifest.json` — then `uses:` the action:

```yaml
# .github/workflows/e2e.yml in a tenant repo (dormant until RUN_E2E_GATE=true)
on:
  pull_request: { branches: [main] }
  workflow_dispatch:
jobs:
  e2e:
    if: github.event_name == 'workflow_dispatch' || vars.RUN_E2E_GATE == 'true'
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@<sha>
        with: { path: <this-repo-name> }   # MUST equal the repo name (sibling layout)
      - uses: Needless2Say/kriegerdataforge-cicd/.github/actions/run-e2e@main
        with:
          journey: fitness                 # must match e2e/manifest.json
          app-id: ${{ secrets.KDF_APP_ID }}
          app-private-key: ${{ secrets.KDF_APP_PRIVATE_KEY }}
```

The `KDF_APP_ID` / `KDF_APP_PRIVATE_KEY` secrets + the `RUN_E2E_GATE` variable are provisioned into a
journey repo by [`ops-setup-e2e.yml`](#repo-internal-event-triggered-workflows). See
[`E2E_TESTING.md`](../guides/E2E_TESTING.md) and [`e2e/README.md`](../../e2e/README.md).

---

## Permissions reference

Declared `permissions:` per reusable workflow (⊝ = not declared → caller/default token; job-level
shown where it differs from top-level):

| Workflow | Scope |
|---|---|
| `cd-nextjs-vercel.yml` | `authorize`: `contents:read`; `deploy`: `contents:read` + `id-token:write` |
| `cd-python-vercel.yml` | `authorize`: `contents:read`; `deploy`: `contents:read` + `id-token:write` |
| `cd-terraform.yml` | `authorize`: `contents:read`; `apply`: `contents:read` |
| `bump-version-check.yml` | job: `contents:read` |
| `create-github-release.yml` | job: `contents:write` (caller must grant) |
| `ci-codeql.yml` | job: `actions:read` + `contents:read` + `security-events:write` (caller must grant) |
| `ci-python-format` / `-lint` / `-typecheck` / `-tests` / `-integration` / `-security` | top-level: `contents:read` |
| `ci-nextjs-build` / `-lint-typecheck` / `-tests`, `ci-npm-audit`, `ci-vercel-compactor` | ⊝ none declared |
| `secret-scan.yml` | top-level + job: `contents:read` + `pull-requests:read` |
| `_authorize-owner.yml` | top-level: `contents:read` |

---

## Repo-internal event-triggered workflows

The remaining ten `.github/workflows/*.yml` (of 29 total: 19 `workflow_call` above + these 10) are
**not** `workflow_call`, so they cannot be `uses:`-d by a tenant. They run inside `kriegerdataforge-cicd` on schedules / issues / dispatch, and the ops ones are
owner-gated via [`_authorize-owner.yml`](#_authorize-owneryml). Listed here for completeness of the
`.github/workflows/` enumeration.

| Workflow | Trigger(s) | What it does | Owner gate |
|---|---|---|---|
| `ci.yml` | `pull_request` → `main` | actionlint + pytest (`scripts/tests/`) + calls `bump-version-check.yml` | n/a |
| `release.yml` | `push` `main`, `paths: [VERSION]` | calls `create-github-release.yml` (`contents:write`) | n/a |
| `issue-create-repo.yml` | `issues: labeled` (`new-repo`) | provisions a repo from a template; creates `prod`+`dev` Environments (owner reviewer, `main` only); branch protection; uses **repo-level** `CICD_PAT` (Administration/Contents/Environments/Secrets/Variables/Actions R-W + Members: Read) | inline owner check (PL-076) |
| `ops-rotate-secrets.yml` | `issues: labeled` (`ops:rotate-secrets`) | issue-form front-end for `rotate_secret.py` (`check`/`generate`/`paste`) | `_authorize-owner` |
| `ops-distribute-kit.yml` | `issues: labeled` (`ops:distribute-kit`) | issue-form front-end for `distribute_kit.py` (`check`/`distribute`) | `_authorize-owner` |
| `ops-setup-e2e.yml` | `issues: labeled` (`ops:setup-e2e`) | arms an E2E-journey repo: writes `RUN_E2E_GATE=false`, `USE_GITHUB_APP=true`, copies `KDF_APP_ID`/`KDF_APP_PRIVATE_KEY`; validates target against the fixed 6-repo allow-list | `_authorize-owner` |
| `distribute-kit.yml` | `workflow_dispatch` (`mode` check/distribute, `only`, `repos`) + weekly `schedule` (drift alarm) | runs `distribute_kit.py`; opens one sync PR per drifted repo | `_authorize-owner` (dispatch only) |
| `distribute-gh-pat.yml` | `workflow_dispatch` | distributes a staged `GH_PACKAGES_PAT_NEW` via `rotate_secret.py --mode paste` | `_authorize-owner` |
| `rotate-vercel-tokens.yml` | monthly `schedule` + `workflow_dispatch` | re-mints the shared `VERCEL_DEPLOYMENT_TOKEN` (`--mode generate`, 45-day life) and opens a PR stamping the new expiry | `_authorize-owner` (dispatch only) |
| `check-secret-expiry.yml` | weekly `schedule` (Mon 09:00 UTC) + `workflow_dispatch` | `rotate_secret.py --mode check --secrets all` (registry metadata only); keeps one dedup tracking issue (`ops:secret-expiry`) open/closed | n/a (`issues:write`) |

`GH_PACKAGES_PAT` distribution + Vercel/kit ops mint short-lived **GitHub App** tokens when
`vars.USE_GITHUB_APP == 'true'`, falling back to `CICD_PAT` (`distribute-gh-pat.yml:59-73`,
`rotate-vercel-tokens.yml:70-91`). See the GitHub-App migration ADR in
`docs/CHANGELOG_AND_DECISION_LOG.md`.

---

## Consumer repo summary

The authoritative allow-list is [`scripts/deployer_registry.json`](../../scripts/deployer_registry.json)
(`repo → environment → deployers`). Every repo below runs the
[Deployer authorization gate](#deployer-authorization-gate); the CD workflow column follows repo type.

| Consumer repo | Environments (registry) | CD workflow |
|---|---|---|
| `kriegerdataforge` | `dev`, `prod` | `cd-python-vercel.yml` |
| `kriegerdataforge-auth-ui` | `dev`, `prod` | `cd-nextjs-vercel.yml` |
| `fitness-app-frontend` | `dev`, `prod` | `cd-nextjs-vercel.yml` |
| `fitness-app-backend` | `dev`, `prod` | `cd-python-vercel.yml` |
| `tiffanys-space` | `dev`, `prod` | `cd-nextjs-vercel.yml` |
| `tiffanys-space-backend` | `dev`, `prod` | `cd-python-vercel.yml` |
| `kriegerdataforge-terraform` | `dev`, `prod` | `cd-terraform.yml` |
| `arthurs-portfolio` | `github-pages` | self-contained `nextjs.yml` → GitHub Pages (runs the gate) |
| `kriegerdataforge-template-nextjs` | `dev`, `prod` | `cd-nextjs-vercel.yml` (prepared-files placeholder) |
| `kriegerdataforge-template-fastapi` | `dev`, `prod` | `cd-python-vercel.yml` (prepared-files placeholder) |

---

## Related

- [`docs/guides/MANUAL_SETUP.md`](../guides/MANUAL_SETUP.md) — GitHub Environments, environment secrets, PAT/token creation, tenant onboarding.
- [`docs/guides/SECRET_ROTATION.md`](../guides/SECRET_ROTATION.md) — rotate a repo/environment secret via `rotate_secret.py` + `secret_registry.json`.
- [`docs/guides/E2E_TESTING.md`](../guides/E2E_TESTING.md) + [`e2e/README.md`](../../e2e/README.md) — the E2E engine model and local run.
- [`CONTRIBUTING.md`](../../CONTRIBUTING.md) — two-tier model + breaking-change governance for reusable-workflow interfaces.
- [`scripts/deployer_registry.json`](../../scripts/deployer_registry.json) · [`scripts/check_deployer.py`](../../scripts/check_deployer.py) — the deployer gate data + logic.
- [`docs/CHANGELOG_AND_DECISION_LOG.md`](../CHANGELOG_AND_DECISION_LOG.md) — ADRs (kit distribution D-001, GitHub-App migration, E2E decoupling D-006/D-007).
</content>
</invoke>
