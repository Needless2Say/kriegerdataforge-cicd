# Design note — migrate GitHub PATs to a GitHub App (+ Vercel master auto-rotation)

**Status: PROPOSED — for owner review.** Not yet implemented. This captures the recommended path to
eliminate the long-lived GitHub PATs and to fully automate the Vercel master-token rotation, so it can be
reviewed and scheduled later.

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

1. Create the org-owned GitHub App; set the permissions above; generate a private key; install it on the
   target repos.
2. Add `KDF_APP_ID` + `KDF_APP_PRIVATE_KEY` as `kriegerdataforge-cicd` repo secrets.
3. Update the rotation engine + workflows to mint an App token (`actions/create-github-app-token`) instead
   of consuming `CICD_PAT`; pick + implement the Vercel SDK-install option above.
4. **Verify** every flow (a secret rotation, a deploy, an SDK install) works on App tokens.
5. Remove `CICD_PAT` / `CICD_REGISTRY_PAT` (and `GH_PACKAGES_PAT` if option 2/3 chosen) from
   `secret_registry.json`'s monitored set; **revoke** the old PATs.
6. Update `SECRET_ROTATION.md` / `MANUAL_SETUP.md`; set a relaxed reminder for **App private-key** rotation.

Cost: $0 (GitHub Apps are free). Effort: ~½–1 day plus the Vercel-install decision.

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

## Decisions needed from the owner
1. Approve the GitHub App migration (eliminates the PAT rotation toil).
2. Choose the **Vercel SDK-install** approach (1 narrow PAT / 2 registry / 3 minted-token).
3. Approve building the fail-safe `VERCEL_MASTER_TOKEN` auto-rotation (or keep it reminder-only).
