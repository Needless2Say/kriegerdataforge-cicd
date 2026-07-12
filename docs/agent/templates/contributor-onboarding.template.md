# Contributor Onboarding — {repo name}

> **How to use:** copy this file to `docs/guides/CONTRIBUTOR_ONBOARDING.md` and tailor **every**
> section to the repo — keep the numbered spine so a developer can navigate any KDF repo the same
> way (see `docs/agent/DOCUMENTATION_STANDARD.md`). Delete a section only if you can say why it
> doesn't apply *(e.g. a static portfolio has no environment setup)*. The resulting file is
> **per-repo and never synced**. Replace every `{placeholder}`; delete the table rows that don't
> apply. Body links are written relative to the **destination** (`docs/guides/`), so they resolve
> after copying — not from this template's own location. **Delete this entire "How to use"
> blockquote in the copied file.**

Welcome. This is **{repo name}** — {one paragraph: what this repo is AND its role in the KDF
ecosystem — e.g. "a tenant backend on the KDF platform: identity is delegated to the hub via
`kdf_sdk.auth`; this service verifies tokens, never issues them."}

This guide gets you from a clean checkout to a green `make ci` and your first PR. It does not
replace the canonical docs — read those first:

- [`AGENTS.md`](../../AGENTS.md) — vision, tech stack, module map, **critical rules**, commands.
- [`WORKFLOW.md`](../../WORKFLOW.md) — the lane model and the plan → approve → PR loop.
- [`skills.md`](../../skills.md) — the security playbook (read before security-sensitive work).

> **The mindset that matters most here:** {the repo's #1 gotcha or guiding principle — the thing
> that, unknown, wastes a new contributor's first afternoon.}

---

## 1. Prerequisites

| Tool | Version | Notes |
| --- | --- | --- |
| {runtime — Node.js / Python / Terraform} | {version} | {why pinned / how to install} |
| GNU Make | any recent | All workflows run through the Makefile. **Windows:** use Git Bash / WSL so the recipes' `sh`/`grep` work. |
| Docker + Docker Compose | recent | {what the local stack provides — DB, storage, siblings} |
| {repo-specific tool} | {version} | {notes} |

---

## 2. Clone & install

```bash
git clone {repo-url}
cd {repo-dir}
{install command — e.g. `make install` / `GH_PACKAGES_PAT=<pat> make setup`}
{pre-commit install   # gitleaks hook — ONLY in repos with a .pre-commit-config.yaml; delete otherwise}
```

---

## 3. Environment & secrets

Copy the tracked example file to the gitignored local file and fill in real values. **Real secret
values live only in the gitignored file — never in any tracked file, commit, or log.**

```bash
cp {.env.example / .env.local.example} {.env.development / .env.local}
```

| Variable | Required | Where the value comes from |
| --- | --- | --- |
| {VAR} | {yes/prod-only/optional} | {source — owner, hub registration, your choice} |

### Ecosystem access *(SSO-client repos / private-SDK consumers — delete rows that don't apply)*

| You need | How you get it |
| --- | --- |
| **Your own local-dev OIDC client** | Issued **per developer** from a hub checkout: `python -m api.seed.dev_clients register-dev --username <your-kdf-username> --yes-dev` (dev-only — refuses prod and forces a localhost redirect URI; `list-dev` / `revoke-dev` manage it). The returned `client_id` is this app's expected audience (`KDF_JWT_AUDIENCE` / `AUTH_AUDIENCE`); the issuer is the hub auth-UI URL. |
| **Private Python SDK (`kdf_sdk`)** | Installs via `git+https://github.com/Needless2Say/kriegerdataforge-sdk.git@vX.Y.Z` — needs a **fine-grained GitHub PAT with Contents: Read on `kriegerdataforge-sdk` only**, set as `GH_PACKAGES_PAT`. Install-time only; not needed at runtime. There is **no public PyPI package** — never add one. |

---

## 4. Run it locally

```bash
{the one-command happy path — e.g. `make docker-up` / `make dev`}
```

{Port table or pointer to it. For non-app repos, say what "running" means here — e.g. in a
CI/tooling repo the gate IS the run.}

---

## 5. The gate — `make ci`

`make ci` is **the gate** — it must be green locally before any PR:

```bash
make ci        # {what it runs: lint + type-check + tests + …}
```

Then bump the version — **pick the level by impact** (no behavior/contract change → `patch`;
additive → `minor`; breaking → `major`); the CI check enforces consistency and strictly-ahead,
not your level choice:

```bash
make bump-patch    # Windows: PYTHONIOENCODING=utf-8 make bump-patch
                   # (the bump script's emoji output can crash on cp1252 consoles)
```

{Repo-mandatory post-build sync, if any — e.g. `make vercel-compact` after any `api/` change.}

---

## 6. Where the code lives (module map)

```text
{short annotated directory tree}
```

### Critical rules you'll trip over

{3–5 rules distilled from `AGENTS.md` — the full list lives there. Examples of the *kind* of
rule that belongs here: import boundaries, "server is authoritative", post-build syncs,
identity-decoupling (plain `user_id`, no FK to `kdf_users`).}

---

## 7. Pick a lane → plan → approve → PR

Every task follows the tiered loop in [`WORKFLOW.md`](../../WORKFLOW.md): **Quick** (tiny,
no-behavior) · **Standard** (plan → **owner approves** → implement → `make ci` green → PR →
GitHub CI green → **owner merges**) · **Epic** (novel/cross-repo → the design gate in
[`DESIGN_AND_EPICS.md`](../agent/DESIGN_AND_EPICS.md)). Don't skip the plan-approval gate; don't
self-merge; when unsure, size **up**.

Before opening a PR, meet [`DEFINITION_OF_DONE.md`](../agent/DEFINITION_OF_DONE.md) for your change
type. For anything security-sensitive, follow the matching scenario in
[`skills.md`](../../skills.md) **before** writing code.

---

## 8. Getting unblocked

| Symptom | Cause / fix |
| --- | --- |
| SDK install fails 403 / `Authentication failed` | `GH_PACKAGES_PAT` missing, expired, or lacking *Contents: Read* on `kriegerdataforge-sdk`. Set it and re-run the install. |
| **Pushes suddenly 403 across ALL repos** | A stale PAT in a global `.gitconfig` `insteadOf` rewrite. The SDK-consumer backend Makefiles inject the PAT via **process-scoped `GIT_CONFIG_*` env vars** precisely to avoid this — remove any `insteadOf` you added by hand. |
| {repo-specific symptom} | {cause / fix} |

Still stuck: the reading order is [`AGENTS.md`](../../AGENTS.md) → [`WORKFLOW.md`](../../WORKFLOW.md)
→ [`skills.md`](../../skills.md) → [`docs/README.md`](../README.md). Then open an issue — for a
**security** issue, never a public one; follow [`SECURITY.md`](../../SECURITY.md).
