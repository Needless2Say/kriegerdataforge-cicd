# Design note — decouple the Tier-2 E2E tests out of cicd into each tenant repo

**Status: APPROVED — owner approved 2026-07-07; Phase 0 spike validated. Phased, backward-compatible
implementation in progress.** Live status + PR links: [`e2e-test-decoupling-LOG.md`](./e2e-test-decoupling-LOG.md).

> **One-line intent.** `kriegerdataforge-cicd` must hold **only the reusable E2E engine**. Each tenant's
> browser journey — its spec, its stack services, its seed data — belongs in **that tenant's repo**.
> Onboarding a new tenant must touch **only that tenant's repo**, never cicd.

---

## Problem — the E2E harness violates this repo's own scope

Today the entire Tier-2 E2E lives under `kriegerdataforge-cicd/e2e/`, and **every part that is
tenant-specific lives here too**. Onboarding one new tenant edits cicd in **five** places:

| # | File in cicd | What a new tenant adds | Grows per tenant? |
|---|---|---|---|
| 1 | `e2e/tests/<tenant>-login.spec.ts` | a whole new Playwright spec | +1 file |
| 2 | `e2e/docker-compose.e2e.yml` | its 3 services (db + api + nextjs) as a new `profiles:` block | +~90 lines |
| 3 | `e2e/ci_stack.py` | a `TENANTS` entry **+** client-cred keys in `_load_or_make_state`/`_compose_env`/`_interp_env` | +~15 lines |
| 4 | `e2e/seed_e2e.py` | a `CLIENTS` entry (redirect + name) | +1 block |
| 5 | `.github/workflows/e2e-compose.yml` | a `journey` enum option + a `case` branch | +2 lines |

This is exactly the scope creep [`CONTRIBUTING.md`](../../CONTRIBUTING.md) warns against: cicd is the
**Tier-1 reusable platform library**, but the E2E `tests/` folder is becoming a graveyard of every
tenant's browser spec, and three engine files carry a hardcoded per-tenant registry. As the platform
grows to N tenants, cicd bloats linearly with content that is not reusable — the opposite of its purpose.

**Root cause:** an E2E journey is inherently *cross-repo* (fitness needs fitness-fe + fitness-be + hub +
auth-UI + db). The first implementation put both the reusable *engine* and the tenant-specific *content*
in one place. The fix is to separate them.

---

## Principle

> **Onboarding tenant N must touch only tenant N's repo — never cicd, never the hub, never another tenant.**

cicd keeps a fixed, tenant-agnostic *engine*; each tenant repo carries its own journey as **data + a spec**.

---

## Target architecture

### Stays in cicd (reusable substrate — frozen size, never grows per tenant)

- **`e2e-compose.yml`** reusable workflow — parameterized by the **caller** (generic `journey` + `repos`
  inputs); no `journey` enum, no hardcoded multi-repo checkout list.
- **`ci_stack.py`** — **data-driven**: discovers each sibling repo's `e2e/manifest.json` instead of a
  hardcoded `TENANTS` dict. Owns keygen, shared-secret generation, build/up/migrate/seed orchestration.
- **`docker-compose.shared.yml`** — only the shared identity layer: `kdf-db` + `kdf-api` (hub) +
  `kdf-auth-ui`. There is always exactly one hub and one auth-UI, so this does not grow per tenant.
- **`seed_shared.py`** — seeds the deterministic login user + inserts whatever **client specs the driver
  hands it** (generic insert code; the redirect/name are tenant-supplied data).
- **The Playwright harness** — `playwright.config.ts`, `package.json`, `tsconfig.json`, `README.md`.

### Moves into each tenant repo (the parts that grow — now grow *there*)

- **`e2e/tests/<tenant>.spec.ts`** — its browser journey.
- **`e2e/docker-compose.e2e.yml`** — a **fragment** defining only *its* services, merged onto the shared
  base. Cross-repo build contexts are absolute via `${E2E_WORKSPACE}/<repo>` (see Compose merge below).
- **`e2e/manifest.json`** — its journey declared as data (schema below).
- **`.github/workflows/e2e-gate.yml`** — already present; passes its `journey` + extra `repos` as inputs.

The catalogue-seed logic (`python -m api.seed.fitness seed-foods`) already lives in the tenant backends —
only its *invocation wiring* moves from `ci_stack.py`'s `TENANTS` dict into the manifest.

---

## The contract — `e2e/manifest.json`

This **is** the decoupling: cicd reads it, never hardcodes it. Worked example
(`fitness-app-frontend/e2e/manifest.json`):

```json
{
  "journey": "fitness",
  "grep": "@fitness",
  "repos": ["fitness-app-backend"],
  "compose": "e2e/docker-compose.e2e.yml",
  "entry_url": "http://localhost:3000",
  "backend": {
    "service": "fitness-app-api",
    "migrate": true,
    "seed": ["python", "-m", "api.seed.fitness", "seed-foods"]
  },
  "oidc_client": {
    "redirect_uri": "http://localhost:3000/api/auth/oidc/callback",
    "name": "Fitness App (E2E)"
  }
}
```

The shared-identity `auth` journey (`kriegerdataforge-auth-ui/e2e/manifest.json`) is the degenerate case —
no tenant app, no extra repo, a synthetic client whose `:9999` callback the spec intercepts:

```json
{
  "journey": "auth",
  "grep": "@auth",
  "repos": [],
  "compose": null,
  "entry_url": "http://localhost:3002",
  "backend": null,
  "oidc_client": { "redirect_uri": "http://localhost:9999/callback", "name": "Auth-UI Journey (E2E)" }
}
```

| Field | Meaning | Replaces (in today's cicd) |
|---|---|---|
| `journey` / `grep` | journey id + Playwright `--grep` tag | `TENANTS` key, workflow `case` |
| `repos` | extra sibling repos to check out beyond self + shared | workflow hardcoded checkout list |
| `compose` | tenant compose fragment path (null = shared only) | a `profiles:` block in the monolith |
| `backend` | service to migrate + seed command (null = none) | `TENANTS[*].service`/`seed` |
| `oidc_client` | redirect + display name for the seeded client | `seed_e2e.py` `CLIENTS` entry |

---

## cicd engine changes (touched **twice** total, then frozen)

- **`ci_stack.py` → data-driven.** Delete the `TENANTS` dict. Scan `WORKSPACE/*/e2e/manifest.json` into a
  registry keyed by `journey`; `up --journey fitness` selects one. Generate a client id/secret keyed by
  journey name — the state file becomes `{ "shared": {…}, "clients": { "fitness": {…} } }`, no more
  hardcoded `tiffanys_client_id` keys. Assemble the compose invocation as
  `-f docker-compose.shared.yml [-f <repo>/e2e/docker-compose.e2e.yml]`; migrate/seed the backend only when
  `manifest.backend` is set.
- **`docker-compose.shared.yml`** — extracted from today's monolith: `kdf-db` + `kdf-api` + `kdf-auth-ui`
  + the `gh_packages_pat` secret + `e2e-net` only.
- **`seed_shared.py`** — generalized `seed_e2e.py`: login user + a list of client specs handed in by the
  driver (generic code; redirect/name from manifests).
- **`e2e-compose.yml`** — the reusable path becomes generic: inputs `journey` (grep/manifest selector) +
  `repos` (CSV extra siblings). The App token scopes to `{hub, auth-ui, sdk} + github.repository + repos`;
  checkout = that same set. **No `journey` enum, no 7-repo list.** Owner smoke-testing moves to a
  `workflow_dispatch` on each tenant's own `e2e-gate.yml`, so cicd ends with **zero tenant names anywhere**.

---

## Compose merge design (Phase 0 — validated)

The shared base (cicd) and the tenant fragment (tenant repo) merge with
`docker compose -f shared.yml -f <tenant>/e2e/docker-compose.e2e.yml`. The one real unknown was build-context
path resolution: Docker resolves *relative* build contexts against the **first** `-f` file's directory, which
would break a fragment that lives in a different repo. **Resolution: absolute contexts via
`${E2E_WORKSPACE}/<repo>` interpolation**, which the driver sets to the workspace root.

**Phase 0 spike (2026-07-07) confirmed this works** — `docker compose -f shared.yml -f fitness-fragment.yml
config` resolved every context to an absolute path unambiguously, and merged the network + `gh_packages_pat`
secret across files:

```
kdf-api            → ${E2E_WORKSPACE}/kriegerdataforge        (from shared.yml)
fitness-app-api    → ${E2E_WORKSPACE}/fitness-app-backend     (from the tenant fragment)
fitness-app-nextjs → ${E2E_WORKSPACE}/fitness-app-frontend    (from the tenant fragment)
```

---

## Per-repo moves

| Repo | Gains `e2e/` | Journey spec (from) |
|---|---|---|
| `fitness-app-frontend` | `manifest.json` + `docker-compose.e2e.yml` (fe + be + db) | `tests/fitness.spec.ts` ← `oidc-login.spec.ts` |
| `tiffanys-space` | `manifest.json` + `docker-compose.e2e.yml` (fe + be + db) | `tests/tiffanys.spec.ts` ← `tiffanys-login.spec.ts` |
| `kriegerdataforge-auth-ui` | `manifest.json` (no compose/backend) | `tests/auth.spec.ts` ← `auth-login.spec.ts` |
| `fitness-app-backend` / `tiffanys-space-backend` | (seed cmd already lives here; referenced by manifest) | — |

The compose fragment lives with the **frontend** (it owns the journey entry point) and references its
sibling backend via `${E2E_WORKSPACE}/<repo>` build contexts.

---

## Migration plan (safe, incremental, one VERSION bump per PR, owner merges each)

- **Phase 0 — spike (cicd, throwaway):** prove the cross-repo compose merge. ✅ **DONE** (above).
- **Phase 1 — cicd engine, additive & backward-compatible (1 PR):** ship the data-driven `ci_stack.py`
  (manifest discovery), `docker-compose.shared.yml`, `seed_shared.py`, and the generic workflow inputs —
  **while keeping today's hardcoded path as a fallback** so the E2E stays green with zero tenant changes yet.
- **Phase 2 — move each journey to its repo (1 PR per tenant, independently dispatch-verifiable):**
  fitness → fitness-fe/be, tiffanys → tiffanys-space/be, auth → auth-UI. cicd auto-discovers each manifest,
  so **no cicd PR per tenant**.
- **Phase 3 — cicd cleanup (1 PR):** delete the built-in `TENANTS`/monolith-compose/old specs fallback.
  cicd is now pure reusable engine.

**Net:** cicd is touched **exactly twice** (engine in, fallback out), each tenant once, and **every future
tenant = one PR in its own repo, zero cicd edits.**

---

## Risks & mitigations

| Risk | Mitigation |
|---|---|
| Cross-repo compose build-context resolution | **Resolved** — absolute `${E2E_WORKSPACE}` contexts, Phase-0-validated. |
| A migration window where the E2E is broken | Phase 1 keeps the old hardcoded path as a fallback; tenants move one at a time; gates are **dormant** (`RUN_E2E_GATE` unset) throughout. |
| Reusable-workflow interface change breaks callers | The workflow's `workflow_call` inputs are extended **additively** (`repos` is new + optional-with-default); `journey` type unchanged. Follows `CONTRIBUTING.md` breaking-change rules. |
| App-token scope must stay least-privilege yet tenant-agnostic | The caller passes its own `repos`; the token scopes to `{shared} + caller + repos` — generic in cicd, explicit per tenant. |
| Harness duplication if moved per repo | **Avoided** — the harness (config/package.json) and driver stay in cicd (reusable); only the spec + fragment + manifest move. |

---

## Decisions

1. ✅ **Approved (2026-07-07)** — decouple the E2E: reusable engine stays in cicd, tenant journeys move to
   their repos.
2. ✅ **Resolved** — the shared engine (driver + shared compose + reusable workflow) **stays in cicd**
   (owner choice, 2026-07-07); rejected "fully self-contained per repo" (duplicates the ~350-line driver
   into every tenant and drifts).
3. ✅ **Resolved** — cross-repo compose merge via absolute `${E2E_WORKSPACE}/<repo>` contexts (Phase-0-validated).
4. ✅ **Resolved** — the tenant contract is a declarative `e2e/manifest.json`; cicd discovers it, so
   onboarding a tenant never edits cicd.

See also the scope guardrail added to [`AGENTS.md`](../../AGENTS.md) and
[`CONTRIBUTING.md`](../../CONTRIBUTING.md), and ADR **D-006** in
[`CHANGELOG_AND_DECISION_LOG.md`](../CHANGELOG_AND_DECISION_LOG.md).
