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
| `CICD_REGISTRY_PAT` | PAT for GitHub Packages / registry access | By hand. |
| `VERCEL_MASTER_TOKEN` | Vercel **Full Account** token (`kdf-master-rotation`) that can create/delete tokens + set project env | The engine uses this for `generate`. Rotate by hand. |
| `TF_TOKEN_APP_TERRAFORM_IO` | Terraform Cloud API token (deferred) | By hand. |
| `GH_PACKAGES_PAT_NEW` | **Staging slot** for the dedicated `Distribute GH_PACKAGES_PAT` workflow | Set only during a PAT rotation, then delete. |
| `SECRET_VALUE_NEW` | **Generic staging slot** for the issue form's `paste` mode | Set only during a paste rotation, then delete. |

### Environment secrets — engine-managed (§3)

These are in `scripts/secret_registry.json`, so the engine rotates them across every repo+environment:

| Secret | Mode | Lives in (env secret) |
|---|---|---|
| `VERCEL_TOKEN` / `VERCEL_API_TOKEN` | **generate** (Vercel API) | each app repo's `prod`/`dev`/`infra` env |
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
   - **Secret(s)** — one or more (e.g. `VERCEL_TOKEN`, or `ALL`). For `paste`, pick exactly one.
   - **Mode** — `generate` (auto-mint), `paste` (distribute a staged value), or `check` (expiry report).
   - **Environment(s)** — `prod` / `dev` / `infra` / `ALL`. Per-env secrets get a **distinct value per env**.
   - **Vercel apps** — optional filter for `VERCEL_TOKEN` generation.
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

# auto-mint fresh Vercel tokens for the fitness frontend, prod only:
python scripts/rotate_secret.py --mode generate --secrets VERCEL_TOKEN --apps fitness-frontend --envs prod

# distribute an owner-supplied value (paste) to every GH_PACKAGES_PAT target:
export STAGED_SECRET_VALUE="<the new PAT value>"
python scripts/rotate_secret.py --mode paste --secrets GH_PACKAGES_PAT
```

Or trigger the scheduled workflows from the Actions tab: **Rotate Vercel Tokens** (generate),
**Distribute GH_PACKAGES_PAT** (paste, reads `GH_PACKAGES_PAT_NEW`), **Check GH_PACKAGES_PAT Expiry**.

### What "generate" vs "paste" means per secret

- **`VERCEL_TOKEN` → generate.** The engine mints a *unique* token per target via the Vercel API,
  writes it to that repo's environment secret, then deletes the old token. No value to supply.
- **`GH_PACKAGES_PAT` → paste.** GitHub cannot mint PATs via API, so you create the fine-grained PAT in
  the GitHub UI, stage it, and the engine distributes that one value to every target.

---

## 4. Rotate a repository secret (by hand)

For the ops-plane creds in §2 (`CICD_PAT`, `VERCEL_MASTER_TOKEN`, `CICD_REGISTRY_PAT`, `TF_TOKEN_*`).
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

**Rollback:** re-`paste` the previous value (repo/env secret), or for `VERCEL_TOKEN` re-run `generate`
(it always mints fresh). Keep the old credential alive until you've verified the new one.

**Troubleshooting:**
- *403 creating a Vercel token* → `VERCEL_MASTER_TOKEN` must be **Full Account** scope (the `/v3/user/tokens`
  API rejects team-scoped tokens). See `MANUAL_SETUP.md` Phase 6.1.
- *404 on a target* → the environment doesn't exist in that repo, or the `secret_name`/`repo` is wrong in the registry.
- *paste aborted* → `SECRET_VALUE_NEW` (form) / `GH_PACKAGES_PAT_NEW` (distribute workflow) wasn't set.
- *"Terraform-managed — refusing"* → that secret is app-plane; use the terraform runbook.
- Logs look empty → secret values are **masked** by design; check the per-target `OK`/`FAILED` lines, not the value.

---

## See also
- [`MANUAL_SETUP.md`](./MANUAL_SETUP.md) — first-time provisioning of every secret + environment.
- [`docs/reference/WORKFLOWS.md`](../reference/WORKFLOWS.md) — reusable workflow inputs/secrets reference.
- `scripts/rotate_secret.py --help` · `scripts/secret_registry.json` — the engine + registry.
- terraform repo `SECRETS_ROTATION` / `SECRETS_ROTATION_QUICKSTART` — app-plane (Terraform-owned) secrets.
