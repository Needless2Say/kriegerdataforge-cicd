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
`always()` unless the caller's `skip` says docs only (D-075), and its first step ends it failed when, with
`needs_sdk_auth`, the fetch did not succeed (a skipped required job counts as passing). The step's `cancelled()` arm
reads false in a job `always()` keeps through a cancel, measured in D-075, so without package access the job runs its
work on a cancelled run. It checks the caller out with no credential kept, then downloads the mirrors and hands git one
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
caller's own text. Its fetch job runs on every call that `skip` does not skip, mirrors only
`kriegerdataforge-fmt` and mints for that repo alone. With no `kdf_fmt_ref` it reads the caller's
`requirements-dev.in`, where every repo declares kdf-fmt at `main`, the one branch a requirement file may name
(D-054), and its check job
reads the ref from the same line, the URL fixed, failing by name when the line is missing. A caller
that passes `kdf_fmt_ref`, an override, gets that ref alone. The check job keeps the
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
| `ci-python-kdf-fmt.yml` | `python_version`=`3.14`, `kdf_fmt_ref`=`""` (an override, empty reads the ref from `requirements-dev.in`, D-054), `check_command`=`python -I -m kdf_fmt.cli check --no-cache`, `ref`=`""` | always, two jobs (D-038), the fetch mints for `kriegerdataforge-fmt` alone (App token first, `GH_PACKAGES_PAT` fallback, callers pass `secrets: inherit`), private callers only | `contents: read` |
| `ci-kdf-fmt-public.yml` | `python_version`=`3.14`, `kdf_fmt_ref`=`""` (an override, empty reads `requirements-dev.in`), `baseline`=`""` (a plain file name) | always, one job (D-044), mints for `kriegerdataforge-fmt` alone (App token first, `GH_PACKAGES_PAT` fallback, `secrets: inherit`), fails when no token reaches it, PUBLIC callers, no artifact | `contents: read` |
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

The Postgres these three jobs start is Docker's official image from the owner's mirror on GitHub's registry,
`ghcr.io/needless2say/postgres`, pinned by its index digest, PostgreSQL 16.15, `server_version_num` 160015 (D-077).
Docker Hub's anonymous pull limit (D-064) and then ECR Public's data limit, each counted by a runner's address, had
failed whole jobs before a test ran. `mirror-ci-images.yml` copies the image there and proves it public, and the
runner logs in to GitHub's registry with the job's own token before it pulls the service, a `docker ... login
ghcr.io` line in "Initialize containers" that names no secret. `postgres-lane-proof` in this repo's `ci.yml` proves
the lane on each pull request here that changes code, before a caller meets it, a docs only one skipping it (D-075). A new patch follows the copier's order in
[CI's image mirror](#cis-image-mirror-d-077-d-080), and
`scripts/tests/test_workflow_service_images.py` holds every workflow here but the copier, which has its own, to one
rule on its text. A line that is not
a comment and names `image`, `container` or `docker`, in any case, must be a service's `image:` line with the lanes'
image by a digest and nothing after it, and no line may hold a `\x`, `\u` or `\U` escape. So a job's container, a
`docker://` step or a script's `docker run` is refused until the test is changed with it. It catches a mistake, not a
workflow written to hide a pull, which whoever can edit a workflow could write anyway.

**`ci-python-integration.yml`** additionally provisions a PostgreSQL 16 **service** (`kdf`/`kdf`/
`kdf_test`, health checked) and exports the connection string under **two** names,
`DB_DATABASE_URL` (SDK/alembic, `env_prefix=DB_`) and `KDF_TEST_DATABASE_URL` (the pytest conftest
gate), so a `-m requires_postgres` suite actually runs instead of silently green skipping (finding
PL-166). It declares `ENVIRONMENT: local`, since a stack started in Actions is local by the owner's
definition (2026-09-30) and never the DEV account. App specific schema (e.g. a `kdfusers` table) is
provisioned by the caller's `seed_command`, whose SQL lives in the caller's private repo (`:68-91`).

**`ci-python-system.yml`** provisions a PostgreSQL 16 service whose database is `kdf_system` and
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
| `ref` | string | `""`, the caller run's own ref | no |
| `fetch-depth` | number | `0` (full history) | no |
| `not_docs` | string | `""`, the docs the caller's code, tests, build or package read, space separated patterns | no |

- **Secrets.** `GITHUB_TOKEN` (default). **Outputs.** `docs_only`, `true` on a pull request whose every changed
  path is docs and none is in `not_docs`, proven against its merge commit, else empty (D-075, below).
- **Permissions.** Top level **and** job. `contents: read`, `pull-requests: read`. The caller grants both at its top
  level, or the whole run fails at startup and shows no check at all.
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

#### `kdf-scan-gate-reusable.yml`

The local code scan's gate (D-088), Opengrep over the code and zizmor over the workflows of one pull request's head,
in `ghcr.io/needless2say/kdf-scan` by the digest written in the workflow, which `scripts/common/SCAN_IMAGE` names
too. A caller never writes its own caller. `.github/workflows/kdf-scan-gate.yml` is the text of
`scripts/common/kdf-scan-gate-caller.yml`, which the scripts sync writes whole once the registry's `scan_caller` says
its credential may write workflow files, a bootstrap pull request bringing it before, and the owner starts it on
`main` at each merge attempt.

| Input | Type | Default | Required |
|---|---|---|---|
| `pr` | number | none | yes |

- **Secrets.** None, the job's own `GITHUB_TOKEN` alone. **Outputs.** None, its summary names the caller workflow,
  cicd's `main` when the run began, the head, the base's `main`, the image, the scanner's cicd commit and the rules'
  commit, and its last line is the scan's.
- **Permissions.** Workflow `{}`, the job `contents: read` and `pull-requests: read`.
- **What it refuses.** Any event but `workflow_dispatch` and any ref but `refs/heads/main`, a pull request whose base
  is not `main`, an unpinned image, fetched ids unlike GitHub's, and a head, `main` or pin that moved during the run.
  The scan itself runs with the network off, the root read only, no capability and a user that is not root. It fails
  a pull request that changes the caller to other than the canonical text, or changes a workflow that names the gate
  in any case or through YAML's escapes, cicd's own reusable workflow apart in cicd alone, the repository named by
  `github.repository`. A name an expression builds at run time is beyond the text, so the owner reads the run's path
  and event.
- **Consumers.** Every repo with a Makefile, once its caller arrives. A public repo's log names rule
  ids and never a rule's message.

```yaml
jobs:
  kdf-scan-gate:
    uses: Needless2Say/kriegerdataforge-cicd/.github/workflows/kdf-scan-gate-reusable.yml@main
    with:
      pr: ${{ inputs.pr }}
```

### The docs only fast path (D-075)

A pull request whose every change is docs runs the secret scan alone in a repo whose `ci.yml` is wired for it, every
required check still reporting and passing, and it bumps no version. GitHub has no rule that requires a check only
when its paths change. A workflow skipped by a path filter leaves its checks pending, and a job skipped by its own
condition reports Success, so the skip lives in the workflows.

**What counts as docs** is one list, `scripts/common/ci_paths.py`, which the scan and Distribute both read. A path is
docs when it starts with the root `docs/` folder or its last part ends in `.md`, both case sensitive, so `README.MD`
and `nested/docs/x.txt` are code. A file under `docs/` whose extension, in any case, is on the short list of code
(`.py`, `.pyi`, `.ts`, `.tsx`, `.js`, `.jsx`, `.mjs`, `.cjs`, `.tf`, `.tfvars`, `.tfstate`, `.tfplan`, `.hcl`, `.sh`,
`.go`, `.sql`) stays code. A change is docs only when it changes at least one path and every path, a rename read as a
deletion and an addition, is docs.

**`not_docs`** names the docs a repo's code reads, a README a wheel or an npm package packs, a prompt a package loads,
a Markdown file a test asserts. Patterns over the whole path in GitHub's path filter syntax, `*` within one folder and
`**` across folders, `**/` matching zero or more folders. A pattern holding `?`, `+`, `[`, `]` or `!`, which GitHub
reads another way, or `{` and `}`, which a matcher may read as alternation, is refused, as is an empty or absolute
one, one with an empty, `.` or `..` part or a backslash, and one that matches no tracked file. A refusal gives no
answer, every lane runs, and the step's log and summary say why. A path whose name holds one of those characters is
named with `*` in its place, `app/*/x.md` for `app/[slug]/x.md`, a superset that still matches it. The pull request
that makes code read a `.md` or a file under `docs/` adds it to `not_docs` in the same pull request, and a file the
kit syncs is never named there, since Distribute reads no repo's `not_docs`.

**The answer.** The scan's last step, `Docs only`, runs only after gitleaks passed, on a `pull_request` event with an
empty `ref`, with `continue-on-error`, so it never fails the scan. It proves `HEAD` is the event's commit with exactly
two parents, the pull request's base and head, in a checkout that is not shallow, lists the change with
`git diff --name-only --no-renames -z`, checks git's exit status, and writes `docs_only=true` only when the list says
so. It prints no path to the log, one line of fixed text and counts, and writes its summary, each path escaped, to
the step summary file alone. A push, a schedule or a release dispatch with a `ref` gets no answer.

**`skip`**, a boolean defaulting to `false`, is on every billed lane, `ci-python-tests`, `-integration`, `-system`,
`-mutation`, `-security`, `-lint`, `-typecheck`, `ci-python-kdf-fmt`, `ci-vercel-compactor`,
`ci-nextjs-lint-typecheck`, `-build`, `-tests` and `ci-npm-audit`. Every job of the lane reads it, so each required
check `<caller job> / <called job>` reports skipped. A caller job skipped by its own condition would report its own
name alone and leave the required check pending. A job the fetch renderer does not write, the one job lanes and the
security lane's Bandit job, reads `skip` alone, so a cancelled run cancels it as it did before. `secret-scan.yml`,
`ci-codeql.yml` and `fetch-private-packages.yml` take no `skip`.

**The caller pattern.** The skip is one expression, true only when the scan job itself succeeded and said so. Each
lane's caller job waits for the scan, runs on `!cancelled()` joined to any condition it had, and passes the
expression. A job's own `if` reads `cancelled()` true after a cancel, so a cancel during the scan never enters the
caller and each `<caller job> / <called job>` check never reports, which blocks a merge as a failed check does. Never
put a caller on `always()`. GitHub keeps a job on `always()` running through a cancel, and a step's `cancelled()`
reads false inside it, so no guard step there can fail it (D-075, measured). Each local job waits for the scan, runs
on `always()` and the expression's negation joined to its own condition, since a local job skipped on a cancelled run
reports Success under its own name, and its first step fails it when the scan ended neither `success` nor `failure`,
the result a step does read after a cancel. A required check that comes from a matrix job, or a job whose name holds
an expression, may report its unexpanded name when skipped, so such a job is listed and checked before it is wired.

```yaml
jobs:
  secret-scan:
    uses: Needless2Say/kriegerdataforge-cicd/.github/workflows/secret-scan.yml@main
    with:
      ref: ${{ inputs.ref }}
      not_docs: README.md src/example/prompts/*.md

  lint:
    needs: [secret-scan]
    if: ${{ !cancelled() }}
    uses: Needless2Say/kriegerdataforge-cicd/.github/workflows/ci-python-lint.yml@main
    with:
      ref: ${{ inputs.ref }}
      skip: ${{ needs.secret-scan.result == 'success' && needs.secret-scan.outputs.docs_only == 'true' }}
    secrets: inherit

  version-check:
    name: Version check
    needs: [secret-scan]
    if: ${{ always() && !(needs.secret-scan.result == 'success' && needs.secret-scan.outputs.docs_only == 'true') && github.event_name == 'pull_request' }}
    runs-on: ubuntu-latest
    steps:
      - name: Fail when the scan did not finish
        if: ${{ needs.secret-scan.result != 'success' && needs.secret-scan.result != 'failure' }}
        env:
          SCAN_RESULT: ${{ needs.secret-scan.result }}
        run: |
          echo "::error::the secret scan ended $SCAN_RESULT, so this job ends failed rather than skipped and checks nothing"
          exit 1
      # the job's own steps follow
```

On a code pull request every lane starts after the scan, about a minute later, and no billed minute is added, since
the scan runs anyway. A run cancelled after the scan, a superseded push under `cancel-in-progress` for instance,
cancels a lane's jobs, while a rendered lane's install job and a local job, each on `always()`, run to their end. A
docs only merge to `main` starts every workflow that runs on a push, and the scan answers only
a pull request, so each such workflow takes a `paths:` filter of the same rule, every path, then not `docs/**` and not
`**/*.md`, then the code under `docs/` and each `not_docs` pattern included again. A push has no required check, so a
path filter is safe there. A path filter matches case sensitively, so a code file under `docs/` whose extension is not
lower case is code to the scan and docs to the filter, which only spares a push workflow on its merge after its pull
request ran whole.

**The undo.** A pull request here that makes the last step write nothing turns the fast path off in every repo at
once, keeping the inputs the callers pass, since removing an input a caller passes breaks that caller. A check already
green stays green and a running workflow may keep the old lane, so the undo also lists the open docs only pull
requests, holds their merges, and reruns each on the disabled classifier before any merges. A docs pull request is
never bumped to merge it, which would cut a release. Until the fast path works again, a docs only pull request is held
or closed.

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
- **Images (D-080).** `scripts/ecosystem_images.py` reads the copier, `mirror-ci-images.yml`, from cicd's `main` by
  the image test's shapes. For each `WATCH` line it asks the line's publisher alone, never a mirror, for its upstream
  tag by an uncounted `HEAD`. A digest other than the kept one is read for its version, from its config's OCI label
  or `<NAME>_VERSION` env, else, for an image whose config names none, as Mailpit's, from the publisher's release tag
  of the kept tag's shape whose index digest is the same, a higher tag on another digest passed over. A newer version
  at the line's level, patch, or minor for Checkov, is a finding. The same version or a newer one below the level is
  a rebuild, one note line. A followed tag's newer runtime of its shape on Docker Hub, `26-alpine` beside `24-alpine`,
  is a note line too and never a finding, since moving runtime is a migration the owner chooses. The Trivy version
  the terraform scan pins beside Trivy's latest release, and the copier's newest scheduled run red or older than two
  days, are findings. Its registry reads use anonymous pull tokens, never the App token, each bounded in retries,
  every tag list at most 20 pages of 1,000, and the whole section in one five minute budget. A read that fails, a
  list cut short or a version neither config nor tag names is unread and keeps the issue open. It needs no input,
  secret or permission beyond the watch's own.
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

The remaining twenty two `.github/workflows/*.yml` (of 51 total, 29 `workflow_call` and these 22) are
**not** `workflow_call`, so they cannot be `uses:`-d by a tenant. They run inside `kriegerdataforge-cicd` on schedules / issues / dispatch, and the ops ones are
owner gated via [`_authorize-owner.yml`](#_authorize-owneryml). Listed here for completeness of the
`.github/workflows/` enumeration.

| Workflow | Trigger(s) | What it does | Owner gate |
|---|---|---|---|
| `ci.yml` | `pull_request` → `main` | actionlint + kdf-fmt over `scripts/` and `tools/claude-code/`, the roots `kdf-fmt.toml` names (D-082) + pytest (`scripts/tests/`) + calls `bump-version-check.yml`, and D-075's skip and cancel probes, no required check, `skip-probe-nested` calling `probe-nested.yml`, a `workflow_call` only `ci.yml` calls, the scan beside a lane called with `skip: true`, and D-077's `postgres-lane-proof`, the integration lane by a local reference holding its service's `server_version_num`, no required check | n/a |
| `release.yml` | `push` `main`, `paths: [VERSION]` | calls `create-github-release.yml` (`contents:write`) | n/a |
| `issue-create-repo.yml` | `issues: labeled` (`new-repo`) | provisions a repo from a template. Creates `prod`+`dev` Environments (owner reviewer, `main` only). Branch protection. Uses **repo level** `CICD_PAT` (Administration/Contents/Environments/Secrets/Variables/Actions R-W + Members: Read) | inline owner check |
| `ops-rotate-secrets.yml` | `issues: labeled` (`ops:rotate-secrets`) | issue form front end for `rotate_secret.py` (`check`/`generate`/`paste`) | `_authorize-owner` |
| `ops-distribute-kit.yml` | `issues: labeled` (`ops:distribute-kit`) | issue form front end for `distribute_kit.py` (`check`/`distribute`) | `_authorize-owner` |
| `ops-distribute-scripts.yml` | `issues: labeled` (`ops:distribute-scripts`) | issue form front end for `distribute_scripts.py`, the script sync sibling of `ops-distribute-kit.yml` (ADR D-013). Issue content flows through env vars into an argv array and `mode` is allow listed | `_authorize-owner` |
| `ops-distribute-all.yml` | `issues: labeled` (`ops:distribute-all`) | issue form front end for `distribute_all.py`, the kit and the dev scripts in ONE sync PR per repo, for the day both are due (ADR D-047). Every Distribute workflow closes its issue after posting the result, completed on success and not planned on a failure, and a sync PR whose every change is a copy cicd tested or docs by `ci_paths` (D-075) carries `[skip ci]` | `_authorize-owner` |
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
| `codeql.yml` | `push` / `pull_request` → `main` + weekly `schedule` (Sun 00:00 UTC) | CodeQL through the centralized reusable workflow, one leg for `python` and one for `javascript-typescript` over `scripts`, `e2e` and `tools` (D-085, design 5.8), hosted with no local target. The analyze job stays skipped until `vars.ENABLE_CODEQL == 'true'`, free on this public repo | n/a |
| `mirror-ci-images.yml` | `push` `main`, `paths` its own file alone, + `workflow_dispatch` with no `inputs` + daily `schedule` (06:23 UTC) | The copier of every image CI pulls (D-077, D-080), the next section | n/a (`main` guard on its copy job, `packages: write` to that job alone, both proof jobs and the workflow `{}`) |
| `publish-scan-image.yml` | `push` `main`, `paths` the scan's sources and its own file, + `workflow_dispatch` | Builds the local code scan's image into an OCI archive, inspects every layer for the stock rules, runs the image's own fixtures, then pushes that archive to `ghcr.io/needless2say/kdf-scan` tagged with its commit, attests it in GitHub's attestation store and reads it anonymously (D-088, D-089). Nothing is deleted, and an image runs nowhere until an activating pull request pins its digest | n/a (`main` guard on both jobs, the build job `{}`, `packages`, `attestations` and `id-token` write to the publish job alone) |
| `kdf-scan-gate.yml` | `workflow_dispatch` (`pr`) | This repo's own copy of the gate's caller, `scripts/common/kdf-scan-gate-caller.yml` whole, since cicd is no target of its own scripts sync, a test holding the two equal. The owner starts it on `main` at each merge attempt, and it calls `kdf-scan-gate-reusable.yml` at `main`, its log printing rule ids alone since this repo is public (D-085, D-088) | n/a (`contents: read`, `pull-requests: read`) |

`GH_PACKAGES_PAT` distribution, Vercel/kit ops, and the App secret distribution mint short lived
**GitHub App** tokens when `vars.USE_GITHUB_APP == 'true'`, falling back to `CICD_PAT`
(`distribute-gh-pat.yml`, `rotate-vercel-tokens.yml`,
`ops-distribute-app-secrets.yml`). Board provisioning is the exception. It needs an owner staged
classic PAT (see the D-010 W1 finding). See the GitHub App migration ADR in
`docs/CHANGELOG_AND_DECISION_LOG.md`.

**Hardened for the local code scan (D-085, design 5.7).** Every App token names its `repositories:`. A token whose
targets come from a registry, an input or an issue lists them first with `scripts/token_repositories.py`, through the
operation's own selection, so the token reaches the repos the run acts on and no other. The `ops-*` workflows mint
only after reading the issue's fields, and an empty list fails rather than minting a token for every repo. The OIDC
drift check names its manifest's two repos and the expiry pull request cicd alone. `ops-setup-e2e.yml`'s token names
its one target and takes the App's grants whole, since the action has no input for repository variables, accepted on
its line. No single value input is expanded in a shell, `bandit_version`, `pip_audit_version`, `bandit_paths` and the
Vercel check's environment read from the step's `env`, `bandit_paths` split into its paths with no evaluation, and
each command input, `install_command` and its kind, is the caller's own command by design, accepted on its `run:`
line. `issue-create-repo.yml` holds `contents: read` alone, its issue writes going through `CICD_PAT`, and Dependabot
waits seven days on a GitHub Actions release.

### CI's image mirror (D-077, D-080)

`mirror-ci-images.yml` keeps every image CI pulls on the owner's mirror on GitHub's registry,
`ghcr.io/needless2say/<name>`, and proves each public on a runner, so no pull spends an allowance a runner's other
tenants share. It runs on `main` alone, at a push that changes its own file, at the owner's dispatch, which takes no
input, and once a day at 06:23 UTC, never on a pull request. Its env names every entry in its own text.

| Block | What it keeps | How a tag is set |
| --- | --- | --- |
| `SOURCES` | Each package and its sources in turn, Docker's official images on ECR Public's gallery, Docker Hub and Google's mirror, Mailpit's and Checkov's publishers on GitHub's registry and Docker Hub | A source serves bytes by a digest already chosen, read with no credentials, and never decides a tag |
| `KEPT` | The Postgres lanes' entries, each its index digest, its tag and its `server_version_num`, the newest last (D-077) | Fixed, the entry's own tag |
| `PINNED` | The E2E stacks' Postgres 16-alpine, Caddy and Mailpit and the terraform scan's Checkov, each its package, index digest and tag | Fixed, the version and variant its image's config carries, `16.15-alpine`, `2.10.2-alpine`, `v1.31.2`, `3.3.6` |
| `FOLLOWED` | The base images every Dockerfile builds on, `node 24-alpine` and `python 3.14-slim`, and a held digest while a hold stands | The digest Docker Hub names for the tag, read each run, unless held |
| `WATCH` | A line per kept or pinned image, its publisher, its line's upstream tag and the level a newer version is reported at, `patch` or Checkov's `minor` | Never, the weekly ecosystem watch alone reads it |

Every destination tag is unique across `KEPT`, `PINNED` and `FOLLOWED`, so the lanes' `16.15` and the stacks'
`16.15-alpine` never share one.

- **`copy`** holds `packages: write` through the job's own token, the one job of this repo that may write a package,
  and checks out nothing and runs no repository code and no action. It logs in through standard input and reads every
  source with `--src-no-creds`, so the token travels to none. First its gate, then holds, then each kept and pinned
  entry, then each followed tag, each entry apart, every failure gathered into one red at the close with its kind
  named, none cleared by a later success. An entry is left as it is only when its index, an index by its own
  `mediaType`, every manifest it lists and the runner's platform's layers read, each hashed to its digest, and its
  tag's own manifest hashes to the digest. A followed tag left as it is is still chosen, so the proof holds it there.
  Every other is copied with `skopeo copy --all --preserve-digests --src-no-creds`, from each source in turn by the same
  digest, each attempt bounded, and held to the same checks after. Each line it writes names the entry, its source,
  its digest and its image's creation time, evidence and never a rule. Its outputs are the gate's answer and each
  followed tag's chosen digest.
- **Its gate.** The run fetches its own commit and `main`'s anonymously with no blob into a fresh repository and
  compares this file's blob at each. The same blob runs as current. Another blob applies no hold, follows no tag and
  copies no followed digest, ending green with a notice naming `main`'s commit on a first attempt and red on a rerun.
  A failed fetch or an empty read is red and moves nothing followed. Kept and pinned entries are copied in every case.
- **A followed tag** is decided by Docker Hub alone, by a `HEAD` for `registry-1.docker.io/v2/library/<name>/manifests/
  <tag>` with an anonymous pull token, which Docker says does not count toward its limit. Its answer counts only as a
  200 with an index's `Content-Type` and a digest of its exact shape. Before the tag moves, the digest the mirror's tag
  holds is asked the same way, the tamper check. A 404 records that digest, repairs the tag and ends the run red. A
  refusal decides nothing. The copied digest must be an index by its `mediaType`.
- **`verify`** has no permissions. Its service is the lanes' own with the newest kept digest on the mirror, its
  `server_version_num` read by host and port and held to that entry's (D-077).
- **`verify-images`** has no permissions and no service. It reads every entry's index and listed manifests with
  `skopeo inspect --raw --no-creds` and pulls the runner's platform of each followed tag and pinned entry with
  `skopeo copy --src-no-creds` into the runner's temp folder, so a package still private fails closed, and the owner
  sets it public on its page and dispatches the copier again. On a current run it holds each followed tag to the copy's
  chosen digest, or to its hold, or gives it the tamper check when the copy chose none. A run whose text is not
  `main`'s makes no placement or tamper decision on a followed or held tag.

Both proofs run on `main` after a copy that succeeded or failed, never after a skip or a cancel, by a condition that
names `!cancelled()`. One concurrency group, `mirror-ci-images-copy`, holds a whole run, copy and proofs.

**Each kind of red, and what it asks.**

| The close names | What happened | What it asks |
| --- | --- | --- |
| `refused` | Docker Hub did not name a followed tag's index | Nothing. The tag still serves its last image, and the next day's run tries again. Counted for the month later check |
| `stale-rerun` | A rerun whose copier text is not `main`'s | A dispatch from `main`, unless `main`'s own run has ended green since. Never a rerun |
| `gate` | The copier's blob could not be read at the run's commit or at `main`'s | A dispatch from `main` once GitHub answers |
| `tamper` | The mirror's tag held a digest Docker Hub does not serve for the image, recorded in the log, the tag already repaired | A look at the recorded digest and at the package's access settings. A 404 can also mean an old digest Docker Hub stopped serving |
| `hold` | A hold's digest is not in its package, or the tag could not be set to it | The hold's pull request corrected |
| `copy` | No source served an entry, or the copy is not present and placed | A dispatch once a source serves it, else the entry's pull request |
| `private`, `pull`, `placement` | `verify-images` could not read or pull an entry with no credentials, or a tag is not on its digest | The package's page set public, then a dispatch, else the log read for the digest |

**A hold.** A bad upstream image is held by a cicd pull request that writes a digest its package already holds after
the followed tag, `node 24-alpine sha256:<digest>`. Its merge sets the tag from the mirror's own copy with no upstream
read and never sends that digest to Docker Hub, and each later run warns, naming the held digest and Docker Hub's
current one. The hold is in force once its own run's placement proof is green, so read that run. A run that compared
its copier text before the hold merged can still publish in the minutes before, and the hold's run sets the tag back.
Never rerun an old run to apply a hold, dispatch from `main`. Removing the digest resumes following.

**A new tag**, `node 26-alpine` one day, is a cicd pull request appending it to `FOLLOWED`, its merge copying it, then
the Dockerfiles' pull requests. A tag no Dockerfile names is removed from `FOLLOWED` in a later one, its copies kept.

**A new service digest** follows D-077's order. A cicd pull request appends the `PINNED` entry and its `WATCH` line, its
merge copies and proves it, and later pull requests move the shared stack and the tenants' stacks. Nothing in cicd's
runs starts the stack to enforce the order, so this page, D-080 and the stack's own comment write it. The shared
stack, `e2e/docker-compose.shared.yml`, names the mirror for its four image lines, each line's package and digest a
pair the copier pins, which the image test holds.

**Two ways back.** A failing image is answered by a hold. A failing mirror is answered per consumer, its `FROM` line
or its stack's lines back on an upstream that serves that day, each a pull request in its own repository. For the
shared stack, its four lines on ECR Public's gallery and Mailpit's own `ghcr.io/axllent` by the same digests, and the
image test's `STACK_MODE` set to `upstream`, in one pull request.

**The packages grow, and the logs fade.** Each index's platform and attestation manifests are untagged versions, and a
followed tag that moved leaves its old index untagged too, some fifty a year for Python's slim tag. That costs nothing
for a public package. The run's log is the record of what each tag held when, kept 90 days, the package pages' dates
the record after that.

A Postgres patch is ordered. First a cicd pull request appends the new entry to `KEPT` and moves `verify`'s service
line to it, the lanes unchanged, and its merge runs the copier, which copies and proves it. Then the pull requests
that move the lanes, each lane's digest and the version `postgres-lane-proof` expects moving together, cicd's proven
by its own `postgres-lane-proof`, each other repo's that starts the same service by its own run before it merges. A
pull request that both appended an entry and moved a lane to it would fail its `postgres-lane-proof` on the missing
image, so the proof guards the order too. The image test holds every lane's digest among the kept ones, `verify` on
the newest, and the proof's expected version the lanes' entry's. The old entry stays kept, so a rollback is the
lanes' pull request naming it again with its version, and moving the lanes back to ECR Public's gallery is their lines
and the test's one constant for the lanes' image.

**No version of any package, tagged or untagged, is ever deleted.** The index's platform and attestation manifests
show as untagged versions, which a tidy of untagged versions would remove, and every build, stack or lane that names
one then fails before it starts. GitHub restores a deleted package within 30 days while its name is not reused, and a
dispatch of the copier copies a kept or pinned digest again while a source still serves it, and a followed tag's
current image always.

**Who can move a followed tag** chooses the code every build runs, so no token is ever given `write:packages`, and no
repository but this one is given write in a package's Actions access, which the owner reads on each new package's page.

The image test, `scripts/tests/test_workflow_service_images.py`, reads the copier by a strict rule of its own,
`scripts/tests/copier_rule.py`. Its triggers with their one schedule, its concurrency, its `main` guard, each job's
declared permissions and condition, its `needs`, the copy job's outputs, `verify`'s service and its target are each
held whole, a key's line and every line below it, so a line continued or a key added below a blank line is refused.
Its sources, kept, pinned, followed and watched entries are held to their exact shapes, every source on one of seven
known hosts and paths and every destination tag unique. It holds no action, the blob comparison's lines and the tamper
check's token and `HEAD` lines as written, and its every other line that names an image or a pull, and refuses one of
its names set in a step's env or by a script's assignment, and a `continue-on-error`, `shell` or `working-directory`
key or a step's `if`. `scripts/tests/test_mirror_ci_images.py` holds the cases
the rule refuses and runs the copy step's and the proof's scripts under bash with stub `skopeo`, `curl` and `git`, one
case for each kind of red and green above. And the test refuses a `credentials` key in any workflow,
`persist-credentials` apart, and a declared grant that can write a package anywhere but the copier's `copy` job. A
workflow that declares no permissions takes the repository's default token, which the text cannot show, so the owner
keeps this repository's default workflow permission read only.

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
