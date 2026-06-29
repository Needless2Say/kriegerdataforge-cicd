# Design note — migrate GitHub PATs to a GitHub App (+ Vercel master auto-rotation)

**Status: ACCEPTED — Phase 1 implemented.** The owner approved retiring the long-lived GitHub PATs in
favour of a GitHub App that mints ephemeral, scoped installation tokens. **Phase 1** (the `CICD_PAT`
automation surface) is wired in code, behind a feature flag, and ready to switch on once the owner creates
the App. **Phase 2** (the CI-runner + Vercel-build `GH_PACKAGES_PAT` / `CICD_REGISTRY_PAT`) is scoped below
and deferred until Phase 1 is validated in production.

## Decisions (resolved)

1. **Migrate to a GitHub App** — approved.
2. **Token lifetime** — keep the GitHub default of **1 hour nominal**. GitHub fixes the installation-token
   TTL at 1 hour and exposes *no* knob to shorten it; we don't need one, because
   `actions/create-github-app-token` **revokes the token in a post-job step**, so the real exposure window
   is the job's runtime (minutes). Risk is bounded by *scope*, not time: every workflow mints **per-job**,
   scoped to `owner` and **downscoped** to the minimum permission (`permission-secrets: write` for the
   rotators, `permission-contents`/`permission-pull-requests: write` for kit distribution).
3. **Vercel SDK-install (Phase 2)** — chosen path: **option 1 now** (keep a single narrow `contents:read`
   PAT, monitored, for the Vercel build only), with **option 2 (publish the SDK to a registry)** as the
   clean long-term follow-up. Rationale below.

## Implementation status

| Workflow | Token before | Token after (Phase 1) |
|---|---|---|
| `ops-rotate-secrets.yml` | `CICD_PAT` | App token (`secrets:write`) → falls back to `CICD_PAT` |
| `rotate-vercel-tokens.yml` | `CICD_PAT` | App token (`secrets:write`) → falls back to `CICD_PAT` |
| `distribute-gh-pat.yml` | `CICD_PAT` | App token (`secrets:write`) → falls back to `CICD_PAT` |
| `distribute-kit.yml` | `CICD_PAT` | App token (`contents`+`pull-requests:write`) → falls back to `CICD_PAT` |
| `ops-distribute-kit.yml` | `CICD_PAT` | App token (`contents`+`pull-requests:write`) → falls back to `CICD_PAT` |
| `issue-create-repo.yml` | `CICD_PAT` | **unchanged** — the CICD_PAT holdout (see below) |

Each minting step is gated on the **`USE_GITHUB_APP`** repo *variable* and falls back to `CICD_PAT`
(`${{ steps.app-token.outputs.token || secrets.CICD_PAT }}`), so **merging Phase 1 changes nothing** until
the owner creates the App and flips the flag — and unsetting the variable is an **instant rollback**.

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
| `CICD_REGISTRY_PAT` | package registry access | registry read/write |

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
| `CICD_PAT` → write secrets/envs | **Secrets: read/write**, **Environments: read/write**, **Actions: read/write**; **Administration: read/write** only if repo provisioning needs it | all consumer repos |
| `GH_PACKAGES_PAT` → install the SDK | **Contents: read** | the private SDK repo |
| `CICD_REGISTRY_PAT` → packages | **Packages: read/write** (if still needed) | the relevant repos |

The rotation engine writes secrets via the REST API with whatever token it's given — an App installation
token with `Secrets: write` works unchanged. The only standing secrets become **`KDF_APP_ID`** +
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

> The GitHub-Actions-side PATs (`CICD_PAT`, `CICD_REGISTRY_PAT`) are easy to App-ify. The Vercel-build-side
> `GH_PACKAGES_PAT` is the part that needs a decision — option 2 (registry) is the cleanest long-term.

---

## Migration steps (phased, reversible)

**Owner, to switch Phase 1 on** (one-time, ~10 min — full walkthrough in `MANUAL_SETUP.md`):

1. Create the App (account-owned for now); grant **Secrets: R/W** + **Contents: R/W** +
   **Pull requests: R/W**; generate a private key; install it on the consumer repos.
2. Add `KDF_APP_ID` + `KDF_APP_PRIVATE_KEY` as `kriegerdataforge-cicd` repo secrets, then set the repo
   **variable** `USE_GITHUB_APP=true`.
3. **Verify** by running a flow (e.g. *Check Secret Expiry*, or a *Rotate Vercel Tokens* dry run). If
   anything misbehaves, unset `USE_GITHUB_APP` for an instant rollback to `CICD_PAT`.
4. Once confident, **revoke** the standalone `CICD_PAT` *capabilities the App now covers* — but keep the
   PAT itself until the org move (it still backs `issue-create-repo.yml`).

**Already done in code (this PR):** the five rotation/kit workflows mint App tokens behind the
`USE_GITHUB_APP` flag with a `CICD_PAT` fallback; `KDF_APP_PRIVATE_KEY` added to `secret_registry.json`
(monitored); `SECRET_ROTATION.md` §8.3a + `MANUAL_SETUP.md` Phase 6.7 setup written.

**Phase 2 (deferred):** App-ify the CI-runner SDK install (`ci-python-*.yml`) and pick the Vercel
SDK-install path (option 1 now / option 2 long-term) to retire `GH_PACKAGES_PAT` and `CICD_REGISTRY_PAT`.
This needs the App secrets plumbed into every consumer repo (reusable-workflow `secrets: inherit`) and the
Vercel-build decision, so it is staged after Phase 1 is proven.

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

1. ✅ **Approved** — migrate to a GitHub App (Phase 1 implemented in this PR).
2. ✅ **Resolved** — Vercel SDK-install: option 1 (narrow `contents:read` PAT) now, option 2 (registry)
   as the long-term follow-up. Tracked as Phase 2.
3. ⬜ **Still open** — approve building the fail-safe `VERCEL_MASTER_TOKEN` auto-rotation, or keep it
   reminder-only. (Unchanged; depends on the one-time Vercel-API scope check above.)
