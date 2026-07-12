# Changelog & Decision Log — kriegerdataforge-cicd

Append-only Architecture Decision Records (`D-NNN`) for this repo, the home of the ecosystem CI/CD
automation and the canonical **agentic-workflow kit** (`kit/common/`). ADRs are immutable: to change
a decision, add a new one that supersedes it — don't edit history.

---

## D-001 — Agentic-Workflow Standard v1.1: vision-propagation, ambition ethos, contract-ownership

- **Date:** 2026-06-27
- **Status:** Accepted
- **Tier / scope:** Epic · repos: all (kit synced from `cicd/kit/common/`)
- **Design doc:** the multi-agent review of the kit (session `wm62gt0vf`) · **Epic tracker:**
  [`kriegerdataforge/docs/epics/agent-kit-distribution.md`](https://github.com/Needless2Say/kriegerdataforge/blob/main/docs/epics/agent-kit-distribution.md)

**Context.** A 7-dimension adversarial review of the agentic-workflow kit (graded B+) found it steers
a capable model well but leaves the owner's two stated priorities to luck: (1) a model on a cross-repo
task read only its *starting* repo's vision and treated the others as code to map; (2) nothing in the
kit licensed ambition, so the conservative default tone ("keep it scoped") nudged models toward timid
minimal patches. Three sharper gaps: the contract-first sequence hard-coded `backend → SDK → frontend`,
which is wrong for per-app APIs (the SDK is auth-only; per-app contracts flow backend-OpenAPI →
frontend client); Claude-only mechanisms (`/code-review ultra`, sub-agents, a hub-only `prompts/` link)
were stated without a provider-neutral fallback; and the template repos — the seed for every future
repo — had no Vision section and pointer files that never routed to `AGENTS.md`.

**Decision.** Ship **Standard v1.1** as additive, byte-identical kit edits plus one new flagship doc:

- **Vision-first across the blast radius** — Discovery now requires reading *every* touched repo's
  `AGENTS.md` Vision & Critical rules before designing; conflicts are escalated to the owner, never
  resolved silently. A per-repo vision table is now a fill-in field in the design-spec and
  epic-tracker templates (the artifact forces the thought).
- **"Aim high, then ship it safely"** — an explicit ethos: unrestricted in *what* you propose,
  disciplined in *how* you land it. Ambition belongs in the plan (as a proposal), restraint in the diff.
- **Contract ownership** — "define each contract in the repo that owns it"; auth/JWT in the SDK,
  per-app APIs via the backend's OpenAPI-generated (read-only) client.
- **Provider-neutral requirements** — adversarial review and parallelism are required *outcomes*; the
  Claude-specific mechanisms are optional accelerants with a manual fallback.
- **A new [`AGENT_OPERATING_STANDARD.md`](../kit/common/docs/agent/AGENT_OPERATING_STANDARD.md)** — the
  human-readable standard with worked examples from a one-line fix to an ecosystem-spanning epic, a
  contract-ownership map, a prompting guide, and a glossary. Added to the synced kit (`KIT_VERSION`
  → v1.1.0).
- **Template repairs** — all four `kriegerdataforge-template-*` repos' pointer files now route to
  `AGENTS.md`, and their `AGENTS.md` carries a fill-in Vision stub, so generated repos are born inside
  the workflow loop with a vision to write.

**Alternatives considered.**

- *Per-repo paths-ignore / leave as-is* — rejected: the gaps are in the kit *content*, not the engine.
- *Inject the kit into `issue-create-repo.yml` at generate time* — superseded (D-001 in the hub log):
  templates are sync targets, so `/generate` is born current without editing the privileged workflow.

**Trade-offs.** The kit grows (one new doc, longer Discovery/contract sections) — accepted, because the
cost of a vision-misaligned cross-repo design dwarfs a few paragraphs of reading. The edits are additive
and byte-identical-safe, so the distribution engine fans them out as ordinary review-gated PRs.

**Consequences.** Bump `kit/KIT_VERSION` → v1.1.0 and run the **Distribute** workflow to propagate. cicd
is sync-excluded, so its root-level kit copies are updated in this same change. Future kit edits must
keep `AGENT_OPERATING_STANDARD.md` consistent with the operational files (the doc defers to them on
conflict). The contract-ownership rule and the identity-decoupling FK split (hub FK vs tenant plain
`user_id`) are now invariants every cross-repo design must respect.

---

## D-002 — Ops Console: issue-form front-ends for privileged operations

- **Date:** 2026-06-27
- **Status:** Accepted
- **Tier / scope:** Epic · repos: `kriegerdataforge-cicd` (effects span the ecosystem)
- **Design doc:** [`docs/design/ops-console.md`](design/ops-console.md)

**Context.** `workflow_dispatch` cannot multi-select (its `choice` input is single-select), so targeting a
subset of repos for kit distribution meant typing exact names. Privileged ops also left no first-class
record. And this repo is **public** (not yet an org), so anyone can open an issue — authorization, not
obscurity, must be the control. GitHub **issue forms** support multi-select `dropdown`s and `checkboxes`,
and the repo already runs a proven issue-form → parser → owner-gated workflow (`issue-create-repo.yml`).

**Decision.** Add an **Ops Console**: issue-form front-ends (`.github/ISSUE_TEMPLATE/ops-*.yml`) for
privileged operations (kit distribution, secret rotation), each driven by a parser workflow that **reuses a
single fail-closed owner-only gate** (`_authorize-owner.yml`, comparing `github.triggering_actor` to
`github.repository_owner`) and calls the **existing engine scripts** (`distribute_kit.py`, `rotate_*.py`).
One engine, multiple front-ends — `workflow_dispatch`/cron are retained for automation and the scheduled
drift/expiry alarms. Trigger is a **manually-applied `ops:*` label** (deliberate go); destructive ops
require a confirmation checkbox; parsed issue content is treated as untrusted (passed via `env:` only,
never inlined into `run:`, and allow-listed before use). No secret value ever appears in an issue.

**Alternatives considered.**

- *`workflow_dispatch` free-text repo list* — shipped as the CLI/automation path, but no multi-select and
  poor discoverability for humans; kept, not removed.
- *A custom web UI / external tool* — rejected: heavyweight; issues already give UI + audit + access control.
- *Auto-applying the trigger label from the form* — rejected: would run the workflow on every opened issue
  (noise/abuse surface). Manual labeling by the owner is the deliberate, owner-only trigger.

**Trade-offs.** More YAML (forms + parser workflows + the reusable gate) and option lists to keep roughly in
sync with the registries — accepted, because the audit trail + multi-select UX + a single centralized
authorization gate are worth it for privileged ops, and it is one shared pattern.

**Consequences.** Create the `ops`, `ops:distribute-kit`, `ops:rotate-secrets` labels. The GH-PAT rotation
flow depends on the owner pre-setting `GH_PACKAGES_PAT_NEW` (GitHub can't generate PATs); the workflow
guards on it. Every new privileged operation should be added as another `ops-*` form + a thin parser
workflow that `needs:` the same `_authorize-owner.yml` gate — never a new ad-hoc gate.

---

## D-003 — Agentic-Workflow Standard v1.2: pre-launch hardening

- **Date:** 2026-06-28
- **Status:** Accepted
- **Tier / scope:** Epic · repos: all (kit synced from `cicd/kit/common/`)
- **Design doc:** the 25-agent stress-test of the v1.1 kit (this session) · **Epic tracker:**
  [`kriegerdataforge/docs/epics/agent-kit-distribution.md`](https://github.com/Needless2Say/kriegerdataforge/blob/main/docs/epics/agent-kit-distribution.md)

**Context.** Before the first ecosystem-wide sync, a 25-agent adversarial stress-test (5 repo-recon
probes + a small-task simulation + a gamification-epic simulation, each finding verified against the
real files) checked the v1.1 kit against the actual repos. It confirmed 11 gaps and discarded 6 false
positives — evidence the standard is sound, but with rough edges an ambitious cross-repo task exposes:
the headline "Vendored byte-identical across every repo" guarantee was literally false pre-sync; the
engine shipped no version marker; the Epic lane mandated feature flags and cross-user leaderboards that
the repos/kit gave no sanctioned way to build; and several smaller "the kit assumes/decides X" gaps.

**Decision.** Ship **Standard v1.2** as additive, byte-identical kit edits (`KIT_VERSION` → v1.2.0):

- **Honest sync wording** — "the kit-sync engine keeps this file byte-identical … drift is flagged and
  re-synced" replaces the absolute "vendored byte-identical" claim, in all four docs.
- **Vendored version marker** — `docs/agent/KIT_VERSION` is added to the synced set so every repo records
  which kit version it carries; `distribute_kit.py` refuses to run if it disagrees with `kit/KIT_VERSION`.
- **Semver-by-impact** mapping in `WORKFLOW.md`/`DEFINITION_OF_DONE.md`, plus a note that the CI version
  check enforces consistency + strictly-ahead, **not** the chosen level.
- **Quick lane** now carries the repo-mandatory post-build-sync reminder (e.g. `make vercel-compact`)
  the Standard lane already had.
- **PR-template-as-DoD is a constraint** — reduce the Testing section to a single `make ci` gate, and
  every command a PR template names must be a real Makefile target (fixes granular/nonexistent-target drift).
- **ADR ids continue a repo's existing scheme** (e.g. `ADR-NNN`) rather than forcing a clashing `D-NNN` series.
- **Epic "integrate & verify"** splits agent (verify on local/preview with the flag forced on) from owner
  (merge the prod-flag/infra slice, authorize prod verification).
- **Feature-flag convention** (see D-004) and **cross-user public-profile contract** (see D-005).
- **Gamification/anti-abuse scenario** added to `skills.md` + a matching `DEFINITION_OF_DONE.md` checkbox.

**Alternatives considered.**

- *Ship v1.1 first, v1.2 after* — rejected: nothing had been synced yet, so one clean v1.2.0 avoids two
  sync waves across every repo.
- *Keep the "byte-identical" wording* — rejected: literally false until synced; the engine-mechanism
  framing is both honest and accurate post-sync.

**Trade-offs.** The kit grows (a flag subsection, an anti-abuse scenario, a contract row) — accepted; the
edits are additive and byte-identical-safe, so the engine fans them out as ordinary review-gated PRs.

**Consequences.** Bump **both** `kit/KIT_VERSION` and `kit/common/docs/agent/KIT_VERSION` → v1.2.0 and run
**Distribute**; cicd is sync-excluded, so its root copies are updated in this same change. The first
ecosystem-wide sync delivers v1.2.0. Repo-local defects the stress-test found — `fitness-app-frontend`'s
`make generate-client` pointing at the **wrong backend** (the hub instead of `fitness-app-backend`), and
two PR templates — are fixed in their own repos' PRs, not here.

---

## D-004 — Feature-flag convention: a simple owned default-off flag

- **Date:** 2026-06-28
- **Status:** Accepted
- **Tier / scope:** Epic · repos: all (kit convention; first used by any flag-gated epic)
- **Design doc:** this session's stress-test (the flag-mechanism gap)

**Context.** The Epic lane mandates "ship dark behind a feature flag, off by default," but no repo has a
flag mechanism and the kit never said how to build one — so an agent would invent one mid-epic, itself an
undesigned new pattern. The owner asked for the best outcome with the most **control and scalability**.

**Decision.** Codify a **tiered** convention in `DESIGN_AND_EPICS.md` §3.3:

- **Default (almost every slice): a simple, owned, default-off flag.** A backend feature → a Pydantic
  `Settings` boolean `FEATURE_<NAME>_ENABLED=False` (the `fitness-app-backend` `reports` pattern). A
  frontend-only feature → `NEXT_PUBLIC_<NAME>_ENABLED` read via `serverEnv` (never bare `process.env`). A
  backend flag the frontend must observe → a small `GET /config/flags` endpoint consumed through the
  regenerated read-only client. Enabled **last** by an owner-merged infra (terraform) slice.
- **Out of scope:** per-user / percentage / cohort rollout, remote kill-switches, or A/B are **not** covered
  by this convention — if a slice needs them, surface it to the owner as a **design decision** before
  building; never hand-roll per-user flag logic.

**Alternatives considered.**

- *Build or adopt a flag service* — not pursued: it's a multi-week effort with its own infra, authz, and
  audit surface; out of scope for the standard, to be raised with the owner only if a concrete need arises.
- *Leave flags undefined / design-gate every time* — rejected: no consistency; every epic re-litigates the basics.

**Trade-offs.** The simple flag has no per-user/percentage targeting — accepted for now; the convention
names the exact escalation trigger so a service is adopted **deliberately**, requirements known, not prematurely.

**Consequences.** `GET /config/flags`-style endpoints are the sanctioned cross-layer mechanism, and "off by
default in `main`" is enforced by the owning backend's setting. The standard does **not** commit to a flag
service; a future need for cohort / percentage / kill-switch rollout is raised with the owner as its own
design decision.

---

## D-005 — Cross-user public-profile resolution: a hub-owned read-only contract

- **Date:** 2026-06-28
- **Status:** Accepted
- **Tier / scope:** Epic · repos: hub (`kriegerdataforge`) owns; all tenant backends consume
- **Design doc:** this session's stress-test (the leaderboard identity gap)

**Context.** Identity decoupling forbids a tenant DB a per-app user/identity table or a cross-DB FK to
`kdf_users`, and the SDK maps `sub` → `KDFUser.username` for the **current** token-holder only. So a feature
that must display **other** users (a leaderboard's names/avatars, social, mentions) had no sanctioned way to
resolve arbitrary `user_id`s — steering an agent toward either a rule-violating per-app user cache or an
unflagged hub change.

**Decision.** Add a **fourth contract-ownership row**: *"Other users' public profile"* is owned by the **hub**
and consumed by tenant backends via a **hub-owned read-only batch endpoint** (e.g. `GET /users/public?ids=…`)
returning display fields only — **never** a per-app user table or cross-DB FK. Because it extends the hub's
identity surface, it **leads the contract-first sequence and carries a design note**. Documented in
`AGENT_OPERATING_STANDARD.md` (contract map + worked example C), `DESIGN_AND_EPICS.md` (Discovery → Identity),
and `skills.md` (the gamification scenario).

**Alternatives considered.**

- *Per-app user cache table synced from the hub* — rejected: violates identity decoupling; stale-data +
  ownership problems.
- *Resolve via the SDK* — rejected: the SDK is auth-only and resolves the current token-holder, not arbitrary
  ids; widening it couples every tenant to a profile contract.

**Trade-offs.** A leaderboard now depends on a hub round-trip (batchable / cacheable) — accepted; it keeps
identity single-sourced in the hub.

**Consequences.** The `GET /users/public` batch endpoint is **hub work to implement** when the first
cross-user-display feature is built: display fields only (no PII beyond the public profile), rate-limited, and
consumed **read-only** by tenant backends.

---

## D-006 — Decouple the Tier-2 E2E tests out of cicd into each tenant repo

- **Date:** 2026-07-07
- **Status:** Accepted
- **Tier / scope:** Epic · repos: `kriegerdataforge-cicd` (engine) + `fitness-app-frontend`,
  `tiffanys-space`, `kriegerdataforge-auth-ui` (journeys), referencing the two app backends
- **Design doc:** [`docs/design/e2e-test-decoupling.md`](design/e2e-test-decoupling.md) · **Log:**
  [`docs/design/e2e-test-decoupling-LOG.md`](design/e2e-test-decoupling-LOG.md)

**Context.** The Tier-2 full-stack E2E was first built entirely under `kriegerdataforge-cicd/e2e/` — including
every *tenant-specific* part. Onboarding one tenant edits cicd in **five** places (a new Playwright spec in
`tests/`, a `profiles:` service block in `docker-compose.e2e.yml`, a `TENANTS` entry + client-cred keys in
`ci_stack.py`, a `CLIENTS` entry in `seed_e2e.py`, and a `journey` enum/`case` in `e2e-compose.yml`). This
directly violates the repo's Tier-1 scope (`CONTRIBUTING.md`): cicd is the **reusable** platform library, but
the `e2e/tests/` folder was becoming a per-tenant graveyard and three engine files carried a hardcoded tenant
registry — so cicd bloats **linearly** with non-reusable content as the platform scales to N tenants. Root
cause: an E2E journey is inherently cross-repo, and the first cut co-located the reusable *engine* with the
tenant-specific *content*.

**Decision.** **Separate the reusable engine from tenant content.** cicd keeps a **tenant-agnostic** engine —
the driver (`ci_stack.py`, made **data-driven**: it discovers each sibling repo's `e2e/manifest.json` instead
of a hardcoded `TENANTS` dict), a `docker-compose.shared.yml` (db + hub + auth-UI only), a generic
`seed_shared.py`, the reusable `e2e-compose.yml` workflow (generic `journey` + `repos` inputs, no enum/repo
list), and the Playwright harness. **Each tenant repo owns its journey as data + a spec** — an `e2e/`
directory with `tests/<tenant>.spec.ts`, a compose **fragment** (only its services, absolute
`${E2E_WORKSPACE}/<repo>` build contexts so multi-`-f` merge resolves correctly — Phase-0-validated), and an
`e2e/manifest.json` the engine reads. **Onboarding a new tenant then touches only that tenant's repo.** Also
added a **scope guardrail** (`AGENTS.md` critical rule #12 + `CONTRIBUTING.md` two-tier rows + a "scope smell
test") so a future model does not re-introduce tenant content here. Migration is phased and
backward-compatible: cicd engine ships additively with the old path kept as a fallback (Phase 1), tenants move
one at a time (Phase 2), then the fallback is deleted (Phase 3) — gates stay dormant throughout.

**Alternatives considered.**

- *Leave the E2E in cicd as-is* — rejected: unbounded per-tenant bloat; violates Tier-1 scope.
- *Fully self-contained per repo (cicd holds nothing E2E-related)* — rejected (owner, 2026-07-07): duplicates
  the ~350-line driver + compose-merge logic + harness into every tenant, which then drift independently —
  *more* total maintenance, and it discards the reusable-workflow benefit that is precisely cicd's purpose.
- *Relative cross-repo compose contexts* — rejected: multi-`-f` merge resolves relative paths against the
  first file's directory (the wrong repo); absolute `${E2E_WORKSPACE}` contexts avoid the trap.

**Trade-offs.** Each tenant carries only its spec, compose fragment, and manifest (the Playwright
config/`package.json` stay shared via the cicd checkout), plus a brief migration window where a
moved-but-not-yet-wired journey must be verified by dispatch — accepted, because the gates are dormant and
Phase 1's fallback keeps everything green until each tenant lands.

**Consequences.** The tenant contract is a declarative `e2e/manifest.json`; cicd must **discover** tenants,
never enumerate them. Future tenant onboarding = **one PR in that tenant's repo** (add `e2e/` + the
`e2e-gate.yml` caller), **zero cicd edits**. The `e2e/README.md` "Promoting the E2E to a merge gate" routing
table and `MANUAL_SETUP.md` tenant-onboarding steps are updated as the phases land (tracked in the log).

---

## D-007 — E2E as a per-repo CI job (composite action), not a callable workflow

- **Date:** 2026-07-07
- **Status:** Accepted
- **Tier / scope:** Epic · repos: `kriegerdataforge-cicd` (composite action) + `fitness-app-frontend`,
  `tiffanys-space`, `kriegerdataforge-auth-ui` (thin per-repo jobs)
- **Design doc:** [`docs/design/e2e-cijob-refactor.md`](design/e2e-cijob-refactor.md) · **Log:**
  [`docs/design/e2e-cijob-refactor-LOG.md`](design/e2e-cijob-refactor-LOG.md) · **Supersedes** the
  `e2e-compose.yml` `workflow_call` gate from D-006's completion.

**Context.** D-006 relocated each journey's *test assets* into its tenant repo and made the driver
data-driven, but left the **reusable workflow** `e2e-compose.yml` (`workflow_call`) still hardcoding
per-tenant content that grows on every onboard: the journey dropdown enum, the App-token `repositories:`
list, and 6 fixed `actions/checkout` steps. So the *gate* path still required a cicd edit per tenant — the
scope creep the epic set out to kill, relocated to the workflow. The owner also wanted the E2E to be a
**real CI job** in each tenant repo, toggled by that repo's own GitHub **variable**, not a callable-workflow
indirection.

**Decision.** Replace the reusable workflow with a **cicd composite action** `.github/actions/run-e2e`
(a reusable *step*, not `workflow_call`) that carries the whole run-logic **generically**: it reads the
**calling repo's `e2e/manifest.json`** for the sibling repos, mints an App token scoped to
`{hub, auth-ui, sdk}` + those repos, checks them out via a token-authenticated clone loop (replacing the
fixed checkout steps), and runs `ci_stack.py up --journey X` → `npm test`. Each tenant repo owns a thin
`.github/workflows/e2e.yml` job gated by `vars.RUN_E2E_GATE` that checks itself out into the sibling layout
and `uses:` the action (passing `journey` + the App secrets as inputs, since composite actions can't read
`secrets`). **No central registry** — control is fully per-repo (the variable + the repo's own manifest);
cicd keeps **no tenant list anywhere**. `e2e-compose.yml` is deleted. Tenant manifests drop the
non-functional `$comment`.

**Alternatives considered.**

- *Keep the reusable `workflow_call` workflow, make it generic via a `repos` input / a cicd registry* —
  rejected by the owner: still a callable-workflow indirection; the owner wants a real repo-owned CI job.
- *Fully self-contained per-repo job (inline checkout + run, no cicd action)* — rejected: duplicates ~40
  lines of orchestration YAML into every tenant repo, which drifts; the composite action keeps the logic
  reusable in cicd (its purpose) while still being a repo-owned job.
- *Central `e2e/registry.json` in cicd as the control plane* — rejected: with a per-repo `RUN_E2E_GATE`
  variable + the manifest as SoT, a registry is a redundant second control surface that must agree with
  the variable.

**Trade-offs.** A composite action is a slightly less common pattern than the ecosystem's reusable
workflows, and the dynamic checkout leg (clone loop + runtime token scope) is only provable on a runner
(validated by the first owner dispatch). Accepted: it's the only shape that is simultaneously a real
repo-owned CI job, reusable (no per-tenant cicd growth), and registry-free.

**Consequences.** Onboarding a tenant = its own `e2e/` assets + a ~15-line `e2e.yml` + flipping
`RUN_E2E_GATE` — **zero cicd edits**, because the action reads the tenant's manifest and never learns tenant
names. `KDF_APP_ID`/`KDF_APP_PRIVATE_KEY` must exist as repo secrets (the `ops-setup-e2e` flow provides
them); its `USE_GITHUB_APP` variable becomes vestigial for E2E (the action always uses the App token) — a
minor future cleanup. Owner manual runs move to `workflow_dispatch` on each tenant `e2e.yml` (repo
write-access gates them; the old `_authorize-owner` gate was only needed because cicd is public).

---

## D-008 — Every repo owns a distinct E2E journey scoped to its dependency subgraph

- **Date:** 2026-07-07
- **Status:** Accepted
- **Tier / scope:** Epic · repos: **all** ecosystem repos gain an `e2e/` journey — the two tenant
  backends (`fitness-app-backend`, `tiffanys-space-backend`) and the hub (`kriegerdataforge`) join the
  three that already have one (`fitness-app-frontend`, `tiffanys-space`, `kriegerdataforge-auth-ui`).
- **Design doc:** [`docs/design/e2e-every-repo-journeys.md`](design/e2e-every-repo-journeys.md) · **Log:**
  [`docs/design/e2e-every-repo-journeys-LOG.md`](design/e2e-every-repo-journeys-LOG.md) · **Builds on**
  D-006 (decoupling) + D-007 (composite action; the action already reads the *caller's* manifest, which is
  what makes this possible with no engine change).

**Context.** D-007 made each repo run the journey defined by its **own** `e2e/manifest.json`. Only the
three journey-owning repos had one. The owner wants **every** repo — including the two tenant backends and
the hub — to have a real full-stack E2E that proves *that repo's* robustness, not just the frontends. The
owner specified, per repo, the exact set of downstream services its journey must stand up.

**Decision.** Every repo owns a **distinct** journey scoped to its **dependency subgraph**: the repo **plus
everything downstream it depends on** (toward the auth DB), and **never its upstream consumers**. Each repo
owns its own `manifest.json` + Playwright spec + (where needed) compose fragment. This is **not** duplication
of D-006's single-ownership rule — each journey is a genuinely *different* stack + assertion, so no two repos
define the same journey:

| Repo | Stack the journey brings up | Assertion |
| --- | --- | --- |
| `kriegerdataforge` (hub) | hub + auth-db | OIDC/auth endpoints against the built image + real DB — extensive |
| `kriegerdataforge-auth-ui` | auth-ui + hub + auth-db | `auth` browser journey (login → consent → code) — exists |
| `fitness-app-backend` | fitness-be + fitness-db + auth-ui + hub + auth-db | headless OIDC login → assert backend API (no frontend) |
| `fitness-app-frontend` | + fitness frontend | full browser journey (login → `/database`) — exists |
| `tiffanys-space-backend` | tiffanys-be + tiffanys-db + identity | headless OIDC login → assert backend API |
| `tiffanys-space` | + tiffanys frontend | full browser journey — exists |

The backend/hub specs **reuse the existing Playwright harness**: they perform a headless OIDC login through
auth-ui to mint a **real** hub token, then use Playwright's API-request context to hit the backend (or the
hub directly). **Zero changes to `ci_stack.py` or the `run-e2e` action** — it already reads the caller's
manifest and runs the staged spec. The new journeys are `app: false` (opt-in); `journey: all` is **not
used** — each repo runs only its own journey.

**Downstream-only is the key property.** A backend PR's gate stands up only the *stable identity layer* it
depends on, **not** its frontend — so the gate never depends on the frontend's `main` being in lockstep.
This is the deliberate cross-repo-lockstep escape hatch: gates reach only downstream, never up.

**Alternatives considered.**

- *Backends/hub re-run their tenant's **browser** journey via a shared reference (a `journey-repo` input on
  the action)* — rejected: it brings up the **consumer** (the frontend) for a backend PR, re-coupling the
  gate to the frontend's `main`; contradicts the owner's downstream-only dependency graph. Also needless —
  each repo owning its own (distinct) manifest is simpler and needs no new action input.
- *Cover backends/hub with pytest integration tests only (no stack E2E)* — rejected: the owner wants
  full-stack proof per repo (built Docker image + real network + real DB), which in-process integration
  tests (`test_oidc_e2e_db.py`, etc.) cannot give.

**Trade-offs.** The backend + hub specs are **net-new** tests (headless OIDC + API assertions) and overlap
somewhat with existing in-process integration tests; accepted for the built-image / real-network coverage
and the per-repo-ownership the owner wants. Each is proven locally then owner-merged, one repo at a time.

**Consequences.** The `e2e-compose.yml` deletion (D-007's last step) now waits until **all** repos are on
the action — the two backend `e2e-gate.yml` callers are replaced by real `e2e.yml` jobs first, so nothing
dangles. Onboarding any future repo = its own `e2e/` subgraph journey + a thin `e2e.yml` — still zero cicd
edits.

---

## D-009 — Agentic-Workflow Standard v1.3: documentation standard + contributor-onboarding template

- **Date:** 2026-07-12
- **Status:** Accepted
- **Tier / scope:** Epic · repos: **all** (kit content, synced from `cicd/kit/common/`)
- **Design doc:** none (additive kit-content change; this entry is the record). Builds on D-001
  (propagation model) and D-003 (v1.2 hardening + the vendored `KIT_VERSION` marker).

**Context.** The 2026-07 ecosystem-wide documentation wave established per-repo conventions the kit
neither mandates nor describes: `docs/guides/CONTRIBUTOR_ONBOARDING.md` in every repo (a shared
8-section spine), README onboarding front doors, the repo-tailored `docs/prompts/` authoring toolkit,
the `docs/` taxonomy, and the deprecate-with-a-banner pattern (proven on the hub's and tiffanys'
stale `SETUP_AND_ONBOARDING.md`). A `/generate`'d repo is born without these conventions, and an
agent has no canonical source for them. Separately, the 2026-06/07 remediation waves produced
hard-won, ecosystem-wide security lessons not yet in `skills.md` (per-request CSP nonce for dynamic
Next apps, fail-closed CSRF defaults, RP-initiated logout, BuildKit `--mount=type=secret` for
install-time tokens, the compactor symbol-collision trap, the no-public-PyPI policy, test-key and
`kdf_sdk.testing` rules).

**Decision.** Ship an **additive kit minor — v1.3.0**:

- **New synced file** `docs/agent/DOCUMENTATION_STANDARD.md` — ground-truth/accuracy discipline, the
  docs taxonomy, the README front-door standard, the contributor-onboarding mandate, the
  `docs/prompts/` toolkit description (tailoring + boundary rules), and deprecate-with-a-banner.
- **New synced template** `docs/agent/templates/contributor-onboarding.template.md` — the proven
  8-section onboarding spine, including the ecosystem-access rows (per-developer `register-dev`
  OIDC clients; fine-grained `GH_PACKAGES_PAT`).
- **Surgical edits** to `WORKFLOW.md` (docs-work pointer; Windows `PYTHONIOENCODING` bump note;
  sequence-PRs-per-repo), `skills.md` (the security-lesson harvest above), `DEFINITION_OF_DONE.md`
  (docs-standard + conditional E2E-journey bullets), and `AGENT_OPERATING_STANDARD.md` (artifacts
  table + maintenance list).
- Registry `files[]` grows **9 → 12**; both `KIT_VERSION` markers bump together to `v1.3.0`.

The per-repo instances (README, `docs/prompts/*`, `CONTRIBUTOR_ONBOARDING.md`) remain per-repo and
are still never synced — the D-002 boundary is unchanged; the kit standardizes and templates them.

**Alternatives considered.**

- *A separate README front-door template file* — rejected: ~15 inherently repo-entangled lines; an
  inline fenced exemplar in the standard suffices and keeps the sync set at +2.
- *Shipping the 7 `docs/prompts/` bodies as kit templates* — rejected for v1.3.0: each prompt is
  shared-body + repo-tailored header, which a byte-identical engine cannot carry; the standard
  documents the toolkit and its tailoring rule instead. Candidate for a future kit minor + ADR.
- *Folding everything into `skills.md` / `WORKFLOW.md`* — rejected: wrong altitude; docs governance
  is a distinct concern, and a new `docs/agent/` file is automatically version-gate-exempt in
  consumers.

**Consequences.** The weekly `check` drift cron reports **all 14 repos drifted until the owner runs
Distribute** (the two new files count as missing) — expected, not an incident. Consumer sync PRs
remain docs-only and version-gate-exempt. The 6 repos lacking README front doors are brought up to
standard in per-repo follow-up PRs (cicd's own README in the same PR as this entry). cicd's root
copies of the kit files are hand-synced in this PR, as always (cicd is sync-excluded).

## D-010 — Reports-ecosystem standard: Projects boards provisioning (engine + ops form)

- **Date:** 2026-07-12
- **Status:** Accepted
- **Tier / scope:** Epic (Wave 1 of 6) · repos: cicd now; reports-sdk / report-form / both app
  stacks / terraform / templates in later waves
- **Design doc:** [`docs/design/reports-ecosystem.md`](design/reports-ecosystem.md) · epic
  tracker: `kriegerdataforge/docs/epics/reports-ecosystem-standard-PLAN.md` (+ `-LOG.md`)

**Context.** The AI bug reporter (submit → PII-redact → AI-cluster → GitHub issue + Projects v2
item) is fully built and deployed, but only inside `fitness-app-backend/api/reports/`, only for
the fitness board, admin-click-only. Tiffany's report UI is broken (its backend never received
the module), no repo can adopt the feature without copy-paste, and the ecosystem has no standard
ticket boards for developers — or the first external collaborator — to work from.

**Decision.** Promote it to an ecosystem standard (owner-approved 7-wave plan; see the hub
tracker). This wave ships the cicd control-plane piece:

- `scripts/projects_registry.json` — 6 user-owned boards (Fitness / Tiffany's Space / Platform /
  Infra / Portfolios / Templates; membership partitions the ecosystem) + the standard field
  schema (Status target-options, Priority, Type, Severity; Repo derived per board).
- `scripts/provision_projects.py` — registry-driven check/execute engine (distribute_kit skeleton
  + rotate_secret error aggregation). Idempotent: adopt-by-title / pinned `existing_node_id`;
  every mutation guarded by an existence read; GraphQL POSTs deliberately never status-retried.
  Auth is **App-first** (no GraphQL `viewer` dependency — App installation tokens have none) with
  an owner-staged classic-PAT fallback (`SECRET_VALUE_NEW`, `project`+`repo`, revoked after) iff
  the API refuses App tokens for user-owned ProjectsV2.
- `ops:provision-projects` issue form + workflow (D-002 pattern: owner-only gate, awk field
  parser, metadata-only issue summary — board node ids are metadata, not secrets).
- What stays deliberately manual (the API can't): built-in **Status** option reshaping, custom
  views, failed collaborator invites — the engine prints exactly what remains; recipes in
  [`docs/guides/PROJECTS_BOARDS.md`](guides/PROJECTS_BOARDS.md).

**Alternatives considered.** One board per repo (rejected: the shipped reporter routes per app;
fe/be work would split across boards) · a long-lived Projects-scoped PAT (rejected: App-first
keeps zero new long-lived credentials) · centralizing all apps' reports in fitness-be (rejected:
per-client audience isolation refuses other apps' JWTs; per-app modules enable template bundling)
· Vercel cron for the later triage schedule (rejected by owner: orchestration must live in GitHub,
cloud-agnostic).

**Consequences.** `agents/README.md`'s brainstormed issue-triage-agent row is superseded for the
bug-report domain (triage runs in-process in each app; cicd only schedules it — the skeleton
remains for the other agent concepts). Wave 2 consumes the printed board node ids
(`GH_REPORTS_*PROJECT_ID`). Later waves add: `ops:distribute-app-secrets` + App-token package
installs (W2.5), npm plumb (W3.5), the disabled weekly triage trigger + `reports_registry.json`
(W4.1), and kit v1.4.0's `REPORTS_STANDARD.md` (W6, D-011).
