# Design note — migrate GitHub PATs to a GitHub App (+ Vercel master auto-rotation)

**Status: ACCEPTED — App created & live; the E2E test-run engine (`run-e2e`) is fully migrated (un-gated App token); its provisioner (`ops-setup-e2e.yml`) + the rotation/kit surface are still flag-gated.**
The owner approved retiring the long-lived GitHub PATs in favour of a GitHub App that mints ephemeral,
scoped installation tokens. The App now **exists and is in production use**: the Tier-2 E2E engine
(`.github/actions/run-e2e`) mints its App token on **every** run with **no feature flag** (landed under
ADR **D-007**; see the table below), so the App's ID + private key are live secrets. The **rotation/kit
surface** (the original `CICD_PAT` automation) still mints its App token **behind the `USE_GITHUB_APP`
flag with a `CICD_PAT` fallback**, so the last remaining rollout step there is flipping (or confirming)
that repo variable on `kriegerdataforge-cicd`. **Phase 2** (the CI-runner + Vercel-build
`GH_PACKAGES_PAT`) is scoped below and still deferred — though the E2E engine already App-ifies its own
private-SDK clone (`run-e2e/action.yml:144`), proving the CI-runner half is feasible.

> **Note:** the former dormant registry-checkout PAT was **retired/removed on 2026-06-30**. It was only a
> `|| github.token` fallback for checking out the **public** cicd repo, which `github.token` already
> covers — it was never App-ified, just deleted from the registry. It plays no part in this migration.

## Decisions (resolved)

1. **Migrate to a GitHub App** — approved.
2. **Token lifetime** — keep the GitHub default of **1 hour nominal**. GitHub fixes the installation-token
   TTL at 1 hour and exposes *no* knob to shorten it; we don't need one, because
   `actions/create-github-app-token` **revokes the token in a post-job step**, so the real exposure window
   is the job's runtime (minutes). Risk is bounded by *scope*, not time: every workflow mints **per-job**,
   scoped to `owner` and **downscoped** to the minimum permission (`permission-secrets`+`permission-environments: write`
   for the rotators, `permission-contents`/`permission-pull-requests: write` for kit distribution).
3. **Vercel SDK-install (Phase 2)** — chosen path: **option 1 now** (keep a single narrow `contents:read`
   PAT, monitored, for the Vercel build only), with **option 2 (publish the SDK to a registry)** as the
   clean long-term follow-up. Rationale below.

## Implementation status

### The E2E surface — test-run engine un-gated (App token always), provisioner flag-gated

Landed **after** this note under ADR **D-007** (E2E-as-a-per-repo-CI-job). The **`run-e2e` composite
action** mints its token **unconditionally**, so `USE_GITHUB_APP` is **vestigial for the E2E engine**
(D-007's recorded consequence). The **`ops-setup-e2e.yml` provisioner**, by contrast, still mints its App
token **behind `USE_GITHUB_APP` with a `CICD_PAT` fallback** — exactly like the rotation surface below —
so only the `run-e2e` action row is truly un-gated (each row's own **Gate** column, not this heading, is
authoritative).

| Workflow / action | Token | Scope | Gate |
|---|---|---|---|
| `.github/actions/run-e2e` | App token (`contents:read`) | dynamic — the caller's `e2e/manifest.json` repos + shared identity repos + SDK (`run-e2e/action.yml:74-82`) | **none** — always App token |
| `ops-setup-e2e.yml` (E2E-repo provisioner) | App token (Secrets **+ Variables** write) | the single target repo via `repositories:` (`ops-setup-e2e.yml:93-101`) | `USE_GITHUB_APP` → `CICD_PAT` (`:95,105`); *writes* `USE_GITHUB_APP=true` into the target for parity (`:11,109`) |

### Flag-gated — the rotation/kit surface (App token when `USE_GITHUB_APP=true`, else `CICD_PAT`)

Unchanged from this note's original Phase 1:

| Workflow | Token after | Gate + fallback (`file:line`) |
|---|---|---|
| `ops-rotate-secrets.yml` | App token (`secrets`+`environments:write`) → `CICD_PAT` | `:64`, `:123` |
| `rotate-vercel-tokens.yml` | App token (rotate job `secrets`+`environments:write`; PR job `contents`+`pull-requests:write`) → `CICD_PAT` | `:72`,`:112`, `:87`/`:127`/`:142` |
| `distribute-gh-pat.yml` | App token (`secrets:write`) → `CICD_PAT` | `:61`, `:73` |
| `distribute-kit.yml` | App token (`contents`+`pull-requests:write`) → `CICD_PAT` | `:77`, `:90` |
| `ops-distribute-kit.yml` | App token (`contents`+`pull-requests:write`) → `CICD_PAT` | `:55`, `:111` |
| `issue-create-repo.yml` | `CICD_PAT` (unchanged) | the CICD_PAT holdout (see below) |

On the flag-gated surface each minting step is gated on the **`USE_GITHUB_APP`** repo *variable*
(`if: vars.USE_GITHUB_APP == 'true'`) and falls back to `CICD_PAT`
(`${{ steps.app-token.outputs.token || secrets.CICD_PAT }}`), so unsetting the variable is an **instant
rollback**. Note the split the two tables draw out: the E2E action **ignores** this flag (it always mints
an App token), which is exactly why D-007 records `USE_GITHUB_APP` as vestigial for E2E even as
`ops-setup-e2e.yml` keeps writing `USE_GITHUB_APP=true` into each provisioned tenant repo "for parity."

**The CICD_PAT holdout.** `issue-create-repo.yml` provisions new repos. Creating a repo under a *personal
account* requires a user-to-server PAT; a GitHub App **installation token cannot create user-account
repos**. So this one workflow keeps `CICD_PAT` until the planned **org move**, after which the App's
org-level *Administration* permission can create repos and `CICD_PAT` can be fully retired. It is
owner-only and rarely run, so the residual exposure is minimal.

The new standing secrets are **`KDF_APP_ID`** (not sensitive) and **`KDF_APP_PRIVATE_KEY`** (a `.pem`,
stored as a cicd repo secret and monitored in `secret_registry.json`). Setup steps:
[`docs/guides/MANUAL_SETUP.md` → "GitHub App (ephemeral tokens)"](../guides/MANUAL_SETUP.md). Private-key
rotation recipe: [`SECRET_ROTATION.md` §8.3a](../guides/SECRET_ROTATION.md).

---

## Problem

The ecosystem authenticates GitHub automation with **fine-grained Personal Access Tokens**:

| PAT | Used by | Grants |
|---|---|---|
| `CICD_PAT` | issue assistant + the rotation engine | `secrets: write` + `administration` across the org repos |
| `GH_PACKAGES_PAT` | CI runners + Vercel builds | `contents: read` on the private SDK repo (to `pip install kdf-auth-sdk`) |

These are **long-lived (yearly)** and **GitHub has no API to mint a PAT** — so:

- "Monthly rotation" means **monthly manual toil** (recreate each PAT in the UI, 12×/year).
- More frequent manual handling of a raw secret is *more* leak surface, not less.
- Each PAT's expiry is a **single point of failure** — when `CICD_PAT` or the Vercel master lapses, the
  whole rotation/ops automation silently stops.

## Goal

No long-lived GitHub access tokens. Workflows should mint **short-lived, scoped, auto-issued** tokens on
demand — i.e. eliminate the PATs rather than rotate them more often (the higher-security pattern).

---

## Solution — a GitHub App

A GitHub App (org-owned) issues **installation access tokens** that:

- are minted via API from the App's **App ID + private key** (`actions/create-github-app-token`),
- **expire after ~1 hour** (mint a fresh one per workflow run),
- are scoped to specific repos + permissions.

So instead of three standing PATs, you hold **one App private key** that only ever mints ephemeral,
narrowly-scoped tokens. GitHub Apps support **multiple private keys**, enabling zero-downtime key rotation.

### Permission mapping (App replaces PAT)
| Today (PAT) | App permission | Installed on |
|---|---|---|
| `CICD_PAT` → write env secrets | **Environments: read/write** (environment secrets are gated by "Environments", NOT "Secrets") | all consumer repos |
| `GH_PACKAGES_PAT` → install the SDK | **Contents: read** | the private SDK repo |

The rotation engine writes **environment** secrets via the REST API with whatever token it's given — an
App installation token with `Environments: write` works unchanged (environment secrets are gated by the
"Environments" permission, **not** "Secrets"). The only standing secrets become **`KDF_APP_ID`** +
**`KDF_APP_PRIVATE_KEY`** (cicd repo secrets).

### The one hard wrinkle: SDK install on **Vercel** builds
`GH_PACKAGES_PAT` is also consumed by **Vercel** at build time (`installCommand` clones the private SDK).
Vercel builds don't run in GitHub Actions, so they can't call `create-github-app-token` themselves. Options
(decide during implementation):
1. **Keep one narrow `contents:read` PAT just for Vercel builds** — the smallest residual PAT, monitored as today.
2. **Publish the SDK to a registry** (GitHub Packages / private PyPI) and authenticate the build with a
   registry token instead of a repo PAT.
3. **Mint a short-lived App token in a pre-deploy GitHub Action** and pass it to the Vercel build as a
   one-shot env (more moving parts).

> The GitHub-Actions-side PAT (`CICD_PAT`) is easy to App-ify. The Vercel-build-side
> `GH_PACKAGES_PAT` is the part that needs a decision — option 2 (registry) is the cleanest long-term.

---

## Migration steps (phased, reversible)

**Done — the App exists and is live.** The App has been created (account-owned for now) granting at least
**Secrets / Environments / Contents / Pull-requests R/W** plus **Variables** write (the permissions the
minted tokens request — `contents:read` for `run-e2e`, Secrets+Variables write for `ops-setup-e2e.yml`,
`secrets`+`environments:write` for the rotators, `contents`+`pull-requests:write` for kit distribution); a
private key was generated and
installed on the ecosystem repos. `KDF_APP_ID` + `KDF_APP_PRIVATE_KEY` are `kriegerdataforge-cicd` repo
secrets (`KDF_APP_PRIVATE_KEY` monitored — tracked expiry 2026-12-29 in the registry, manual rotation — in `secret_registry.json:118-140`).
The E2E engine mints App tokens on every run and `ops-setup-e2e.yml` copies the App secrets into each
journey repo. Setup walkthrough: `MANUAL_SETUP.md`; key-rotation recipe: `SECRET_ROTATION.md §8.3a`.

**Remaining — flip the flag for the rotation/kit surface** (one-time; unset for instant rollback):

1. Set the `kriegerdataforge-cicd` repo **variable** `USE_GITHUB_APP=true` so the five rotation/kit
   workflows (table above) start minting App tokens instead of falling back to `CICD_PAT`.
2. **Verify** by running a flow (e.g. *Check Secret Expiry*, or a *Rotate Vercel Deployment Token* dry
   run). If anything misbehaves, unset `USE_GITHUB_APP` for an instant rollback to `CICD_PAT`.
3. Once confident, **revoke** the standalone `CICD_PAT` *capabilities the App now covers* — but keep the
   PAT itself until the org move (it still backs `issue-create-repo.yml`).

**Phase 2 (deferred):** App-ify the general CI-runner SDK install (`ci-python-*.yml`) and pick the Vercel
SDK-install path (option 1 now / option 2 long-term) to retire `GH_PACKAGES_PAT`. The E2E engine already
proves the CI-runner half works — its image build clones the private SDK using the minted App token as
`GH_PACKAGES_PAT` (`run-e2e/action.yml:144`) — but generalising that to every consumer's reusable workflow
(`secrets: inherit`) and resolving the Vercel-build path is still staged work.

Cost: $0 (GitHub Apps are free).

---

## Related future enhancement — auto-rotate `VERCEL_MASTER_TOKEN`

Unlike PATs, the Vercel master token **can** be minted via API, so monthly auto-rotation is feasible — but
deferred because of one unknown and one self-modification concern:

- **Scope-preservation (unknown):** `kdf-master-rotation` needs **Full Account** scope to call
  `/v3/user/tokens` (team-scoped tokens get 403). It's unverified whether a token *created via that API*
  inherits Full Account scope. If it doesn't, an auto-minted master couldn't itself rotate tokens → the
  chain breaks next cycle.
- **Self-modification:** rotating the master means writing the cicd repo's **own** `VERCEL_MASTER_TOKEN`
  repository secret mid-run (needs a `update_github_repo_secret` helper + the App/PAT write token).

**Proposed fail-safe design** (when built): mint new master → **verify** it can create *and* delete a
throwaway token (proves Full Account scope) → only then write it to the repo secret and delete the old one
→ on any failure, delete the new token, keep the old, and exit non-zero so the expiry monitor opens an
issue. This degrades safely to today's reminder behavior if the API scope assumption is wrong.

**Recommendation:** verify the Vercel API scope behavior once by hand, then implement the fail-safe
auto-rotation; until then the master stays on the monitored/reminder path (`SECRET_ROTATION.md` §8.4).

---

## Decisions

1. ✅ **Approved + live** — migrated to a GitHub App. The E2E surface runs on **un-gated** App tokens
   (ADR D-007); the rotation/kit surface is **flag-gated** behind `USE_GITHUB_APP` with a `CICD_PAT`
   fallback, pending the flag flip on `kriegerdataforge-cicd`.
2. ✅ **Resolved** — Vercel SDK-install: option 1 (narrow `contents:read` PAT) now, option 2 (registry)
   as the long-term follow-up. Tracked as Phase 2 (still deferred).
3. ⬜ **Still open** — approve building the fail-safe `VERCEL_MASTER_TOKEN` auto-rotation, or keep it
   reminder-only. (Unchanged; depends on the one-time Vercel-API scope check above.)
