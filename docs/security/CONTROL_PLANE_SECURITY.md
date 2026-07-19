# Security model & threat posture of the CI/CD control plane

**Repo:** `kriegerdataforge-cicd` · **Audience:** the owner, collaborators onboarding into deploy
rights, and anyone auditing how KDF's automation authorizes actions and handles credentials.

This document is the source-of-truth **security reference** for the control plane itself — the
reusable workflows, composite action, Python gate scripts, and JSON registries that every tenant
repo calls live from `@main`. It catalogs each control, grounds it in the real file that
implements it (`file:line`), and states the **fail mode**. It is a reference, not a runbook: for
*how to rotate a secret* see [`../guides/SECRET_ROTATION.md`](../guides/SECRET_ROTATION.md); for
*who can deploy* the live data is [`scripts/deployer_registry.json`](../../scripts/deployer_registry.json).

> **No secret values appear here.** Every credential is referenced by **name and location** only,
> per [`SECURITY.md`](../../SECURITY.md) and the ecosystem playbook. No `tfstate`/`tfplan`,
> `.pem`, or token value is read or shown.

---

## 1. Overview — what the control plane is, and who consumes it

`kriegerdataforge-cicd` is the **centralized, public CI/CD platform library** for the KDF
ecosystem. Deploy behavior, security gates, version discipline, and secret handling are defined
**once** here and every tenant repo's `cd.yml` is a thin caller
(`uses: Needless2Say/kriegerdataforge-cicd/.github/workflows/<wf>.yml@main` + `secrets: inherit`)
(`AGENTS.md:16-18`). Consumers: `kriegerdataforge` (hub), `kriegerdataforge-auth-ui`,
`fitness-app-{frontend,backend}`, `tiffanys-space{,-backend}`, `kriegerdataforge-terraform`,
`arthurs-portfolio`, and the `kriegerdataforge-template-{fastapi,nextjs}` scaffold repos
(`scripts/deployer_registry.json:3-43` — ten entries in all).

Because the surface is automation and supply-chain integrity, the security model is built from a
small number of **fail-closed gates** and **least-privilege credential flows** rather than a
network perimeter. The in-scope surface is enumerated in [`SECURITY.md:38-39`](../../SECURITY.md):
third-party action/CLI pinning, the Environment approval gates plus the fail-closed deployer gate,
least-privilege `permissions:`, the owner-gated privileged-ops workflows, and the secret-scanning
backstops.

## 2. Trust boundaries & threat model

| Boundary / assumption | Consequence | Where enforced |
| --- | --- | --- |
| **This repo is public.** Anyone can read the workflows and open an issue. | *Authorization, not obscurity,* is the control. Every privileged path re-checks identity server-side. | `_authorize-owner.yml:5-12`; `ops-setup-e2e.yml:5-7` |
| **GitHub cannot restrict *who* may `workflow_dispatch`** — any collaborator with write access can click "Run workflow". | Deploy authorization is enforced *in-workflow* against an allow-list, not by repo permissions. | `check_deployer.py:4-9` |
| **First-party + sister-tenant trust.** The hub and tenant repos are the owner's; the boundary is between the KDF ecosystem and the outside world, and between *tenants* (one tenant can't arm another). | Ops workflows validate targets against fixed allow-lists; the E2E engine scopes tokens to just the journey's repos. | `ops-setup-e2e.yml:73-78`; `run-e2e/action.yml:74-82` |
| **A reusable workflow change ripples to all consumers at once** (`@main`). | Interface changes are breaking-change candidates; the version gate + pinning defend integrity. | `AGENTS.md:64-68`; `SECURITY.md:38-39` |
| **The control plane never holds *app* data.** It moves credentials and orchestrates deploys; it does not read user data or app databases. | Secret-scoping/least-privilege is the whole game; there is no PII surface here. | — |

The rest of this document is the **control catalog**: each control names the threat it closes and
the exact file that implements it.

---

## 3. Control catalog

### C1 — Ephemeral, least-privilege GitHub-App tokens (auto-revoked at job end)

**Threat closed:** long-lived broad PATs sitting in CI, over-scoped to every repo, surviving well
beyond the job that used them.

Privileged and cross-repo jobs mint a **short-lived GitHub App installation token** via
`actions/create-github-app-token` (pinned to the v3.2.0 commit SHA `bcd2ba49…` since PR #148; the
one remaining v2.2.2 `fee1f7d…` pin is `run-e2e/action.yml:76` — a known follow-up, not fixed in
this docs pass) instead of a standing PAT. The action **auto-revokes the token when the job ends**, so the real exposure window
is the job's runtime (minutes), not the 1-hour nominal TTL (`ops-rotate-secrets.yml:53-71`). Two
axes of least privilege are applied:

- **Permission scoping.** The rotation job requests exactly `permission-secrets: write` +
  `permission-environments: write` — the two grants the engine needs to write repo-level secrets
  and delete retired per-environment shadows (`ops-rotate-secrets.yml:62-71`).
- **Repository scoping.** The E2E engine mints a token with `permission-contents: read` scoped to
  *only* the repos this journey needs — resolved dynamically from the caller's manifest, never a
  hardcoded tenant list (`run-e2e/action.yml:74-82`, `47-72`).

The private key + App ID are themselves referenced by name only (`secrets.KDF_APP_ID`,
`secrets.KDF_APP_PRIVATE_KEY`) and never inlined; the App private key is registered as a monitored,
manually-rotated credential (`secret_registry.json:118-140`).

> **Least-privilege nuance (documented, not a gap).** `ops-setup-e2e.yml` mints a token with **no**
> per-permission filter, because `create-github-app-token@v3.2.0` still has no `permission-variables`
> input and the job must write both Secrets *and* Variables; it is instead scoped to the **single**
> target repo via `repositories:` (`ops-setup-e2e.yml:86-101`). Scoping is by-repo there, not
> by-permission.

### C2 — Deployer-registry fail-closed gate + Environment protection (defense in depth)

**Threat closed:** a collaborator with repo write access dispatching a deploy to an environment
they aren't approved for — including self-approving on `dev`, where a collaborator is a valid
Environment reviewer.

Every reusable CD workflow (`cd-nextjs-vercel.yml`, `cd-python-vercel.yml`, `cd-terraform.yml`)
starts with an **`authorize` job that the deploy/apply job `needs:`**. Crucially, `authorize` has
**no `environment:`**, so it runs *before* the GitHub Environment approval is even requested — an
unauthorized dispatch fails fast, with no approval notification and no secrets loaded
(`cd-python-vercel.yml:59-92`, `cd-nextjs-vercel.yml:47-80`, `cd-terraform.yml:113-145`).

The `authorize` job checks out this repo (sparse — `scripts/` only) and runs
[`check_deployer.py`](../../scripts/check_deployer.py), passing the **dispatching user** as
`DEPLOY_ACTOR` (`github.triggering_actor`) and the target `DEPLOY_ENVIRONMENT`
(`cd-python-vercel.yml:65-82`). The script looks the actor up in
[`deployer_registry.json`](../../scripts/deployer_registry.json), keyed `repo → environment →
[usernames]`, matching case-insensitively (`check_deployer.py:92-93`).

**Fail-closed decision table** (`check_deployer.py:65-100`):

| Condition | Result |
| --- | --- |
| Repo not in registry | DENY — exit 1 (`check_deployer.py:77-82`) |
| Environment not listed for that repo | DENY — exit 1 (`check_deployer.py:84-90`) |
| Actor not in the approved list | DENY — exit 1 (`check_deployer.py:96-100`) |
| Actor in the approved list | ALLOW — exit 0 (`check_deployer.py:93-94`) |

The gate is layered *behind* the **GitHub Environment approval gate**, which pauses the deploy for
a required reviewer and only then loads environment-scoped secrets. The approval model — `prod` /
`infra` owner-only, `dev` owner + collaborator — is a repo-side GitHub Environment configuration
(documented in [`../reference/WORKFLOWS.md`](../reference/WORKFLOWS.md#deployment-model--overview));
`environment: ${{ inputs.environment }}` on the deploy job is what activates it
(`cd-python-vercel.yml:92`). Registry environment keys **must** match the input value the caller
passes (`dev`/`prod`/`github-pages`) (`deployer_registry.json:2`, `AGENTS.md:72-73`).

`check_deployer.py` is standard-library only and unit-tested
(`scripts/tests/test_check_deployer.py`). To change who can deploy, edit the registry and commit —
all consumers read it live from `main` at deploy time (`deployer_registry.json:2`).

### C3 — Owner-only fail-closed gate for privileged "Ops Console" workflows

**Threat closed:** anyone (public repo → anyone can open an issue) triggering a workflow that runs
with broad org-wide credentials by adding a label.

The issue-triggered ops workflows (`ops-rotate-secrets.yml`, `ops-setup-e2e.yml`, and the
kit-distribution ops workflow) each call the reusable `_authorize-owner.yml` as a job and `needs:`
it. That gate compares `github.triggering_actor` (not the frozen `github.event.sender.login`, so a
"Re-run" is attributed to whoever re-ran it) against `github.repository_owner`, case-insensitively,
and **fails closed (`exit 1`)** on any mismatch or empty actor (`_authorize-owner.yml:31-49`). It
exports an `authorized` output, and the privileged job additionally guards on
`needs.authorize.outputs.authorized == 'true'` (`ops-rotate-secrets.yml:26-36`,
`ops-setup-e2e.yml:38-48`).

Untrusted issue-form bodies are handled as **data, never code**: the body is read into an env var
and parsed with `awk` as DATA, never inlined into a shell string
(`ops-rotate-secrets.yml:73-99`, `ops-setup-e2e.yml:54-67`). `mode`/`confirm` fields are
allow-listed and destructive modes require an explicit `Confirm = Yes`
(`ops-rotate-secrets.yml:92-113`).

### C4 — Secret handling: never echoed to logs, never baked into an image layer

**Threat closed:** a credential leaking through a build log line, a comment on a public issue, an
image layer that ships the token, or a stale environment-scoped copy shadowing a rotated value.

**Never echoed / never in a comment.** Deploy code logs only the *length* of the Vercel token, never
its value (`cd-python-vercel.yml:144-153`). Ops workflows post **metadata-only** issue comments and
explicitly rely on GitHub masking registered secrets in the (public) Actions log; the comment body
is hand-built and secret-free (`ops-rotate-secrets.yml:11-14, 149-165`; `ops-setup-e2e.yml:22-24`).
When copying App secrets between repos, values are piped via **stdin** so the multi-line PEM is
never argv-visible (`ops-setup-e2e.yml:111-121`). The PAT resolver in the E2E driver is documented
"Never logged" (`e2e/ci_stack.py:212-225`).

**Never baked into an image layer (BuildKit `--mount=type=secret`).** The E2E stack builds tenant
backend images that must clone the private SDK. The `GH_PACKAGES_PAT` is delivered as a **BuildKit
build secret**, not a build `ARG` and not an env baked into a layer. The shared compose declares a
`secrets:` block sourced from the `GH_PACKAGES_PAT` env var and mounts it (tmpfs) into the build —
"never an image layer or a build-log line" (`e2e/docker-compose.shared.yml:113-119`); each build
that needs it opts in with `secrets: [gh_packages_pat]` (`e2e/docker-compose.shared.yml:44-46`).
The composite action reinforces this: after the shallow clone of each sibling repo it **strips the
credentialed remote** from `<repo>/.git/config`, precisely so a later Docker `COPY . .` build
context can't bake the token into a layer and regress the `--mount=type=secret` hardening
(`run-e2e/action.yml:107-111`). The App token doubling as `GH_PACKAGES_PAT` is auto-masked by
Actions (`run-e2e/action.yml:142-144`).

**Repo-level vs environment-scoped shadowing.** The rotation registry encodes a subtle invariant:
the singular tokens (`GH_PACKAGES_PAT`, `VERCEL_DEPLOYMENT_TOKEN`) live **only** at repository level,
because a same-named environment secret would *shadow* the repo value (env wins over repo). The
engine tracks `retired_github_env_secrets` and **deletes** those env-level copies on rotation,
revoking the old token only after every shadow is gone (`secret_registry.json:2, 9, 66-81`).

**Rotation engine + guardrails.** `rotate_secret.py` + `secret_registry.json` are the single source
of truth. App-plane (Terraform-owned) secrets are **refused** by a `terraform_managed` guard so a
direct write can't drift infra state (`ops-rotate-secrets.yml:15`; `secret_registry.json:2`).
Paste-mode requires the value be staged in the `SECRET_VALUE_NEW` repo secret first — the issue only
*names* the secret (`ops-rotate-secrets.yml:11-13, 134-138`).

**Expiry watchdog.** A weekly cron (`Mon 09:00 UTC`) runs `rotate_secret.py --mode check` — which
reads **only** the registry's expiry metadata, no secret values — and maintains one deduplicated
tracking issue, auto-closing it when everything is healthy (`check-secret-expiry.yml:1-16, 41-96`).
Auto-mintable Vercel tokens self-heal; the PATs and the Vercel master token are flagged as
hand-rotated because no API can mint them (`secret_registry.json:84-96`).

**CI SDK-auth git credential.** Where a CI job must resolve the private SDK, the token is injected
via `git config insteadOf` from `secrets.GH_PACKAGES_PAT` only when `needs_sdk_auth` is set — never
unconditionally (`ci-python-security.yml:54-57`; `cd-python-vercel.yml:110-115`).

**Dual-store reports-cron secrets.** The reports-triage trigger authenticates to each app's
`POST /reports/triage/cron` with an `X-Cron-Secret` value held as a cicd-side **copy**
(`REPORTS_CRON_SECRET_FITNESS_APP` / `REPORTS_CRON_SECRET_TIFFANYS_SPACE`) of the Terraform-owned
app-side secret; the app side is **authoritative** — rotate there first, then paste the same value
here (`secret_registry.json:141-162`). Both halves fail closed: the trigger engine refuses to POST
until the cicd copy is set, and the endpoint answers 503 until the app-side value exists (PL-056).
The rotation recipe is [`SECRET_ROTATION.md`](../guides/SECRET_ROTATION.md) §8.13a and the ops
runbook is [`REPORTS_TRIAGE_OPS.md`](../guides/REPORTS_TRIAGE_OPS.md) — cross-referenced here
rather than duplicated.

### C5 — Strict +1 version discipline

**Threat closed:** silent, unversioned changes to a library every consumer runs from `@main`;
ambiguous or skipped releases that make rollback and provenance unclear.

`bump-version-check.yml` validates on every PR that the `VERSION` file is **exactly one** valid
semver increment ahead of `main` — patch `X.Y.Z+1`, minor `X.Y+1.0`, or major `X+1.0.0`. It reads
`origin/main:VERSION` as the base, parses both to `(maj, min, pat)` tuples, and accepts the head
**only** if it equals one of the three allowed successors; **no bump, skip-by-2, downgrade, or bad
format fails the job** (`bump-version-check.yml:88-115`). Versions are hand-edited and gated — CI
never auto-increments (`bump-version-check.yml:12-14`); the house rule is to always use
`make bump-<level>` and never hand-edit (`AGENTS.md:97-99, 145`). This discipline is what makes a
tagged deploy (`ref: v${{ inputs.version }}`, `cd-python-vercel.yml:99-103`) and a rollback ("specify
an older version") unambiguous.

### C6 — Supply-chain integrity: pinning + verified tool download

**Threat closed:** a poisoned action/CLI tarball executing inside a job that holds prod
credentials (CICD-SEC-3 / SLSA class).

- **Third-party actions pinned to a specific tag or full commit SHA**, never `@main`/`@latest`
  (policy: `AGENTS.md:62` rule #2, `SECURITY.md:38-39`) — and in practice every third-party action
  is pinned to a **full commit SHA** with a version comment, e.g. `actions/checkout@9c091bb…` (`# v7.0.0`),
  `create-github-app-token@bcd2ba49…` (`# v3.2.0`) (`cd-python-vercel.yml:66`, `ops-rotate-secrets.yml:65`).
- **The Vercel CLI is pinned to an exact version** (`vercel@48.0.0`) precisely because that job
  holds `VERCEL_DEPLOYMENT_TOKEN`, `GH_PACKAGES_PAT`, and (on migrations) `DB_DATABASE_URL`; an
  unpinned floating install is called out as a dependency-chain risk (`cd-python-vercel.yml:134-139`).
- **The conftest binary is verified against a pinned `sha256` before it is extracted or executed**,
  because that Terraform step holds prod secrets and a tampered release must never run
  (`cd-terraform.yml:251-267`).

### C7 — Tenant-agnostic trust boundary (a repo depends only on what it consumes)

**Threat closed:** the shared control plane accumulating per-tenant secrets, lists, or code — which
would both bloat it and make one tenant's blast radius the whole ecosystem's.

Critical rule #12: *this repo is the reusable engine ONLY — nothing tenant-specific lives here*; if
onboarding a new tenant would require editing a file here, the file must be made data-driven instead
(`AGENTS.md:77-83`). The E2E engine is the worked example: the composite action reads the **caller's**
`e2e/manifest.json` to discover which *other* repos the journey needs, so it never hardcodes a tenant
list, and mints its App token scoped to exactly that discovered set plus the shared identity repos
and the SDK (`run-e2e/action.yml:47-82`). A tenant thus depends only on its own downstream
dependency subgraph; the App secrets it is armed with are validated against a **fixed allow-list of
the six E2E-journey repos** and copied nowhere else (`ops-setup-e2e.yml:71-78`). ADR **D-006**
captures the decoupling (`docs/design/e2e-test-decoupling.md`); its follow-on ADR **D-007**
(`docs/design/e2e-cijob-refactor.md`) reshapes the E2E into a per-repo CI job — both recorded in
`docs/CHANGELOG_AND_DECISION_LOG.md`.

The engine also **fails closed on an empty gate**: after `npm test`, the N2e guard asserts at least
one Playwright test actually ran, refusing a green-but-empty result that would prove nothing
(`run-e2e/action.yml:160-178`).

### C8 — OIDC-RP drift guard (PL-084) — a monitored cross-repo credential use

**Threat closed:** the copy-pasted OIDC relying-party core (`oidc.ts` + the callback/initiate/logout
route cores) silently diverging between the two tenant frontends — a security fix landing in one app
and not the other — until the shared `@kriegerdataforge/oidc-rp` package is extracted
(owner-deferred post-launch).

`check-oidc-rp-drift.yml` (PR #145; weekly cron Mon 12:30 UTC + `workflow_dispatch`) runs
`scripts/check_oidc_drift.py`, which compares each pair in `scripts/oidc_drift_manifest.json` across
`fitness-app-frontend` and `tiffanys-space`. This is a deliberate **cross-repo credential use**: both
frontends are private, so the reads authenticate with a minted App token (`permission-contents:
read`, gated on `USE_GITHUB_APP`) falling back to `CICD_PAT` (`check-oidc-rp-drift.yml:42-58`).
Output is **metadata-only** — paths + changed-line counts, never file contents, so the tracking
issue in this public repo can't leak private code — and the workflow maintains one deduplicated
`ops:oidc-rp-drift` issue that auto-closes when all pairs are identical again
(`check-oidc-rp-drift.yml:7-13, 76-124`).

---

## 4. Least-privilege permissions matrix

Every workflow sets the minimum `permissions:` (`AGENTS.md:69`; rule #6). `id-token: write` is
granted **only** where Vercel OIDC needs it.

| Workflow / job | `contents` | `id-token` | `issues` | Notes |
| --- | --- | --- | --- | --- |
| `cd-nextjs-vercel.yml` → `authorize` | read | — | — | no `environment:` → runs before approval (`cd-nextjs-vercel.yml:47-51`) |
| `cd-nextjs-vercel.yml` → `deploy` | read | write | — | OIDC (`cd-nextjs-vercel.yml:82-84`) |
| `cd-python-vercel.yml` → `deploy` | read | write | — | `cd-python-vercel.yml:94-96` |
| `cd-terraform.yml` → `apply` | read | — | — | `cd-terraform.yml:147` |
| `bump-version-check.yml` | read | — | — | `bump-version-check.yml:31-33` |
| `_authorize-owner.yml` | read | — | — | `_authorize-owner.yml:21-23` |
| `ops-rotate-secrets.yml` → `run` | read | — | write | issues:write to comment result (`ops-rotate-secrets.yml:38-40`) |
| `ops-setup-e2e.yml` → `setup` | read | — | write | `ops-setup-e2e.yml:50-52` |
| `check-secret-expiry.yml` | read | — | write | maintains the tracking issue (`check-secret-expiry.yml:18-20`) |
| `check-oidc-rp-drift.yml` | read | — | write | cross-repo reads via App token / `CICD_PAT` fallback (`check-oidc-rp-drift.yml:20-22, 42-58`) |

The `run-e2e` composite action requests no permissions of its own — it runs under the **caller
job's** permissions and derives all cross-repo access from its minted, scoped App token
(`run-e2e/action.yml:34-36, 74-82`).

---

## 5. Live vs. advisory / not-yet-fully-enforced (accuracy call-outs)

These are current-state facts a reader must not over-read. They are **not** fixed here (docs-only
task); they are recorded for the owner in the summary.

1. **The Terraform invariant policy gate is ADVISORY today.** The conftest/OPA step runs with
   `continue-on-error: true`, and the `prod_guard` rules are `warn` (conftest exits 0), so it
   surfaces violations in the log but **does not block a misconfigured prod apply** yet. The
   flip-to-deny is gated on PL-014 (Upstash Redis) and PL-051 (prod Stripe) closing out
   (`cd-terraform.yml:226-267`). Until the flip, C6's policy check is observ­ability, not enforcement.
2. **The App-token migration is flag-gated with a broad PAT fallback.** `ops-rotate-secrets.yml`
   and `ops-setup-e2e.yml` mint the scoped App token **only when `vars.USE_GITHUB_APP == 'true'`**;
   otherwise they fall back to `secrets.CICD_PAT` (`ops-rotate-secrets.yml:62-64, 123`;
   `ops-setup-e2e.yml:93-95, 105`). `CICD_PAT` carries full Administration/Contents/Environments/
   Secrets/Variables/Actions/Issues/PRs read-write over **all** repos on a 30-day manual expiry
   (`secret_registry.json:84-89`). So the least-privilege story (C1) is fully realized only with the
   flag on; with it off, these ops run under the broad PAT.
3. **The deployer-gate checkout depends on this repo being public.** The `authorize` job clones the
   registry using the caller's default `github.token`, which works only because
   `kriegerdataforge-cicd` is public. If it goes private after the org move, that checkout needs a
   read-only token — already flagged in-code and in the central roadmap
   (`cd-python-vercel.yml:72-75`).
4. **`ops-setup-e2e.yml` per-repo secret copy is a pre-org-move stopgap.** Once `KDF_APP_*` become
   org secrets, the per-repo copy is obsolete and should be retired
   (`ops-setup-e2e.yml:16-21`).

---

## 6. Related

- [`../reference/WORKFLOWS.md`](../reference/WORKFLOWS.md) — the full per-workflow contract
  (inputs/secrets/outputs/callers) and the deployment/Environment-gate model.
- [`../guides/SECRET_ROTATION.md`](../guides/SECRET_ROTATION.md) — how to rotate a repo/environment
  secret via `rotate_secret.py` + `secret_registry.json`.
- [`../guides/MANUAL_SETUP.md`](../guides/MANUAL_SETUP.md) — GitHub Environments, environment
  secrets, PAT/token creation, tenant onboarding, org migration (the non-automatable half).
- [`../guides/E2E_TESTING.md`](../guides/E2E_TESTING.md) + [`../../e2e/README.md`](../../e2e/README.md)
  — the reusable E2E engine and its run modes.
- [`../design/github-app-migration.md`](../design/github-app-migration.md) — the design note behind
  C1 (retire long-lived PATs for ephemeral App tokens).
- [`../design/e2e-test-decoupling.md`](../design/e2e-test-decoupling.md) — ADR **D-006**, the
  tenant-agnostic boundary behind C7.
- [`../design/e2e-cijob-refactor.md`](../design/e2e-cijob-refactor.md) — ADR **D-007**, the follow-on
  that makes the E2E a per-repo CI job.
- [`../../SECURITY.md`](../../SECURITY.md) — disclosure process and the in-scope security surface.
