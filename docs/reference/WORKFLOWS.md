# Reusable workflow catalog

Interface reference for every **reusable GitHub Actions workflow** (`on: workflow_call`) and the
**`run-e2e` composite action** in `kriegerdataforge-cicd`. Every tenant repo calls these live from
`@main`, so the inputs / secrets / outputs / permissions below are a **public contract**, changing
one is a breaking change candidate for all consumers (see `CONTRIBUTING.md` and AGENTS.md rules 4–6).

Enumerated strictly from `.github/workflows/*.yml` and `.github/actions/run-e2e/action.yml` as of
this writing. Each entry cites `file:line`.

- **Overview + consumption rules.** This section.
- **The contract.** [Reusable workflow catalog](#reusable-workflow-catalog) (per workflow inputs,
  secrets, outputs, permissions, caller snippet) + [`run-e2e` composite action](#run-e2e-composite-action).
- **Deploy gate / approval model.** [Deployment model](#deployment-model) + [Deployer authorization gate](#deployer-authorization-gate) + [PROD gate](#prod-gate).
- **Live vs. not-`uses:`-able.** [Repo-internal event-triggered workflows](#repo-internal-event-triggered-workflows) (the ops / rotation / provisioning workflows that are **not** `workflow_call`).

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
   runtime. They are supplied by the caller's repo/environment, not declared as workflow inputs.
2. **Third party actions are SHA pinned** (`actions/checkout@9c091bb…` = v7.0.0, `setup-python@ece7cb06…`
   = v6, `setup-node@48b55a01…` = v6, etc.) per AGENTS.md rule 2. Bump via Dependabot.

> **Ref pinning note.** All examples use `@main` (the live contract), matching how tenants call today.
> A consumer that wants change isolation may pin `@vX.Y.Z` instead. This repo publishes tags via
> [`create-github-release.yml`](#create-github-releaseyml).

---

## Deployment model

All deploys are **manual** (`workflow_dispatch` in the consumer, which then calls the reusable CD
workflow). There are no push triggered deploys, Vercel git auto deploy is off. Flow:

1. A deployer clicks **Run workflow** in the consumer repo, choosing `environment` (+ `version`).
2. The reusable CD workflow's **`authorize`** job runs *first* (before any approval or secret load)
   and fails closed if the actor is not an approved deployer. See
   [Deployer authorization gate](#deployer-authorization-gate).
3. The two Vercel deploys then run **`verify-prod-gate`**, which asks GitHub for a successful run of
   the consumer's own PROD Gate workflow for the release, and fails closed on `prod` when there is
   none. See [PROD gate](#prod-gate).
4. The `deploy`/`apply` job declares `environment: ${{ inputs.environment }}`, which loads that
   environment's secrets and pauses for approval only where the environment configures a
   required reviewer. Measured on 2026-09-17, no environment in any repo carries a reviewer or a
   branch policy, so the deployer authorization gate is the control in front of the token.
5. The deploy runs. A Next.js deploy pulls the project, builds once and ships the prebuilt
   output. A Python deploy deploys without the domains, migrates, smokes the new deployment and
   only then promotes it (D-016).

### Environment approval model

The model below is the intended one. The reviewers it names are not configured anywhere today
(measured 2026-09-17), which is why the deployer authorization gate exists. The GitHub
Environments and their intended required reviewers are provisioned by
[`issue-create-repo.yml:168-223`](../../.github/workflows/issue-create-repo.yml) and documented in
`MANUAL_SETUP.md` Phase 4 (the owner's, in `kriegerdataforge-context/ops/`). The **only** environment names in use, and the
keys the deployer registry is keyed on, are:

| GitHub Environment | Required reviewer(s) | Deployment branch policy |
|---|---|---|
| `dev` | Owner (provisioned owner only, a collaborator may be **added manually** to the `dev` required reviewers list, `issue-create-repo.yml:198-223`, completion checklist line 277) | `main` only |
| `prod` | Owner only (`issue-create-repo.yml:168-196`) | `main` only |
| `github-pages` | Owner (`arthurs-portfolio` and `kriegerdataforge-portfolio`, self contained Pages deploys, `MANUAL_SETUP.md` Phase 4 "For arthurs-portfolio") | GitHub Pages (no `dev`/`prod`) |

> **There is no `infra` / `infrastructure` / `development` / `production` environment.** The Terraform
> CD workflow deploys to `dev`/`prod` like the others (`cd-terraform.yml:99`, `deployer_registry.json`
> `kriegerdataforge-terraform` → `{dev, prod}`, `MANUAL_SETUP.md` Phase 4 "For repo 6"). Use the short
> names `dev` / `prod` / `github-pages` exactly (AGENTS.md rule 9).
>
> The `environment` input descriptions of all three deploys read `("dev" or "prod")`, the value a
> caller passes to match the registry keys and the real GitHub Environments.

#### Key security property

`VERCEL_DEPLOYMENT_TOKEN`, `DB_DATABASE_URL`, the RSA PEMs, and every other
deploy credential live only in GitHub repo/Environment secrets. Never in `.env`, never echoed
(deploy steps log only the token's trimmed length, the `Prepare Vercel token` step). Since D-016 the
trimmed token is a masked step output read by the steps that call Vercel's API alone, never a
`$GITHUB_ENV` value every later step would inherit.

---

## Deployer authorization gate

GitHub cannot restrict **who** may `workflow_dispatch` a run. Anyone with write access can. The
Environment gate covers `prod` (owner only reviewer), but on `dev` a collaborator is also an allowed
reviewer and could self-approve. So every reusable CD workflow runs a **deployer authorization gate**
as its first job.

**How it works:**

1. `cd-nextjs-vercel.yml`, `cd-python-vercel.yml`, and `cd-terraform.yml` each start with an
   `authorize` job that the `deploy`/`apply` job `needs:`. (`arthurs-portfolio`'s self contained
   `cd.yml` runs the same gate before its build.)
2. `authorize` sparse checks out this repo's `scripts/` and runs
   [`scripts/check_deployer.py`](../../scripts/check_deployer.py) (`cd-nextjs-vercel.yml:47-70`).
3. The script matches `github.triggering_actor` (whoever clicked **Run workflow**) against
   [`scripts/deployer_registry.json`](../../scripts/deployer_registry.json), keyed by
   `github.repository` and the target `environment`. Matching is case-insensitive.
4. **Not authorized → the job fails → the deploy job never runs.** Because `authorize` has **no
   `environment:`**, it runs *before* the approval is even requested. An unauthorized dispatch fails
   fast, no approval notification, no secrets loaded (fail closed).

**Registry shape** (`scripts/deployer_registry.json`), `repo → environment → [usernames]`:

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

### Repo access for the gate

The `authorize` job checks out `kriegerdataforge-cicd` with the default
`github.token`. Because this repo is **public**, that built in token clones it. If cicd ever goes
private (post org move), this checkout needs a read only token, tracked in
`KDF docs/engineering/GITHUB_FUTURE_ENHANCEMENTS.md`.

`check_deployer.py` is stdlib only and unit tested in `scripts/tests/test_check_deployer.py`.

---

## PROD gate

A release reaches `prod` only after the consumer's **PROD Gate** passed for it (D-027). The gate is the
consumer's `prod-gate.yml`, dispatched with the release version. It runs the repo's `ci.yml`, its
integration, system and mutation suites and its E2E journey on the release tag, and its last job, which
needs every lane and passes only when each passed, is named `PROD Gate v<version>`. The two Vercel
deploys run a **`verify-prod-gate`** job between `authorize` and `deploy`, the same shape as the deployer
gate, a sparse checkout of this repo's `scripts/` and
[`scripts/check_prod_gate.py`](../../scripts/check_prod_gate.py). What the gate runs per stack is in
[`PROD_GATE.md`](../guides/PROD_GATE.md).

**How it works:**

1. The script resolves the tag `v<version>` in the consumer repo to its commit, following an
   annotated tag to the commit it names. The deploy job checks out that same tag.
2. It lists the runs of the consumer's `prod-gate.yml` whose `head_sha` is that commit and whose
   status is `success`, and takes the newest one whose passed job is named `PROD Gate v<version>`.
   Failing that, it lists the workflow's successful dispatched runs, newest first, and takes the
   first that ran on the repository's default branch and whose passed job has that name. The name is
   asked of every run, a run for another version on the same commit tested another tag. A gate
   dispatched on another branch does not count, that branch's workflow may have dropped a lane. A run
   of the E2E workflow is never read, the journey is one lane (D-027 supersedes D-021 and D-024 here).
3. **On `prod`, none found means the job fails and the deploy never runs**, with the reason on the
   line and in the step summary, no tag, no workflow, or no green run for the release, and what to
   do, dispatch **Actions, PROD Gate, Run workflow** on the default branch with the version, and
   deploy again once it is green. When one is found, the step summary records which run tested the
   release, how it was found, its number, time and link, the way the deployer gate records who
   deployed.
4. **On `dev` the lookup runs and reports, and never denies.** DEV is the soak that comes before
   the gate is dispatched for the release.

The runs listing needs `actions: read`, which a called workflow can only hold when the caller grants
it, so every consumer's `cd.yml` gives its deploy job `contents: read`, `id-token: write` and
`actions: read`. A caller that omits it fails at startup with GitHub's own permission message.

`check_prod_gate.py` is stdlib only and unit tested in `scripts/tests/test_check_prod_gate.py`, against
a map of the API answers. The job is pinned by `scripts/tests/test_workflow_contracts.py`, and the six
consumers' gates by `scripts/tests/test_consumer_release_workflows.py`, which runs each gate's verdict
on every result GitHub can write.

---

## Reusable workflow catalog

24 workflows are `on: workflow_call`. None declares an explicit `secrets:` block, so callers pass
`secrets: inherit`. Permissions are stated as declared in each file (top level and/or per job), an
undeclared scope means the workflow relies on the caller's / default token.

### Deployment (CD)

These three share the [Deployer authorization gate](#deployer-authorization-gate) (`authorize` job:
`permissions: contents: read`). The two Vercel ones also pin the Vercel CLI to `vercel@48.0.0`. Every one has a **required
`version`** input. The deploy job checks out `ref: v${{ inputs.version }}` (i.e. pass `1.2.0`, the
workflow prepends `v`), enabling rollback to an older tag.

#### `cd-nextjs-vercel.yml`

Deploy a Next.js app to a Vercel project (`vercel pull` → `vercel build`, the one install → `vercel deploy
--prebuilt --prod`). The deploy token reaches the pull and the deploy steps alone (D-016).

| Input | Type | Default | Required |
|---|---|---|---|
| `environment` | string | — | **yes.** `dev` or `prod` (`:32-35`) |
| `version` | string | — | **yes.** Tag to deploy, e.g. `1.2.0` (`:36-39`) |

- **Secrets read (via `inherit`):** `VERCEL_DEPLOYMENT_TOKEN` (repo level), `VERCEL_ORG_ID`,
  `VERCEL_PROJECT_ID` (per environment, job fails fast if unset, `:101-113`), optional
  `GH_NPM_TOKEN` (classic `read:packages`, exported to `npm ci` for private GH Packages deps;
  Vercel's remote build reads its own project env var instead).
- **Outputs.** None.
- **Permissions.** `deploy` job. `contents: read` (D-016 dropped `id-token: write`, the pinned CLI never
  requests a GitHub OIDC token).
- **Consumers.** `fitness-app-frontend`, `tiffanys-space` (and `kriegerdataforge-auth-ui`,
  `kriegerdataforge-template-nextjs` per the registry). `arthurs-portfolio` deploys self contained to
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

Deploy a FastAPI backend to Vercel. Install deps (with private SDK git auth) → compact `api/` into
`vercel_api/` via `scripts/vercel_compactor.py` → `vercel deploy --prod --skip-domain` (the release that
is serving keeps serving) → optional Alembic migration, the revision in place recorded first → smoke the
new deployment's `/healthz`, undoing the migration when it fails → `vercel promote` (hub register row 83,
D-016). An optional `VERCEL_AUTOMATION_BYPASS_SECRET` environment secret rides on the smoke when Vercel's
deployment protection covers the deployment URL, which answers a plain request with a 302 to vercel.com's sign
in or a 401, and the smoke names that case, as it names Vercel's error code on a 5xx and points at the
deployment's runtime logs. The revision is read from alembic's verbose `Rev:` line, since a repo's
`alembic/env.py` may print to stdout, and the migrate and undo steps declare `ENVIRONMENT` (D-018).

| Input | Type | Default | Required |
|---|---|---|---|
| `environment` | string | — | **yes.** `dev` or `prod` (`:38-42`) |
| `run_migrations` | **string** | `'true'` | no. Gate is `if: inputs.run_migrations == 'true'`. Pass the **string** `'true'`/`'false'` (`:43-47`, `:169`, `:175`) |
| `version` | string | — | **yes.** Tag to deploy (`:48-51`) |

- **Secrets read (via `inherit`):** `VERCEL_DEPLOYMENT_TOKEN`, `GH_PACKAGES_PAT` (private SDK clone,
  `:112-115`), `VERCEL_ORG_ID`, `VERCEL_PROJECT_ID`, `DB_DATABASE_URL` (only when `run_migrations`,
  `:178`).
- **Outputs.** None.
- **Permissions.** `deploy` job. `contents: read` (D-016 dropped `id-token: write`).
- **Consumers.** `kriegerdataforge` (hub). Registry also lists `fitness-app-backend`,
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
`-chdir=environments/${{ inputs.environment }}` (directory per environment, no workspaces).

| Input | Type | Default | Required |
|---|---|---|---|
| `environment` | string | — | **yes.** `dev` or `prod`. Selects `environments/<env>/` **and** the Environment gate (`:98-101`) |
| `version` | string | — | **yes.** Tag to deploy. Note rolling back reverts config, not state (`:102-105`) |

- **Secrets read (via `inherit`).** Injected as `TF_VAR_*` env (`:153-201`):

  | Secret | → Terraform var |
  |---|---|
  | `VERCEL_DEPLOYMENT_TOKEN` | `vercel_api_token` |
  | `BACKEND_AUTH_PRIVATE_KEY` / `_PUBLIC_KEY` / `FRONTEND_AUTH_PUBLIC_KEY` | `backend_auth_private_key` / `_public_key` / `frontend_auth_public_key` |
  | `BACKEND_AUTH_ADMIN_EMAIL` / `_PASSWORD` | `backend_auth_admin_email` / `_password` |
  | `KDF_AUTH_DB_DATABASE_URL`, `FITNESS_APP_BACKEND_DB_DATABASE_URL`, `TIFFANYS_SPACE_BACKEND_DB_DATABASE_URL` | matching `*_db_database_url` |
  | `FITNESS_APP_SERVICE_KEY`, `TIFFANYS_SPACE_SERVICE_KEY`, `KDF_AUTH_UI_SERVICE_KEY` | matching `*_service_key` |
  | `FITNESS_OIDC_CLIENT_SECRET`, `TIFFANYS_SPACE_OIDC_CLIENT_SECRET` | matching `*_oidc_client_secret` |
  | *Optional.* `TIFFANYS_SPACE_CRON_SECRET`, `BACKEND_STRIPE_SECRET_KEY`, `BACKEND_STRIPE_WEBHOOK_SECRET`, `TF_TOKEN_APP_TERRAFORM_IO` | matching vars / TF Cloud auth |

- **Non-secret vars read (`vars.*` → `TF_VAR_*`, `:177-199`):** `BACKEND_URL`,
  `FITNESS_APP_BACKEND_URL`, `TIFFANYS_SPACE_BACKEND_URL`, `KDF_AUTH_SERVICE_PROJECT_NAME`,
  `FITNESS_APP_PROJECT_NAME`, `FITNESS_APP_BACKEND_PROJECT_NAME`, `TIFFANYS_SPACE_PROJECT_NAME`,
  `TIFFANYS_SPACE_BACKEND_PROJECT_NAME`, `KDF_AUTH_UI_URL`, `FITNESS_OIDC_CLIENT_ID`,
  `FITNESS_OIDC_REDIRECT_URI`, `TIFFANYS_SPACE_OIDC_CLIENT_ID`, `TIFFANYS_SPACE_OIDC_REDIRECT_URI`,
  optional `KDF_AUTH_CORS_ORIGINS`, `FITNESS_APP_BACKEND_CORS_ORIGINS`,
  `TIFFANYS_SPACE_BACKEND_CORS_ORIGINS`. Non-secret shared values (`vercel_team_id`, JWT issuer/aud,
  TTLs, feature flags) come from the committed `environments/<env>/common.auto.tfvars`, **not** injected.
- **Outputs.** None. **Permissions.** `apply` job. `contents: read` (no `id-token`) (`:147-148`).
- **Consumer.** `kriegerdataforge-terraform`.

> **State.** `terraform init` in CI starts with empty local state. A remote backend must be configured
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
(patch `X.Y.Z+1`, minor `X.Y+1.0`, or major `X+1.0.0`). Any no bump / skip-by-2 / downgrade / bad
format fails.

- **Inputs.** None. **Secrets.** None. **Outputs.** None.
- **Permissions.** `version-check` job. `contents: read` (`:31-32`). Checks out with `fetch-depth: 0`.
- **Consumers.** Every versioned repo (called from `ci.yml`, typically `if: github.event_name == 'pull_request'`).

```yaml
jobs:
  version-check:
    if: github.event_name == 'pull_request'
    uses: Needless2Say/kriegerdataforge-cicd/.github/workflows/bump-version-check.yml@main
```

#### `create-github-release.yml`

Reads `VERSION`, creates a GitHub Release tagged `v{VERSION}` with auto generated notes, **skips**
gracefully if the tag already exists (avoids the double release race from two PRs on the same version).
The tag goes on the commit `VERSION` was read from, the triggering commit, passed as `--target`
(D-038). Without it GitHub tags the default branch's tip when the command runs, and a second merge
landing in between would take the first one's tag.

- **Inputs.** None. **Secrets.** `GITHUB_TOKEN` (default). **Outputs.** None.
- **Permissions.** `release` job. `contents: write` (**the caller must grant this**) (`:35-36`).
- **Consumers.** Every repo with a `release.yml` caller (fires on push to `main` touching `VERSION`).

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
`permissions:` block (relies on the caller/default token). The only secret they read (via
`secrets: inherit`, optional) is **`GH_NPM_TOKEN`**. A CLASSIC `read:packages` PAT exported to the
`npm ci` step for consumers whose committed `.npmrc` routes `@needless2say/*` to private GitHub
Packages (reports ecosystem W3.5). Empty/absent for token less consumers, which changes nothing.
There is deliberately **no App token path here**. GH Packages rejects fine grained PATs and GitHub
App installation tokens (classic PAT / `GITHUB_TOKEN` only, see `SECRET_ROTATION.md` §8.2a).

| Workflow | Inputs (all `type: string` unless noted) | Runs | Notes |
|---|---|---|---|
| `ci-nextjs-build.yml` | `node_version`=`"22"`, `upload_artifact` (boolean)=`false`, `artifact_name`=`"static-export"`, `artifact_path`=`"out/"`, `artifact_retention_days` (number)=`3` | `make ci-build` | uploads artifact only when `upload_artifact` (`:46-52`) |
| `ci-nextjs-lint-typecheck.yml` | `node_version`=`"22"` | `make ci-lint` + `make ci-typecheck` | |
| `ci-nextjs-tests.yml` | `node_version`=`"24"`, `ref`=`""` (the ref to check out, a release dispatch passes the tag, D-024) | `make ci-unit-tests` (Jest) | |
| `ci-nextjs-integration.yml` | `node_version`=`"24"`, `ref`=`""` (as the unit lane's) | `make ci-integration-tests` (Jest, the caller's `src/__tests__/integration/` tree, no coverage), a release dispatch's lane (D-025) | `contents: read` |
| `ci-nextjs-mutation.yml` | `lanes` (**required**, a JSON list of the caller's tables), `node_version`=`"24"`, `ref`=`""` | `node mutation_tests/run.mjs --lane <lane>`, one job per lane, a survivor fails its lane, the PROD Gate's lane (D-027) | `contents: read`, the checkout keeps no credential |
| `ci-npm-audit.yml` | `node_version`=`"22"` | `make ci-npm-audit` | fails on high/critical prod dep CVEs |

```yaml
jobs:
  build:
    uses: Needless2Say/kriegerdataforge-cicd/.github/workflows/ci-nextjs-build.yml@main
    with:
      upload_artifact: true          # optional
      artifact_name: static-export   # optional
```

### Python CI

Every lane in this section and the next, and `secret-scan.yml`, takes `ref`=`""`, the ref to check out. Empty
is the caller run's own ref. A consumer's `ci.yml` hands each lane the `ref` it was called with, so a release
dispatch judges the release tag in every lane (D-026).

The command driven lanes let the caller override the install/run commands. `needs_sdk_auth: true`
(where present) lets `pip` resolve the owner's private packages (`kdf_sdk`, `kdf_reports`, `kdf_fmt`)
**without the job that runs the caller's code ever naming a secret** (D-035). The lane splits in two.
Its **fetch job** (`Fetch private packages`) is the only job that names a secret. It checks out the
caller with no credential kept, runs nothing of it, reads the `requirement_files` as text for
`git+https://github.com/Needless2Say/<repo>.git@<tag or full commit id>` pins, mints the token for
exactly those repos, clones each pinned ref with its full history into a bare mirror, and uploads
the mirrors as one artifact kept for a day. A plain https link to a repo's page, as a pyproject's
`[project.urls]` holds, is not a pin and passes, while any other form pip could install (git+,
git@ or ssh:// URLs, archive or wheel links, a pip option line) fails the plan. The **install job**
keeps its id and its name, so every ruleset's required check is unchanged, names no secret, runs on
`always()`, and its first step ends it failed when the run was cancelled or, with `needs_sdk_auth`,
unless the fetch succeeded (a skipped required job counts as passing). It checks the caller out
with no credential kept, then downloads the mirrors and hands git one
`url.file://<mirror>.insteadOf https://github.com/Needless2Say/<repo>.git` rewrite per repo
through `GIT_CONFIG_COUNT`, `KEY_n` and `VALUE_n` in the job's environment. Without
`needs_sdk_auth` the lane is one job as before. The token is **App token first** (reports ecosystem
epic W2.5): when the calling repo sets the `USE_GITHUB_APP` variable and holds the distributed
`KDF_APP_ID` / `KDF_APP_PRIVATE_KEY` secrets (see
[`ops-distribute-app-secrets.yml`](#repo-internal-event-triggered-workflows)), the fetch job mints a
short lived installation token (`contents: read` only, for the repos it clones, auto revoked at job
end). Otherwise it falls back to the long lived **`GH_PACKAGES_PAT`**. Secrets these lanes read via
`secrets: inherit`. `GH_PACKAGES_PAT`, plus `KDF_APP_ID` / `KDF_APP_PRIVATE_KEY` when the caller
opted in. The fetch mirrors only the allowlisted repos (the three packages, the three backends, and
this repo as the proof's public stand in), and a **public** calling repo may mirror only a public
one, its run artifacts being readable by anyone. The four inputs every split lane shares are
`requirement_files` (default `requirements.txt requirements.in requirements-dev.txt requirements-dev.in
requirements-test.txt requirements-test.in pyproject.toml`, a missing one skipped, the `.in` names since D-041),
`extra_repos` (`repo@ref` items, a branch allowed here alone
and resolved to its commit), `scan_files` (`repo:path` items read inside an extra repo's mirror) and
`token_repositories` (the narrower fence per call, empty is every repo the fetch clones). The style
lane splits the same way since D-038, because `python -m` put the checkout first on the import path,
so a pull request's `pip.py` or `kdf_fmt/` ran where the secret was, and `check_command` is the
caller's own text. Its fetch job always runs, reads no requirement file, mirrors only
`kriegerdataforge-fmt` at `kdf_fmt_ref` and mints for that repo alone, and its check job keeps the
name `Style (kdf-fmt)`, names no secret and installs in isolated mode (`python -I`). Isolated mode
covers the install and the default command only, a caller's own command runs in a job with no
secret to reach. A public caller cannot mirror the private formatter, so every public repo, this
one included, calls `ci-kdf-fmt-public.yml`, one job minted for `kriegerdataforge-fmt` alone with
its command fixed and isolated, an optional `baseline` file name, and a first step that fails when
no token reaches it (D-044, which retired this repo's own `ci-kdf-fmt-self.yml` of D-038).
Several lanes install `libpq-dev` so source built `psycopg2` compiles on the slim
runner.

| Workflow | Inputs (`string` unless noted) → default | `needs_sdk_auth`? | Top level `permissions` |
|---|---|---|---|
| `ci-python-format.yml` | `python_version`=`3.14`, `install_command`=`pip install -e ".[dev]"`, `format_command`=`python -m ruff format --check src/ tests/` | no | `contents: read` (`:4-5`) |
| `ci-python-kdf-fmt.yml` | `python_version`=`3.14`, `kdf_fmt_ref` (**required**, pin a `vX.Y.Z` tag or a full commit id), `check_command`=`python -I -m kdf_fmt.cli check --no-cache`, `ref`=`""` | always, two jobs (D-038), the fetch mints for `kriegerdataforge-fmt` alone (App token first, `GH_PACKAGES_PAT` fallback, callers pass `secrets: inherit`), private callers only | `contents: read` |
| `ci-kdf-fmt-public.yml` | `python_version`=`3.14`, `kdf_fmt_ref` (**required**), `baseline`=`""` (a plain file name) | always, one job (D-044), mints for `kriegerdataforge-fmt` alone (App token first, `GH_PACKAGES_PAT` fallback, `secrets: inherit`), fails when no token reaches it, PUBLIC callers, no artifact | `contents: read` |
| `ci-python-lint.yml` | `python_version`=`3.14`, `install_command`=`pip install -r requirements.txt`, `lint_command`=`python -m ruff check .`, `needs_sdk_auth` (bool)=`false` | yes | `contents: read` |
| `ci-python-typecheck.yml` | + `typecheck_command`=`python -m mypy api/` (same shape as lint) | yes | `contents: read` |
| `ci-python-tests.yml` | + `test_command`=`python -m pytest unit_tests/ -q --tb=short` (fast, DB free unit lane), `ref`=`""` (the ref to check out, a release dispatch passes the tag, D-024) | yes | `contents: read` |
| `ci-python-integration.yml` | `python_version`=`3.14`, `install_command`=`pip install -r requirements.txt`, `migrate_command`=`alembic upgrade head`, `seed_command`=`""`, `test_command`=`python -m pytest -m requires_postgres -q --tb=short`, `needs_sdk_auth` (bool)=`false`, `ref`=`""` (as the unit lane's) | yes | `contents: read` |
| `ci-python-system.yml` | `python_version`=`3.14`, `install_command`=`pip install -r requirements.txt`, `test_command`=`python -m pytest system_tests/ -q --tb=short -p no:warnings -ra`, `needs_sdk_auth` (bool)=`false`, `ref`=`""`, the PROD Gate's lane (D-027) | yes | `contents: read` |
| `ci-python-mutation.yml` | `lanes` (**required**, a JSON list of the caller's tables), `python_version`=`3.14`, `install_command`=`pip install -r requirements.txt`, `needs_sdk_auth` (bool)=`false`, `ref`=`""`, one job per lane, the PROD Gate's lane (D-027) | yes | `contents: read` |
| `ci-python-security.yml` | `python_version`=`3.14`, `bandit_paths`=`api/ scripts/ vercel_api/`, `needs_sdk_auth` (bool)=`false` | yes | `contents: read` |
| `ci-vercel-compactor.yml` | `python_version`=`3.14` | no | *(none declared)* |

None of these declares outputs.

**`fetch-private-packages.yml`** is the fetch job alone, for a caller that runs its own install and
test job (the kdf-sdk canary, which mirrors a backend at its branch through `extra_repos`, reads its
requirement files inside the mirror through `scan_files`, and fences the token with
`token_repositories`). Inputs `ref`, `requirement_files`, `extra_repos`, `scan_files`,
`token_repositories` as above. Outputs `artifact` (holding `kdf-private.tar`, with
`kdf-private/mirrors/<repo>.git` and `kdf-private/manifest.json` of repo, ref, kind and commit) and
`token_sha256` (the sha256 of the token the fetch used, for a proof that a later job holds no copy).
The caller downloads the artifact, untars it under `$RUNNER_TEMP` and hands git the same rewrites the
lanes do. A caller that calls it in a matrix gets one output, the last leg's, and an artifact name
that is new per run, so no leg finds its own, so wrap one leg, the fetch and the job that uses it, in
a reusable workflow of the caller's own and call that in the matrix. The fetch job in it and in each
lane is one template, `scripts/fetch_private_job.template.yml`, written by
`scripts/render_fetch_job.py`, and a test fails when a copy differs.

**`ci-python-integration.yml`** additionally provisions a `postgres:16` **service** (`kdf`/`kdf`/
`kdf_test`, health checked) and exports the connection string under **two** names,
`DB_DATABASE_URL` (SDK/alembic, `env_prefix=DB_`) and `KDF_TEST_DATABASE_URL` (the pytest conftest
gate), so a `-m requires_postgres` suite actually runs instead of silently green skipping (finding
PL-166). It declares `ENVIRONMENT: local`, since a stack started in Actions is local by the owner's
definition (2026-09-30) and never the DEV account. App specific schema (e.g. a `kdfusers` table) is
provisioned by the caller's `seed_command`, whose SQL lives in the caller's private repo (`:68-91`).

**`ci-python-system.yml`** provisions a `postgres:16` service whose database is `kdf_system` and
exports `KDF_SYSTEM_DATABASE_URL`. The suite's harness builds each server's environment from nothing, so
the job hands it the database alone. **`ci-python-mutation.yml`** provisions one too, `kdf_mutation`, makes
a second database `kdf_mutation_sys` beside it, and exports both `KDF_TEST_DATABASE_URL` and
`KDF_SYSTEM_DATABASE_URL`, a lane may hold mutants of all three suites and the system suite commits rows
the integration suite must never read. It runs the shared engine the scripts sync vendors,
`scripts/kdf_scripts/mutation_runner.py` (D-040), and nothing else, a caller's own runner left behind is never run,
and a caller without the engine fails naming the scripts sync (D-042).

**`ci-python-security.yml`** runs two jobs. `bandit` SAST over `bandit_paths` and `pip-audit` (CVE
check) against `requirements.txt`. No SARIF upload, hence no `security-events: write`.

**`ci-vercel-compactor.yml`** runs `scripts/vercel_compactor.py --check --skip-import-check`, a dry
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

CodeQL SAST. Init → autobuild → analyze → upload to the consumer's **Security ▸ Code scanning** tab.

| Input | Type | Default |
|---|---|---|
| `language` | string | `python` (`:31-34`) |
| `config_file` | string | `""` (`:35-38`) |
| `queries` | string | `security-extended,security-and-quality` (`:39-42`) |

- **Secrets.** None. **Outputs.** None.
- **Permissions.** `analyze` job. `actions: read`, `contents: read`, `security-events: write`
  (`:50-53`). The **caller must grant the same**.
- **Entitlement.** CodeQL runs only on **public** repos (free) or **private** repos with GitHub Code
  Security. Because most KDF repos are private, consumers gate the calling job on the `ENABLE_CODEQL`
  repo/org Actions **variable**. It stays skipped (green) until the entitlement exists.
- **Consumers.** `kriegerdataforge`, `kriegerdataforge-sdk`.

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
| `ref` | string | `""`, the caller run's own ref | no (`:21-24`) |
| `fetch-depth` | number | `0` (full history) | no (`:25-29`) |

- **Secrets.** `GITHUB_TOKEN` (default). **Outputs.** None.
- **Permissions.** Top level **and** job. `contents: read`, `pull-requests: read` (`:31-33`, `:40-42`). The caller
  grants both at its top level, or the whole run fails at startup and shows no check at all.
- **Consumers.** Every repo, from its `ci.yml`, and since 2026-09-29 this repo too, as a local reference so a change to
  the lane is exercised by the pull request that makes it. No `GITLEAKS_LICENSE` needed for public/individual use. On
  a pull request the action scans the commits the pull request adds, not the whole history.
- **gitleaks version.** Pinned by `GITLEAKS_VERSION: "8.30.1"`. Left unset the action installs 8.24.3, which ignores a
  consumer's `[[allowlists]]` array without a word (the array arrived in 8.25.0). Raise the pin deliberately, after
  scanning every consumer's full history on the new version with its own `.gitleaks.toml`.

```yaml
jobs:
  secret-scan:
    uses: Needless2Say/kriegerdataforge-cicd/.github/workflows/secret-scan.yml@main
```

### Ecosystem watch, for a private caller alone

#### `ecosystem-watch.yml`

The weekly ecosystem watch (D-049). A private repo's scheduled workflow calls it, `kriegerdataforge-context` today,
and nothing in this public repo starts it, since it reads the open Dependabot alerts of private repos and a run here
would publish them. It mints a read only token of the KDF GitHub App (contents, vulnerability alerts, checks and
actions, all read), runs `scripts/ecosystem_watch.py collect` from cicd's `main`, keeps the JSON snapshot
(`kdf-ecosystem-watch/1`) as a 30 day artifact for a later admin dashboard, and keeps one rolling issue labelled
`ops:ecosystem-watch` in the caller, written with the caller's own token. The body is rewritten every run, a comment
is added only when something is new, posted before the body that remembers it so a failed comment is posted by the
next run, and the issue closes itself when everything is clear and reopens on the next finding. The log carries
counts. Its first step refuses a caller the API does not report private.

- **Reads.** Open Dependabot alerts, every page, each pin of a package built from one of the owner's repos against
  that repo's latest `vX.Y.Z` tag (a commit pin is matched to its tag), each repo's kit version and vendored scripts
  against cicd's, by blob sha, and the deprecation notices on the latest completed run of each active workflow. What
  it cannot read, and a pin it cannot judge, keeps the issue open. A notice seen only on runs older than 60 days is
  listed with its run's date and keeps nothing open, since only a new run of that workflow can clear it.
- **Secrets.** `app_id` and `app_private_key`, passed by name, never `inherit`.
- **Permissions.** `contents: read`, `issues: write`. The App needs Dependabot alerts, Checks, Actions and Contents,
  read only, approved on its installation.

```yaml
# a private repo's .github/workflows/ecosystem-watch.yml
on:
  schedule:
    - cron: "0 10 * * 1"
  workflow_dispatch:
permissions:
  contents: read
  issues: write
jobs:
  watch:
    uses: Needless2Say/kriegerdataforge-cicd/.github/workflows/ecosystem-watch.yml@main
    secrets:
      app_id: ${{ secrets.KDF_APP_ID }}
      app_private_key: ${{ secrets.KDF_APP_PRIVATE_KEY }}
```

---

### Internal owner gate (not for tenant `uses:`)

#### `_authorize-owner.yml`

A reusable fail closed gate that other **privileged ops workflows in *this* repo** call as a job via
the local path `./.github/workflows/_authorize-owner.yml` and `needs:`. It compares
`github.triggering_actor` to `github.repository_owner` (case insensitive) and fails closed on a
mismatch. The leading `_` + local path usage signal it is **internal**. Tenants do not call it.

- **Inputs.** None. **Secrets.** None.
- **Output.** `authorized`. `'true'` only when the actor is the repo owner (`:16-19`, job output
  `:28-29`).
- **Permissions.** Top level `contents: read` (`:21-22`).
- **Callers (this repo).** `ops-rotate-secrets.yml`, `ops-distribute-kit.yml`, `ops-setup-e2e.yml`,
  `ops-provision-projects.yml`, `ops-distribute-app-secrets.yml`, `ops-triage-reports.yml`,
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

`.github/actions/run-e2e/action.yml`. The reusable Tier-2 E2E engine, invoked as a **step** inside a
tenant repo's `.github/workflows/e2e.yml` job (composite action, not `workflow_call`). It is
**tenant agnostic**. It reads the *caller's* `e2e/manifest.json` for the journey and the specs, and the
manifest on the caller's *default branch* for the repositories the App token may read, so it hardcodes
no tenant list and a branch cannot widen the token before it merges (ADR D-006/D-007, D-016).

**What it does** (`action.yml:34-208`). Free disk → read the caller's manifest (`:44-72`) → mint a
GitHub App token scoped `contents:read` to just this journey's repos + the SDK → check out cicd (no
credential kept) + the sibling repos into the sibling layout, each at the caller's own branch name when
it has one and at its default branch otherwise → hold the auth UI's copy of the hub contract to the
hub's recording → set up Python/Node/Playwright →
`python e2e/ci_stack.py up --journey <journey>` → `npm test` (with a fail closed "≥1 test ran" gate,
N2e, `:160-178`) → dump compose logs on failure → upload the Playwright report (1-day retention, GOOD-6)
→ tear the stack down.

**Inputs:**

| Input | Required | Default | Description |
|---|---|---|---|
| `journey` | no | `""` | Journey to run. Read from the caller's `e2e/manifest.json` when empty, and it must equal that manifest's `journey` when given |
| `sibling-ref` | no | `""` | Branch of every sibling repo to check out. Empty means the caller's own branch name where the sibling has one, the sibling's default branch otherwise |
| `app-id` | **yes** | — | GitHub App ID. Pass `${{ secrets.KDF_APP_ID }}` (composite actions can't read secrets directly) (`:14-16`) |
| `app-private-key` | **yes** | — | GitHub App private key. Pass `${{ secrets.KDF_APP_PRIVATE_KEY }}` (`:17-19`) |
| `cicd-ref` | no | `main` | Ref of `kriegerdataforge-cicd` to run the engine from (`:20-23`) |
| `gh-npm-token` | no | `""` | **Classic** `read:packages` PAT for the `npm ci` of the private `@needless2say/*` npm scope during frontend image builds. Pass the caller's `GH_NPM_TOKEN` secret for journeys whose manifest repos include such a frontend. Backend only journeys omit it. GH Packages npm rejects fine grained PATs and App tokens, so the minted App token cannot serve here (`:24-32`) |

- **Outputs.** None declared.
- **Permissions.** None in the action (a composite action inherits the calling **job's** permissions;
  the App token supplies its own scopes).
- **Secrets.** None read directly. The App credentials arrive as the `app-id` / `app-private-key`
  inputs. The minted App token doubles as `GH_PACKAGES_PAT` for the private SDK clone during the image
  build (`:144`). Browser journeys additionally pass the caller's `GH_NPM_TOKEN` secret via the
  `gh-npm-token` input, wired to the `GH_NPM_TOKEN` env of the stack build (`:147`).

**Caller job** (verified against `action.yml` + ADR D-007 `docs/design/e2e-cijob-refactor.md`). The
job **checks itself out into a path equal to its own repo name** (sibling layout). The action reads
`${repo}/e2e/manifest.json`. Then `uses:` the action:

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
          # journey: fitness              # optional, the manifest names it
          app-id: ${{ secrets.KDF_APP_ID }}
          app-private-key: ${{ secrets.KDF_APP_PRIVATE_KEY }}
          gh-npm-token: ${{ secrets.GH_NPM_TOKEN }}   # browser journeys only (private npm scope)
```

The `KDF_APP_ID` / `KDF_APP_PRIVATE_KEY` secrets + the `RUN_E2E_GATE` variable are provisioned into a
journey repo by [`ops-setup-e2e.yml`](#repo-internal-event-triggered-workflows), after an App
private key rotation, the secret copies are re-synced fleet wide by
[`ops-distribute-app-secrets.yml`](#repo-internal-event-triggered-workflows). See
[`E2E_TESTING.md`](../guides/E2E_TESTING.md) and [`e2e/README.md`](../../e2e/README.md).

---

## Permissions reference

Declared `permissions:` per reusable workflow (⊝ = not declared → caller/default token, job level
shown where it differs from top level):

| Workflow | Scope |
|---|---|
| `cd-nextjs-vercel.yml` | `authorize`: `contents:read`, `deploy`: `contents:read` |
| `cd-python-vercel.yml` | `authorize`: `contents:read`, `deploy`: `contents:read` |
| `cd-terraform.yml` | `authorize`: `contents:read`, `apply`: `contents:read` |
| `bump-version-check.yml` | job: `contents:read` |
| `create-github-release.yml` | job: `contents:write` (caller must grant) |
| `ci-codeql.yml` | job: `actions:read` + `contents:read` + `security-events:write` (caller must grant) |
| `ci-python-format` / `-kdf-fmt` / `-lint` / `-typecheck` / `-tests` / `-integration` / `-security` | top level. `contents:read` |
| `ci-nextjs-build` / `-lint-typecheck` / `-tests`, `ci-npm-audit`, `ci-vercel-compactor` | ⊝ none declared |
| `secret-scan.yml` | top level + job. `contents:read` + `pull-requests:read` |
| `_authorize-owner.yml` | top level. `contents:read` |

---

## Repo internal event triggered workflows

The remaining eighteen `.github/workflows/*.yml` (of 38 total: 20 `workflow_call` above + these 18) are
**not** `workflow_call`, so they cannot be `uses:`-d by a tenant. They run inside `kriegerdataforge-cicd` on schedules / issues / dispatch, and the ops ones are
owner gated via [`_authorize-owner.yml`](#_authorize-owneryml). Listed here for completeness of the
`.github/workflows/` enumeration.

| Workflow | Trigger(s) | What it does | Owner gate |
|---|---|---|---|
| `ci.yml` | `pull_request` → `main` | actionlint + pytest (`scripts/tests/`) + calls `bump-version-check.yml` | n/a |
| `release.yml` | `push` `main`, `paths: [VERSION]` | calls `create-github-release.yml` (`contents:write`) | n/a |
| `issue-create-repo.yml` | `issues: labeled` (`new-repo`) | provisions a repo from a template. Creates `prod`+`dev` Environments (owner reviewer, `main` only). Branch protection. Uses **repo level** `CICD_PAT` (Administration/Contents/Environments/Secrets/Variables/Actions R-W + Members: Read) | inline owner check |
| `ops-rotate-secrets.yml` | `issues: labeled` (`ops:rotate-secrets`) | issue form front end for `rotate_secret.py` (`check`/`generate`/`paste`) | `_authorize-owner` |
| `ops-distribute-kit.yml` | `issues: labeled` (`ops:distribute-kit`) | issue form front end for `distribute_kit.py` (`check`/`distribute`) | `_authorize-owner` |
| `ops-distribute-scripts.yml` | `issues: labeled` (`ops:distribute-scripts`) | issue form front end for `distribute_scripts.py`, the script sync sibling of `ops-distribute-kit.yml` (ADR D-013). Issue content flows through env vars into an argv array and `mode` is allow listed | `_authorize-owner` |
| `ops-distribute-all.yml` | `issues: labeled` (`ops:distribute-all`) | issue form front end for `distribute_all.py`, the kit and the dev scripts in ONE sync PR per repo, for the day both are due (ADR D-047). Every Distribute workflow closes its issue after posting the result, completed on success and not planned on a failure, and a sync PR whose every change is a copy cicd tested carries `[skip ci]` | `_authorize-owner` |
| `ops-setup-e2e.yml` | `issues: labeled` (`ops:setup-e2e`) | arms an E2E-journey repo. Writes `RUN_E2E_GATE=false`, `USE_GITHUB_APP=true`, copies `KDF_APP_ID`/`KDF_APP_PRIVATE_KEY`. Validates target against the fixed 6-repo allow list | `_authorize-owner` |
| `ops-provision-projects.yml` | `issues: labeled` (`ops:provision-projects`) | issue form front end for `provision_projects.py` (`check`/`execute`). Adopts/creates the 6 Projects v2 boards from `projects_registry.json`. Runs on an owner staged **classic** PAT in `SECRET_VALUE_NEW`. Neither an App token nor a fine grained PAT can manage user owned ProjectsV2 (ADR D-010 W1 finding) | `_authorize-owner` |
| `ops-distribute-app-secrets.yml` | `issues: labeled` (`ops:distribute-app-secrets`) | issue form front end for `distribute_app_secrets.py` (`check`/`execute`). Copies this repo's `KDF_APP_ID`/`KDF_APP_PRIVATE_KEY` to every consumer repo in `secret_registry.json` (`distribute_source_env` entries, the 12-repo registry list generalizes `ops-setup-e2e`'s fixed copy step). App token scoped `secrets:write` to exactly those repos. Run after an App key rotation (§8.3a) or when onboarding a consumer | `_authorize-owner` |
| `ops-triage-reports.yml` | `issues: labeled` (`ops:triage-reports`) | issue form front end for `trigger_triage.py` (`dry-run`/`execute`, dev/prod). The owner's "run triage now" button. Fires the selected apps' `/reports/triage/cron` endpoints from `reports_registry.json` and comments the metadata only result (executing against prod requires the Confirm dropdown). Ops guide, the owner's `REPORTS_TRIAGE_OPS.md` (`kriegerdataforge-context/ops/`) | `_authorize-owner` |
| `distribute-kit.yml` | `workflow_dispatch` (`mode` check/distribute, `only`, `repos`) + weekly `schedule` (drift alarm) | runs `distribute_kit.py`. Opens one sync PR per drifted repo. `check` also fails on a gap in a repo's own files (the `AGENTS.md` role pointer, `.env.kdf.example`, `.env.kdf` ignored), which that repo fixes itself | `_authorize-owner` (dispatch only) |
| `distribute-gh-pat.yml` | `workflow_dispatch` | distributes a staged `GH_PACKAGES_PAT_NEW` via `rotate_secret.py --mode paste` | `_authorize-owner` |
| `rotate-vercel-tokens.yml` | monthly `schedule` + `workflow_dispatch` | re-mints the shared `VERCEL_DEPLOYMENT_TOKEN` (`--mode generate`, 45-day life) and opens a PR stamping the new expiry | `_authorize-owner` (dispatch only) |
| `check-secret-expiry.yml` | weekly `schedule` (Mon 09:00 UTC) + `workflow_dispatch` | `rotate_secret.py --mode check --secrets all --live`. Each `check.live` token goes to its own provider alone for its real expiry (GitHub's `github-authentication-token-expiration` header, Vercel's token metadata), the date alone printed, and a registry date that disagrees is drift (D-049). Keeps one dedup tracking issue (`ops:secret-expiry`) open/closed | n/a (`issues:write`, `CICD_PAT`, `GH_PACKAGES_PAT` and `VERCEL_MASTER_TOKEN` to the check step alone) |
| `check-oidc-rp-drift.yml` | weekly `schedule` (Mon 12:30 UTC) + `workflow_dispatch` | PL-084 interim guard. `check_oidc_drift.py` compares the copy pasted OIDC RP core (`oidc.ts` + callback/initiate/logout routes, `scripts/oidc_drift_manifest.json`) across the two tenant frontends. Keeps one dedup tracking issue (`ops:oidc-rp-drift`) open while any pair differs. Paths + changed line counts only, never file contents | n/a (App token/`CICD_PAT` for cross repo reads, `issues:write`) |
| `trigger-reports-triage.yml` | weekly `schedule` (Mon 09:23 UTC) + `workflow_dispatch` (`apps`, `environment`, `dry_run`) | `trigger_triage.py`: POSTs each selected app's `X-Cron-Secret`-gated `/reports/triage/cron` (`reports_registry.json`). **Disarmed at birth**: the schedule job requires `vars.RUN_REPORTS_TRIAGE == 'true'` AND per app registry `enabled: true`. Scheduled runs = enabled apps against prod. POSTs never status retried, output metadata only | n/a (dispatch is maintainer only by repo perms, schedule gated by `RUN_REPORTS_TRIAGE`) |
| `hub-prune-tokens.yml` | daily `schedule` (04:17 UTC) + `workflow_dispatch` (`environment`) | POSTs the auth hub's `CRON_SECRET` gated `/internal/cron/prune-tokens` once per environment, which deletes expired denylist rows, spent verification tokens, audit rows past retention, abandoned registrations and expired OIDC rows in the hub (hub DEFERRED row 21). **Disarmed at birth**, the schedule job requires `vars.RUN_HUB_PRUNE == 'true'`, arm it with the hub release whose route answers POST. Per environment secrets `KDF_HUB_URL_{DEV,PROD}` and `KDF_HUB_CRON_SECRET_{DEV,PROD}`, an environment missing either is skipped with a notice. Prints the per table counts only | n/a (dispatch is maintainer only by repo perms, schedule gated by `RUN_HUB_PRUNE`) |
| `codeql.yml` | `push` / `pull_request` → `main` + weekly `schedule` (Sun 00:00 UTC) | CodeQL over the Playwright suite under `e2e/`, through the centralized reusable workflow. The analyze job stays skipped until `vars.ENABLE_CODEQL == 'true'` (a public repo or GitHub Code Security) | n/a |

`GH_PACKAGES_PAT` distribution, Vercel/kit ops, and the App secret distribution mint short lived
**GitHub App** tokens when `vars.USE_GITHUB_APP == 'true'`, falling back to `CICD_PAT`
(`distribute-gh-pat.yml:59-73`, `rotate-vercel-tokens.yml:70-91`,
`ops-distribute-app-secrets.yml`). Board provisioning is the exception. It needs an owner staged
classic PAT (see the D-010 W1 finding). See the GitHub App migration ADR in
`docs/CHANGELOG_AND_DECISION_LOG.md`.

---

## Consumer repo summary

The authoritative allow list is [`scripts/deployer_registry.json`](../../scripts/deployer_registry.json)
(`repo → environment → deployers`). Every repo below runs the
[Deployer authorization gate](#deployer-authorization-gate). The CD workflow column follows repo type.

| Consumer repo | Environments (registry) | CD workflow |
|---|---|---|
| `kriegerdataforge` | `dev`, `prod` | `cd-python-vercel.yml` |
| `kriegerdataforge-auth-ui` | `dev`, `prod` | `cd-nextjs-vercel.yml` |
| `fitness-app-frontend` | `dev`, `prod` | `cd-nextjs-vercel.yml` |
| `fitness-app-backend` | `dev`, `prod` | `cd-python-vercel.yml` |
| `tiffanys-space` | `dev`, `prod` | `cd-nextjs-vercel.yml` |
| `tiffanys-space-backend` | `dev`, `prod` | `cd-python-vercel.yml` |
| `kriegerdataforge-terraform` | `dev`, `prod` | `cd-terraform.yml` |
| `arthurs-portfolio` | `github-pages` | self contained `cd.yml` → GitHub Pages (runs the gate) |
| `kriegerdataforge-portfolio` | `github-pages` | self contained `cd.yml` → GitHub Pages (runs the gate) |
| `kriegerdataforge-template-nextjs` | `dev`, `prod` | `cd-nextjs-vercel.yml` (prepared files placeholder) |
| `kriegerdataforge-template-fastapi` | `dev`, `prod` | `cd-python-vercel.yml` (prepared files placeholder) |

---

## Related

- The owner's runbooks in the private `kriegerdataforge-context/ops/`. `MANUAL_SETUP.md` (GitHub Environments, environment secrets, PAT/token creation, tenant onboarding) and `SECRET_ROTATION.md` (rotate a repo/environment secret via `rotate_secret.py` + `secret_registry.json`).
- [`docs/guides/E2E_TESTING.md`](../guides/E2E_TESTING.md) + [`e2e/README.md`](../../e2e/README.md). The E2E engine model and local run.
- [`CONTRIBUTING.md`](../../CONTRIBUTING.md). Two tier model + breaking change governance for reusable workflow interfaces.
- [`scripts/deployer_registry.json`](../../scripts/deployer_registry.json) · [`scripts/check_deployer.py`](../../scripts/check_deployer.py). The deployer gate data + logic.
- [`docs/CHANGELOG_AND_DECISION_LOG.md`](../CHANGELOG_AND_DECISION_LOG.md). ADRs (kit distribution D-001, GitHub App migration, E2E decoupling D-006/D-007).
</content>
</invoke>
