# Secret Rotation — runbook

How to rotate the **GitHub Actions secrets** used across the KriegerDataForge ecosystem —
both **repository secrets** and **environment secrets** — using the unified rotation engine
where possible and by hand where it isn't.

> This is the *rotation* runbook. For the one-time *initial* provisioning of every secret see
> [`MANUAL_SETUP.md`](./MANUAL_SETUP.md). For **app-plane** secrets owned by Terraform
> (DB URLs, the RS256 keypair, `KDF_SERVICE_KEY`, `STRIPE_*`, OIDC client secrets, `CRON_SECRET`)
> see the terraform repo's `SECRETS_ROTATION` / `SECRETS_ROTATION_QUICKSTART` guides — **do not**
> rotate those with the tools here.

---

## 0. 🚨 Emergency — suspected leak or compromise

A credential was exposed (committed, pasted in a log/screenshot, shared, or seen at a third party).
Work top to bottom: **contain → rotate → verify → record.**

### Immediate (first ~15 minutes)
1. **Confirm scope** — which secret, where it leaked, and since when (so you know the exposure window).
2. **Revoke the leaked credential at its source *now*** — don't wait for the rotation to finish:
   - GitHub PAT → <https://github.com/settings/tokens> → the token → **Revoke**.
   - Vercel token → Vercel → **Account → Tokens** → **Delete**.
   - Neon / Stripe / Twilio / Resend → that provider's API-keys page → revoke or roll.
   Revoking breaks things until you re-rotate — for a *confirmed* leak that's the correct trade-off.
3. **Assess blast radius** (table below). A leaked **control-plane** credential can read/write other
   secrets, so its blast radius is "everything it could reach."
4. **Rotate** the secret **and everything in its blast radius** using the recipe in §8.
5. **Verify** (a `dev` deploy of each affected service) and **record** the incident: what leaked, when,
   the exposure window, and exactly what you rotated.

### Blast-radius triage
| Leaked secret | Severity | Also rotate | Recipe |
|---|---|---|---|
| `CICD_PAT` | 🔴 can write **every** secret | Treat all engine-written secrets as suspect: after §8.3, re-`generate` the `VERCEL_DEPLOYMENT_TOKEN` and re-`paste` `GH_PACKAGES_PAT` | §8.3 → §8.1 → §8.2 |
| `VERCEL_MASTER_TOKEN` | 🔴 full Vercel account | Re-`generate` the `VERCEL_DEPLOYMENT_TOKEN` (it can mint/delete tokens) | §8.4 → §8.1 |
| `AUTH_PRIVATE_KEY` | 🔴 signs every JWT | The whole RS256 group via Terraform, using an overlap window | §8.8 |
| `DB_DATABASE_URL` | 🔴 direct data access | The DB credential (Neon) + Terraform | §8.9 |
| `STRIPE_*` | 🔴 payments | Roll in Stripe + both consumers | §8.11 |
| `VERCEL_DEPLOYMENT_TOKEN` | 🟠 deploy + manage access across the account | The shared token (re-`generate`) | §8.1 |
| `GH_PACKAGES_PAT` | 🟠 read access to the private SDK repo | The PAT everywhere | §8.2 |
| `*_SERVICE_KEY` | 🟠 service-to-service auth | The key **and** the composite `SERVICE_API_KEYS` (one apply) | §8.10 |
| `KDF_OIDC_CLIENT_SECRET` | 🟠 one client's code exchange | Re-register that client | §8.12 |

> If you can't tell what a credential can reach, treat it as **critical** and rotate widely. Over-rotating
> costs a few deploys; under-rotating leaves a foothold.

---

## 1. Two kinds of GitHub secret (know which you're touching)

GitHub Actions has two secret scopes, and they rotate differently:

| | **Repository secret** | **Environment secret** |
|---|---|---|
| Scope | Every workflow run in that repo | Only jobs that declare `environment: <name>` — **after** the env's approval gate |
| Where | repo → Settings → Secrets and variables → **Actions → Repository secrets** | repo → Settings → **Environments → `<env>` → Environment secrets** |
| Used here for | The cicd **ops/control plane** (the master creds the rotation engine itself uses, + staging slots) | All **deploy/runtime** credentials in consumer repos (`prod` / `dev` / `infra`) |
| Rotated by | **By hand** (§4) — these authenticate the engine, so the engine can't rotate them | **The engine** when registered (§3), else by hand (§5) |

The cicd repo's deploy model keeps **deployment** credentials as *environment* secrets only (gated). The
only *repository* secrets are the ops-plane control creds below.

---

## 2. Inventory — what to rotate and how

### Repository secrets (in `kriegerdataforge-cicd`) — rotate by hand (§4)

| Secret | What it is | Notes |
|---|---|---|
| `CICD_PAT` | Fine-grained PAT with `secrets:write` (+ admin) across the org repos | The engine **uses** this to write every other secret. Rotate by hand. |
| `VERCEL_MASTER_TOKEN` | Vercel **Full Account** token (`kdf-master-rotation`) that can create/delete tokens + set project env | The engine uses this for `generate`. Rotate by hand. |
| `TF_TOKEN_APP_TERRAFORM_IO` | Terraform Cloud API token (deferred) | By hand. |
| `GH_PACKAGES_PAT_NEW` | **Staging slot** for the dedicated `Distribute GH_PACKAGES_PAT` workflow | Set only during a PAT rotation, then delete. |
| `SECRET_VALUE_NEW` | **Generic staging slot** for the issue form's `paste` mode | Set only during a paste rotation, then delete. |

### Environment secrets — engine-managed (§3)

These are in `scripts/secret_registry.json`, so the engine rotates them across every repo+environment:

| Secret | Mode | Lives in (env secret) |
|---|---|---|
| `VERCEL_DEPLOYMENT_TOKEN` | **generate** (Vercel API) | one shared token that both deploys and manages → every app repo's `prod`/`dev` env **and** the terraform repo's `prod`/`dev` env (feeds `TF_VAR_vercel_api_token`) |
| `GH_PACKAGES_PAT` | **paste** (GitHub can't mint PATs) | backend repos' `prod`/`dev` env + non-Terraform Vercel project vars |

### Environment secrets — NOT engine-managed (rotate by hand §5, or via Terraform)

| Secret | How to rotate |
|---|---|
| `VERCEL_ORG_ID`, `VERCEL_PROJECT_ID` | Non-secret IDs — set by hand only when a project is re-provisioned |
| `DB_DATABASE_URL` | **App-plane** — rotate the Neon credential, update the tfvars, `terraform apply` (terraform runbook) |
| `BACKEND_AUTH_*`, `*_SERVICE_KEY`, `BACKEND_STRIPE_*`, `*_CRON_SECRET`, OIDC client secrets | **App-plane** — terraform `SECRETS_ROTATION` runbook (several are coupled groups needing `-replace`) |

---

## 3. Rotate an engine-managed environment secret (the normal path)

Two ways to drive the engine: the **issue form** (no checkout needed) or the **CLI**.

### 3a. Via the `ops:rotate-secrets` issue form

1. **New issue → "Ops · Rotate a secret"** template.
2. Fill in:
   - **Secret(s)** — one or more (e.g. `VERCEL_DEPLOYMENT_TOKEN`, or `ALL`). For `paste`, pick exactly one.
   - **Mode** — `generate` (auto-mint), `paste` (distribute a staged value), or `check` (expiry report).
   - **Environment(s)** — `prod` / `dev` / `ALL`. Per-env secrets get a **distinct value per env**.
   - **Vercel apps** — legacy; ignored for the shared `VERCEL_DEPLOYMENT_TOKEN`. Leave it `ALL`.
   - **Confirm** — must be **Yes** for `generate`/`paste`.
3. **For `paste` only:** first store the new value in the **`SECRET_VALUE_NEW`** repository secret
   (Settings → Secrets and variables → Actions → New repository secret). **Never paste a secret value
   into the issue body — this repo is public.**
4. **Add the `ops:rotate-secrets` label** to the issue. This triggers the run (the owner gate fails
   closed for anyone else). Re-add the label to re-run.
5. The workflow posts a **metadata-only** summary comment; full (secret-masked) output is in the Actions run.
6. **Cleanup (paste):** delete the `SECRET_VALUE_NEW` secret afterward.

### 3b. Via the CLI (maintainer machine)

```bash
# from a checkout of kriegerdataforge-cicd, with deps installed:
pip install -r scripts/requirements.txt

export GH_TOKEN="<a PAT with secrets:write on the targets>"      # e.g. the CICD_PAT value
export VERCEL_MASTER_TOKEN="<full-account Vercel token>"          # generate / vercel paste only

# expiry report (no creds needed):
python scripts/rotate_secret.py --mode check --secrets all

# auto-mint a fresh shared Vercel deployment token (written to every target):
python scripts/rotate_secret.py --mode generate --secrets VERCEL_DEPLOYMENT_TOKEN

# distribute an owner-supplied value (paste) to every GH_PACKAGES_PAT target:
export STAGED_SECRET_VALUE="<the new PAT value>"
python scripts/rotate_secret.py --mode paste --secrets GH_PACKAGES_PAT
```

Or trigger the scheduled workflows from the Actions tab: **Rotate Vercel Deployment Token** (generate),
**Distribute GH_PACKAGES_PAT** (paste, reads `GH_PACKAGES_PAT_NEW`), **Check Secret Expiry** (the weekly monitor — see §9).

### What "generate" vs "paste" means per secret

- **`VERCEL_DEPLOYMENT_TOKEN` → generate.** The engine mints **one shared** account-scoped token via the
  Vercel API and writes the same value to every target — every app repo's `prod`/`dev` environment secret
  **and** the terraform repo's `prod`/`dev` (where it feeds `TF_VAR_vercel_api_token`) — then deletes the
  old shared token. This single token both deploys and manages; there is no separate management token. No
  value to supply.
- **`GH_PACKAGES_PAT` → paste.** GitHub cannot mint PATs via API, so you create the fine-grained PAT in
  the GitHub UI, stage it, and the engine distributes that one value to every target.

---

## 4. Rotate a repository secret (by hand)

For the ops-plane creds in §2 (`CICD_PAT`, `VERCEL_MASTER_TOKEN`, `TF_TOKEN_*`).
**Order matters: create the new credential, set it, verify, *then* revoke the old one** (so nothing
breaks mid-rotation).

### Via the GitHub UI
1. Mint the new credential at its source (GitHub fine-grained PAT page, Vercel account tokens, etc.).
2. `kriegerdataforge-cicd` → **Settings → Secrets and variables → Actions → Repository secrets** →
   the secret → **Update** → paste the new value → **Save**.
3. Verify (see §6), then **revoke the old credential** at its source.

### Via the `gh` CLI
```bash
# list repo secrets (names only — values are never readable):
gh secret list --repo Needless2Say/kriegerdataforge-cicd

# set/update a repo secret — omit --body so gh PROMPTS for the value
# (keeps it out of your shell history and the process list):
gh secret set CICD_PAT --repo Needless2Say/kriegerdataforge-cicd
# ...or pipe from a file you delete right after:
gh secret set VERCEL_MASTER_TOKEN --repo Needless2Say/kriegerdataforge-cicd < ./new_token.txt && rm -f ./new_token.txt
```
> ⚠️ Never use `--body "the-secret"` — the value lands in your shell history and `ps` output. Prompt or pipe instead.

### Special case — `CICD_PAT` / `VERCEL_MASTER_TOKEN` (the engine's own creds)
These authenticate the rotation engine, so they **cannot** be rotated by the engine — always §4 by hand.
After updating one, verify by running a harmless engine op (e.g. `--mode check`, or a single-target
`generate`) and confirm it still authenticates before revoking the old credential.

---

## 5. Rotate a non-registered environment secret (by hand)

For environment secrets not in the registry (a one-off, or before you add it to §3).
**App-plane** secrets (`DB_DATABASE_URL`, `BACKEND_AUTH_*`, etc.) should go through the **terraform
runbook** instead — setting them here alone will drift on the next `terraform apply`.

### Via the GitHub UI
`<repo>` → **Settings → Environments → `<env>` (`prod`/`dev`/`infra`) → Environment secrets** →
the secret → **Update** → new value → **Save**.

### Via the `gh` CLI
```bash
# list a repo's environment secrets:
gh secret list --repo Needless2Say/<repo> --env prod

# set an environment secret (note --env):
gh secret set VERCEL_PROJECT_ID --repo Needless2Say/<repo> --env prod
```

---

## 6. Adding a secret to the registry (make it engine-rotatable)

To bring a new **CI-plane** environment secret under the engine, add an entry to
`scripts/secret_registry.json`:

```jsonc
{
  "name": "MY_CI_SECRET",
  "kind": "generate",                 // or "paste"
  "generator": "random_urlsafe",      // generate only: random_urlsafe | vercel_token
  "per_env": true,                    // distinct generated value per environment
  "github_env_secrets": [
    { "repo": "Needless2Say/some-repo", "environment": "prod", "secret_name": "MY_CI_SECRET" },
    { "repo": "Needless2Say/some-repo", "environment": "dev",  "secret_name": "MY_CI_SECRET" }
  ]
  // optional: "vercel_env_vars": [ { "project_id": "...", "environment": "prod", "env_key": "MY_CI_SECRET" } ]
  // optional: "check": { "expiry": "YYYY-MM-DD", "warn_days_before_expiry": 7 }
}
```
- The target **environment must already exist** in each repo with the matching approval gate.
- Set `"terraform_managed": true` if it's an app-plane secret you want the engine to **refuse**
  (it will point back to the terraform runbook instead of writing it).
- Update the matching dropdown option in `.github/ISSUE_TEMPLATE/ops-rotate-secrets.yml` so it shows in the form.

---

## 7. Verify · rollback · troubleshoot

**Verify a rotation took:**
- The engine run shows `OK` per target and exits 0; the issue comment summarizes it.
- For a deploy credential, trigger a `dev` deploy of an affected repo and confirm it succeeds with the new value.
- `gh secret list ... ` shows the **Updated** timestamp moved (values themselves are never readable).

**Rollback:** re-`paste` the previous value (repo/env secret), or for `VERCEL_DEPLOYMENT_TOKEN` re-run `generate`
(it always mints fresh). Keep the old credential alive until you've verified the new one.

**Troubleshooting:**
- *403 creating a Vercel token* → `VERCEL_MASTER_TOKEN` must be **Full Account** scope (the `/v3/user/tokens`
  API rejects team-scoped tokens). See `MANUAL_SETUP.md` Phase 6.1.
- *404 on a target* → the environment doesn't exist in that repo, or the `secret_name`/`repo` is wrong in the registry.
- *paste aborted* → `SECRET_VALUE_NEW` (form) / `GH_PACKAGES_PAT_NEW` (distribute workflow) wasn't set.
- *"Terraform-managed — refusing"* → that secret is app-plane; use the terraform runbook.
- Logs look empty → secret values are **masked** by design; check the per-target `OK`/`FAILED` lines, not the value.

---

## 8. Per-secret recipes (what to do, secret by secret)

Each recipe is **When → Steps → Verify → 🚨 If leaked.** CI-plane recipes (8.1–8.7) are fully
self-contained here; app-plane recipes (8.8–8.14) give the exact "what to do" plus the coupled-group
gotchas, and point to the **terraform `SECRETS_ROTATION` / `SECRETS_ROTATION_QUICKSTART`** runbook for the
`apply` mechanics (those values are Terraform-owned — never write them with the engine).

### CI-plane — engine-managed environment secrets

#### 8.1 `VERCEL_DEPLOYMENT_TOKEN` (one shared deploy + management token)
A single engine-minted, account-scoped Vercel token that both **deploys** and **manages**:
- **`VERCEL_DEPLOYMENT_TOKEN`** — **one shared token** used by *every* app repo's CI **and** the terraform
  repo. The engine mints a single token and writes the same value to all 14 targets — every app repo's
  `prod`/`dev` env secret (12) plus the terraform repo's `prod`/`dev` (2, where it feeds
  `TF_VAR_vercel_api_token`) — then deletes the old shared token **only if every write succeeds** (a partial
  failure keeps both valid). App/env filters are ignored — it's one value everywhere. There is no longer a
  separate terraform management token.

> **Requires `VERCEL_TEAM_ID`.** The engine scopes minted tokens to your Vercel team via the `teamId`
> param — a personal-scoped token is rejected ("token is not valid") for team projects. The
> `VERCEL_TEAM_ID` repo **secret** must be set (= `VERCEL_ORG_ID`); generate fails fast without it.
> Setup: `MANUAL_SETUP.md` §6.2a.

- **When:** monthly schedule (the cron rotates it), or the token leaked.
- **Steps:** issue form → secret `VERCEL_DEPLOYMENT_TOKEN`, mode **generate**, Confirm =
  Yes, add the label. *(Or: Actions → **Rotate Vercel Deployment Token**; or `rotate_secret.py
  --mode generate --secrets VERCEL_DEPLOYMENT_TOKEN`.)*
- **Verify:** trigger a `dev` deploy of any app; or Vercel → Tokens shows a fresh `VERCEL_DEPLOYMENT_TOKEN`
  expiry.
- **Expiry tracking (automatic):** after each successful mint the **Rotate Vercel Deployment Token**
  workflow runs `--mode record-expiry` and opens a small PR bumping this entry's `check.expiry` (today +
  45d). Just review and merge it — no manual edit. If the rotation cron ever stops, the stale expiry trips
  the weekly monitor as a watchdog.
- **🚨 If leaked:** delete that token in Vercel first (containment), then **generate**. The shared token
  has account-wide deploy **and** management reach, so treat a leak as affecting every app and the
  terraform plane.
- **One-time cutover:** the first shared `generate` leaves the old per-app tokens (`kdf-auth-backend-*`,
  `kdf-fitness-frontend-*`, `kdf-tiffanys-frontend-*`) orphaned in Vercel — delete them manually, or let
  them expire (≤45 days). The engine no longer tracks them.

#### 8.2 `GH_PACKAGES_PAT` (env secret in the backend repos + non-Terraform Vercel vars)
- **When:** the `check` workflow warns of expiry, scheduled, or leaked.
- **Steps:**
  1. Create a fine-grained PAT at <https://github.com/settings/tokens>: name `kdf-packages-read`,
     expiration 1 year, resource owner `Needless2Say`, **repository access = only
     `kriegerdataforge-python-sdk`**, **Contents: Read-only** (nothing else).
  2. Stage it: set the **`SECRET_VALUE_NEW`** repo secret (issue-form path) *or* **`GH_PACKAGES_PAT_NEW`**
     (the dedicated *Distribute GH_PACKAGES_PAT* workflow). **Never put the value in the issue.**
  3. Run: issue form → `GH_PACKAGES_PAT`, mode **paste**, Confirm = Yes, label. *(Or run the Distribute workflow.)*
  4. Update the `GH_PACKAGES_PAT` entry's `check.expiry` in `scripts/secret_registry.json`; commit.
  5. **Delete** the staging secret. **Revoke** the old PAT in the GitHub UI.
- **Verify:** a backend build that pip-installs `kdf-auth-sdk` succeeds.
- **🚨 If leaked:** do step 5's revoke **first**, then 1–4.

### CI-plane — repository (control-plane) secrets, by hand

#### 8.3 `CICD_PAT` 🔴 (the engine's own write credential)
The fine-grained PAT the engine uses to write every other secret. It is hand-rotated (GitHub has no PAT-mint
API) and tracked with a **30-day expiry (next: 2026-07-30)**. Its permissions over **All repositories (incl.
future)** are: Repository **Administration, Contents, Environments, Secrets, Variables, Actions, Issues,
Pull requests** (all read/write), plus **Metadata: read**.
- **When:** leaked, near expiry, or scope change.
- **Steps:**
  1. Create a new fine-grained PAT with the same scope the current one has (the permission set above — see
     `MANUAL_SETUP.md` Phase 3 for the exact list).
  2. `gh secret set CICD_PAT --repo Needless2Say/kriegerdataforge-cicd` (prompt for the value — no `--body`).
  3. **Verify it authenticates** before revoking the old one: run `rotate_secret.py --mode check` (issue
     form or CLI), or a single-target `generate`.
  4. **Revoke** the old PAT.
- **🚨 If leaked:** it can overwrite **every** secret. After 1–4, assume tampering: re-`generate` the
  `VERCEL_DEPLOYMENT_TOKEN` (§8.1) and re-`paste` `GH_PACKAGES_PAT` (§8.2). Review recent Actions runs for unexpected activity.

#### 8.3a `KDF_APP_PRIVATE_KEY` 🔴 (GitHub App — the engine's new write credential)
The GitHub App that mints the rotation/kit workflows' short-lived tokens. Setup: `MANUAL_SETUP.md`
Phase 6.7. The non-secret `KDF_APP_ID` never needs rotation; this `.pem` private key does.
- **When:** leaked, periodic (set a relaxed reminder, e.g. ~6 months), or a key you no longer trust.
- **Steps (zero-downtime — GitHub Apps allow multiple keys):**
  1. App → **General → Private keys → Generate a private key** (the App now has *two* valid keys).
  2. Update the `KDF_APP_PRIVATE_KEY` repo secret in `kriegerdataforge-cicd` with the new `.pem`
     contents (`gh secret set KDF_APP_PRIVATE_KEY --repo Needless2Say/kriegerdataforge-cicd < new.pem`).
  3. **Verify** a flow on the new key (Actions → *Check Secret Expiry*, or a scoped *Rotate Vercel Deployment Token*).
  4. App → **Delete** the old private key. Securely delete the local `.pem` files.
  5. Update this entry's `check.expiry` in `secret_registry.json` to the next reminder date; commit.
- **🚨 If leaked:** the key can mint installation tokens with the App's granted scopes (Secrets +
  Contents + PR write) → delete that key immediately (step 4), rotate as above, and assume any secret the
  engine can write is suspect — re-`generate` the `VERCEL_DEPLOYMENT_TOKEN` (§8.1) and re-`paste` `GH_PACKAGES_PAT`
  (§8.2). If `USE_GITHUB_APP` is on, you can also unset it to fall back to `CICD_PAT` while you rotate.

#### 8.4 `VERCEL_MASTER_TOKEN` 🔴 (full Vercel account)
- **Steps:**
  1. Vercel → **Account → Tokens** → create `kdf-master-rotation` with **Full Account** scope (team scope
     gets a 403 on `/v3/user/tokens`).
  2. `gh secret set VERCEL_MASTER_TOKEN --repo Needless2Say/kriegerdataforge-cicd` (prompt).
  3. **Verify:** run a `VERCEL_DEPLOYMENT_TOKEN` generate (§8.1).
  4. **Delete** the old master token in Vercel.
- **🚨 If leaked:** it can mint/delete any Vercel token → re-`generate` the `VERCEL_DEPLOYMENT_TOKEN` (§8.1).

#### 8.6 `TF_TOKEN_APP_TERRAFORM_IO` (deferred)
- Terraform Cloud → **User Settings → Tokens** → create → `gh secret set TF_TOKEN_APP_TERRAFORM_IO
  --repo Needless2Say/kriegerdataforge-cicd` → revoke old. *(Remote state is deferred — this may be unset.)*

#### 8.7 Staging slots — `GH_PACKAGES_PAT_NEW`, `SECRET_VALUE_NEW`
- Not standing secrets: they hold a value only **during** a paste rotation. **Always delete them after the
  run.** If one lingered holding a real value and may have been exposed, delete it and rotate the secret it
  held per that secret's recipe.

### App-plane — Terraform-owned (do these in the terraform repo, never the engine)

> Pattern for all of these: update the value in the env's **gitignored `*.secrets.auto.tfvars`** →
> `terraform plan` → `terraform apply` (with `-replace` on the listed resources). Dev and prod are
> **separate** roots/keypairs. Exact commands: terraform `SECRETS_ROTATION` runbook.

#### 8.8 RS256 keypair — `AUTH_PRIVATE_KEY` + `AUTH_PUBLIC_KEY` 🔴 (Group A)
All three derive from one keypair: `backend_auth_private_key`, `backend_auth_public_key` (auth service),
and `frontend_auth_public_key` (both frontends, **byte-identical** public key).
- **Steps:** generate a new PKCS#8 keypair → **overlap window:** publish the OLD public key in
  `AUTH_PUBLIC_KEYS` (JWKS) so in-flight tokens still verify → update all three tfvars values →
  `terraform apply -replace` on the auth service **and** both frontend public-key resources → after the max
  token lifetime, drop the old key from `AUTH_PUBLIC_KEYS` and apply again.
- **Verify:** new logins work; existing sessions survive the window.
- **🚨 If the private key leaked:** do this immediately and consider shortening token TTLs during the window.

#### 8.9 `DB_DATABASE_URL` 🔴
- Reset the credential at **Neon** (new password/role) → update the env's DB URL tfvar (and the GitHub
  environment secret if `cd-terraform` reads it directly) → `terraform apply` → verify a `dev` deploy connects.
- The auto-injected `POSTGRES_*` / `DATABASE_URL` (Neon–Vercel integration) are rotated in the Neon/Vercel
  Storage UI, **not** Terraform.

#### 8.10 `KDF_SERVICE_KEY` / `SERVICE_API_KEYS` 🟠 (Group C)
Each tenant's `*_service_key` is `KDF_SERVICE_KEY` on that backend **and** joined into the auth service's
composite `SERVICE_API_KEYS`.
- **Steps:** generate a new high-entropy key → update `<tenant>_service_key` in tfvars → `terraform apply
  -replace` on **both** the tenant backend's `KDF_SERVICE_KEY` resource and the auth service's
  `SERVICE_API_KEYS` resource **in one apply** → verify service-to-service calls authenticate.

#### 8.11 `STRIPE_SECRET_KEY` / `STRIPE_WEBHOOK_SECRET` 🔴 (Group E)
Consumed by both the auth service and the tiffanys-space backend.
- **Steps:** roll the key/secret in the **Stripe** dashboard → update `backend_stripe_*` tfvars →
  `terraform apply -replace` on the Stripe resources of **both** consumers → verify a test charge + webhook.

#### 8.12 `KDF_OIDC_CLIENT_SECRET` 🟠
One-time value shown at client registration; kdf-auth never returns it again — **no in-place rotation**.
- **Steps:** re-register the client with kdf-auth to get a new secret → update `<tenant>_oidc_client_secret`
  in tfvars → `terraform apply` → verify that tenant's OIDC login + callback.

#### 8.13 `CRON_SECRET`
- Generate a new high-entropy value → update `*_cron_secret` tfvars → `terraform apply` → verify the cron
  endpoint accepts the new bearer (and rejects the old).

#### 8.14 Provider keys — `AUTH_RESEND_API_KEY`, `AUTH_TWILIO_*`, `RATELIMIT_STORAGE_URI`
- Rotate at the provider (Resend / Twilio / Upstash) → update the matching tfvars → `terraform apply` →
  verify the feature (email/SMS/rate-limit) still works. Empty value = feature disabled (safe fallback).

---

## 9. Automated monitoring & rotation cadence

Two scheduled workflows keep credentials fresh. Everything is **monthly** in cadence — fully automated
where the credential can be minted by a machine, reminder-driven where it can't.

| Credential | Cadence | Mechanism |
|---|---|---|
| Shared `VERCEL_DEPLOYMENT_TOKEN` | monthly | **Auto-generate** — `Rotate Vercel Deployment Token` (cron, 1st of the month), then auto-opens a PR bumping `check.expiry`. Hands-off (just merge the bot PR). |
| `GH_PACKAGES_PAT` | monthly\* | **Auto-issue reminder** → mint by hand, then §8.2. |
| `CICD_PAT` | monthly\* | **Auto-issue reminder** → §8.3. |
| `VERCEL_MASTER_TOKEN` | monitored | **Auto-issue reminder** → §8.4. Auto-rotation is a planned enhancement. |
| `KDF_APP_PRIVATE_KEY` | ~6-monthly | **Auto-issue reminder** → §8.3a (zero-downtime multi-key rotation). |

\* GitHub has no PAT-creation API, so "monthly" here means: set the PAT's expiry to ~30 days when you
create it, and the monitor reminds you to run the ~5-minute manual recipe. **The GitHub App migration
retires this toil for the rotation/kit workflows** — Phase 1 is implemented (mint App tokens behind the
`USE_GITHUB_APP` flag, fall back to `CICD_PAT`); once it's switched on, `CICD_PAT` survives only for
`issue-create-repo.yml` until the org move. See
[`../design/github-app-migration.md`](../design/github-app-migration.md).

**`Check Secret Expiry`** runs weekly (Mondays): `rotate_secret.py --mode check --secrets all`, then keeps
**one deduplicated tracking issue** (label `ops:secret-expiry`):
- near / at / undated expiry → opens the issue (or updates it) listing what to rotate + the recipe;
- all healthy → **auto-closes** it.

It reads only the registry's `check.expiry` metadata — never a secret value. After you rotate, update that
secret's `check.expiry` in `scripts/secret_registry.json`; the issue auto-closes on the next clean run.

**Manual override (enhanced security):** nothing here blocks an out-of-cycle rotation — run the
`ops:rotate-secrets` form / CLI any time (e.g. after a suspected leak, §0), independent of the schedule.

---

## See also
- [`MANUAL_SETUP.md`](./MANUAL_SETUP.md) — first-time provisioning of every secret + environment.
- [`../design/github-app-migration.md`](../design/github-app-migration.md) — planned move to a GitHub App (ephemeral tokens) + Vercel-master auto-rotation.
- [`docs/reference/WORKFLOWS.md`](../reference/WORKFLOWS.md) — reusable workflow inputs/secrets reference.
- `scripts/rotate_secret.py --help` · `scripts/secret_registry.json` — the engine + registry.
- terraform repo `SECRETS_ROTATION` / `SECRETS_ROTATION_QUICKSTART` — app-plane (Terraform-owned) secrets.
