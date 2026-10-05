# Changelog & Decision Log, kriegerdataforge-cicd

Append only Architecture Decision Records (`D-NNN`) for this repo, the home of the ecosystem CI/CD
automation and the canonical **agentic workflow kit** (`kit/common/`). ADRs are immutable, to change
a decision, add a new one that supersedes it. Don't edit history.

---

## D-001. Agentic Workflow Standard v1.1. Vision propagation, ambition ethos, contract ownership

- **Date.** 2026-06-27
- **Status.** Accepted
- **Tier / scope:** Epic · repos: all (kit synced from `cicd/kit/common/`)
- **Design doc:** the multi-agent review of the kit (session `wm62gt0vf`) · **Epic tracker:**
  [`kriegerdataforge/docs/epics/agent-kit-distribution.md`](https://github.com/Needless2Say/kriegerdataforge/blob/main/docs/epics/agent-kit-distribution.md)

**Context.** A 7-dimension adversarial review of the agentic workflow kit (graded B+) found it steers
a capable model well but leaves the owner's two stated priorities to luck. (1) a model on a cross repo
task read only its *starting* repo's vision and treated the others as code to map, (2) nothing in the
kit licensed ambition, so the conservative default tone ("keep it scoped") nudged models toward timid
minimal patches. Three sharper gaps. The contract first sequence hard coded `backend → SDK → frontend`,
which is wrong for per app APIs (the SDK is auth only, per app contracts flow backend OpenAPI →
frontend client), Claude only mechanisms (`/code-review ultra`, sub-agents, a hub only `prompts/` link)
were stated without a provider neutral fallback, and the template repos. The seed for every future
repo. Had no Vision section and pointer files that never routed to `AGENTS.md`.

**Decision.** Ship **Standard v1.1** as additive, byte identical kit edits plus one new flagship doc:

- **Vision first across the blast radius.** Discovery now requires reading *every* touched repo's
  `AGENTS.md` Vision & Critical rules before designing. Conflicts are escalated to the owner, never
  resolved silently. A per repo vision table is now a fill in field in the design spec and
  epic tracker templates (the artifact forces the thought).
- **"Aim high, then ship it safely".** An explicit ethos. Unrestricted in *what* you propose,
  disciplined in *how* you land it. Ambition belongs in the plan (as a proposal), restraint in the diff.
- **Contract ownership.** "define each contract in the repo that owns it". Auth/JWT in the SDK,
  per app APIs via the backend's OpenAPI generated (read only) client.
- **Provider neutral requirements.** Adversarial review and parallelism are required *outcomes*. The
  Claude specific mechanisms are optional accelerants with a manual fallback.
- **A new [`AGENT_OPERATING_STANDARD.md`](../kit/common/docs/agent/AGENT_OPERATING_STANDARD.md)**. The
  human readable standard with worked examples from a one line fix to an ecosystem spanning epic, a
  contract ownership map, a prompting guide, and a glossary. Added to the synced kit (`KIT_VERSION`
  → v1.1.0).
- **Template repairs.** All four `kriegerdataforge-template-*` repos' pointer files now route to
  `AGENTS.md`, and their `AGENTS.md` carries a fill in Vision stub, so generated repos are born inside
  the workflow loop with a vision to write.

**Alternatives considered.**

- *Per repo paths ignore / leave as is.* Rejected. The gaps are in the kit *content*, not the engine.
- *Inject the kit into `issue-create-repo.yml` at generate time.* Superseded (D-001 in the hub log):
  templates are sync targets, so `/generate` is born current without editing the privileged workflow.

**Trade-offs.** The kit grows (one new doc, longer Discovery/contract sections), accepted, because the
cost of a vision misaligned cross repo design dwarfs a few paragraphs of reading. The edits are additive
and byte identical safe, so the distribution engine fans them out as ordinary review gated PRs.

**Consequences.** Bump `kit/KIT_VERSION` → v1.1.0 and run the **Distribute** workflow to propagate. cicd
is sync excluded, so its root level kit copies are updated in this same change. Future kit edits must
keep `AGENT_OPERATING_STANDARD.md` consistent with the operational files (the doc defers to them on
conflict). The contract ownership rule and the identity decoupling FK split (hub FK vs tenant plain
`user_id`) are now invariants every cross repo design must respect.

---

## D-002. Ops Console. Issue form front ends for privileged operations

- **Date.** 2026-06-27
- **Status.** Accepted
- **Tier / scope:** Epic · repos: `kriegerdataforge-cicd` (effects span the ecosystem)
- **Design doc.** [`docs/design/ops-console.md`](design/ops-console.md)

**Context.** `workflow_dispatch` cannot multi-select (its `choice` input is single select), so targeting a
subset of repos for kit distribution meant typing exact names. Privileged ops also left no first class
record. And this repo is **public** (not yet an org), so anyone can open an issue, authorization, not
obscurity, must be the control. GitHub **issue forms** support multi-select `dropdown`s and `checkboxes`,
and the repo already runs a proven issue form → parser → owner gated workflow (`issue-create-repo.yml`).

**Decision.** Add an **Ops Console**. Issue form front ends (`.github/ISSUE_TEMPLATE/ops-*.yml`) for
privileged operations (kit distribution, secret rotation), each driven by a parser workflow that **reuses a
single fail closed owner only gate** (`_authorize-owner.yml`, comparing `github.triggering_actor` to
`github.repository_owner`) and calls the **existing engine scripts** (`distribute_kit.py`, `rotate_*.py`).
One engine, multiple front ends, `workflow_dispatch`/cron are retained for automation and the scheduled
drift/expiry alarms. Trigger is a **manually applied `ops:*` label** (deliberate go), destructive ops
require a confirmation checkbox. Parsed issue content is treated as untrusted (passed via `env:` only,
never inlined into `run:`, and allow listed before use). No secret value ever appears in an issue.

**Alternatives considered.**

- *`workflow_dispatch` free text repo list.* Shipped as the CLI/automation path, but no multi-select and
  poor discoverability for humans, kept, not removed.
- *A custom web UI / external tool.* Rejected. Heavyweight. Issues already give UI + audit + access control.
- *Auto applying the trigger label from the form.* Rejected. Would run the workflow on every opened issue
  (noise/abuse surface). Manual labeling by the owner is the deliberate, owner only trigger.

**Trade-offs.** More YAML (forms + parser workflows + the reusable gate) and option lists to keep roughly in
sync with the registries. Accepted, because the audit trail + multi-select UX + a single centralized
authorization gate are worth it for privileged ops, and it is one shared pattern.

**Consequences.** Create the `ops`, `ops:distribute-kit`, `ops:rotate-secrets` labels. The GH PAT rotation
flow depends on the owner pre-setting `GH_PACKAGES_PAT_NEW` (GitHub can't generate PATs). The workflow
guards on it. Every new privileged operation should be added as another `ops-*` form + a thin parser
workflow that `needs:` the same `_authorize-owner.yml` gate. Never a new ad hoc gate.

---

## D-003. Agentic Workflow Standard v1.2, pre-launch hardening

- **Date.** 2026-06-28
- **Status.** Accepted
- **Tier / scope:** Epic · repos: all (kit synced from `cicd/kit/common/`)
- **Design doc:** the 25-agent stress test of the v1.1 kit (this session) · **Epic tracker:**
  [`kriegerdataforge/docs/epics/agent-kit-distribution.md`](https://github.com/Needless2Say/kriegerdataforge/blob/main/docs/epics/agent-kit-distribution.md)

**Context.** Before the first ecosystem wide sync, a 25-agent adversarial stress test (5 repo recon
probes + a small task simulation + a gamification epic simulation, each finding verified against the
real files) checked the v1.1 kit against the actual repos. It confirmed 11 gaps and discarded 6 false
positives. Evidence the standard is sound, but with rough edges an ambitious cross repo task exposes:
the headline "Vendored byte identical across every repo" guarantee was literally false pre-sync. The
engine shipped no version marker. The Epic lane mandated feature flags and cross user leaderboards that
the repos/kit gave no sanctioned way to build, and several smaller "the kit assumes/decides X" gaps.

**Decision.** Ship **Standard v1.2** as additive, byte identical kit edits (`KIT_VERSION` → v1.2.0):

- **Honest sync wording.** "the kit sync engine keeps this file byte identical … drift is flagged and
  re-synced" replaces the absolute "vendored byte identical" claim, in all four docs.
- **Vendored version marker.** `docs/agent/KIT_VERSION` is added to the synced set so every repo records
  which kit version it carries, `distribute_kit.py` refuses to run if it disagrees with `kit/KIT_VERSION`.
- **Semver by impact** mapping in `WORKFLOW.md`/`DEFINITION_OF_DONE.md`, plus a note that the CI version
  check enforces consistency + strictly ahead, **not** the chosen level.
- **Quick lane** now carries the repo mandatory post build sync reminder (e.g. `make vercel-compact`)
  the Standard lane already had.
- **PR template as DoD is a constraint.** Reduce the Testing section to a single `make ci` gate, and
  every command a PR template names must be a real Makefile target (fixes granular/nonexistent-target drift).
- **ADR ids continue a repo's existing scheme** (e.g. `ADR-NNN`) rather than forcing a clashing `D-NNN` series.
- **Epic "integrate & verify"** splits agent (verify on local/preview with the flag forced on) from owner
  (merge the prod-flag/infra slice, authorize prod verification).
- **Feature flag convention** (see D-004) and **cross user public profile contract** (see D-005).
- **Gamification/anti-abuse scenario** added to `skills.md` + a matching `DEFINITION_OF_DONE.md` checkbox.

**Alternatives considered.**

- *Ship v1.1 first, v1.2 after.* Rejected. Nothing had been synced yet, so one clean v1.2.0 avoids two
  sync waves across every repo.
- *Keep the "byte identical" wording.* Rejected. Literally false until synced. The engine mechanism
  framing is both honest and accurate post-sync.

**Trade-offs.** The kit grows (a flag subsection, an anti-abuse scenario, a contract row), accepted. The
edits are additive and byte identical safe, so the engine fans them out as ordinary review gated PRs.

**Consequences.** Bump **both** `kit/KIT_VERSION` and `kit/common/docs/agent/KIT_VERSION` → v1.2.0 and run
**Distribute**. Cicd is sync excluded, so its root copies are updated in this same change. The first
ecosystem wide sync delivers v1.2.0. Repo local defects the stress test found, `fitness-app-frontend`'s
`make generate-client` pointing at the **wrong backend** (the hub instead of `fitness-app-backend`), and
two PR templates. Are fixed in their own repos' PRs, not here.

---

## D-004. Feature flag convention. A simple owned default off flag

- **Date.** 2026-06-28
- **Status.** Accepted
- **Tier / scope:** Epic · repos: all (kit convention, first used by any flag gated epic)
- **Design doc.** This session's stress test (the flag mechanism gap)

**Context.** The Epic lane mandates "ship dark behind a feature flag, off by default," but no repo has a
flag mechanism and the kit never said how to build one, so an agent would invent one mid epic, itself an
undesigned new pattern. The owner asked for the best outcome with the most **control and scalability**.

**Decision.** Codify a **tiered** convention in `DESIGN_AND_EPICS.md` §3.3:

- **Default (almost every slice). A simple, owned, default off flag.** A backend feature → a Pydantic
  `Settings` boolean `FEATURE_<NAME>_ENABLED=False` (the `fitness-app-backend` `reports` pattern). A
  frontend only feature → `NEXT_PUBLIC_<NAME>_ENABLED` read via `serverEnv` (never bare `process.env`). A
  backend flag the frontend must observe → a small `GET /config/flags` endpoint consumed through the
  regenerated read only client. Enabled **last** by an owner merged infra (terraform) slice.
- **Out of scope.** Per user / percentage / cohort rollout, remote kill switches, or A/B are **not** covered
  by this convention. If a slice needs them, surface it to the owner as a **design decision** before
  building. Never hand roll per user flag logic.

**Alternatives considered.**

- *Build or adopt a flag service.* Not pursued. It's a multi-week effort with its own infra, authz, and
  audit surface. Out of scope for the standard, to be raised with the owner only if a concrete need arises.
- *Leave flags undefined / design gate every time.* Rejected. No consistency. Every epic re-litigates the basics.

**Trade-offs.** The simple flag has no per-user/percentage targeting. Accepted for now. The convention
names the exact escalation trigger so a service is adopted **deliberately**, requirements known, not prematurely.

**Consequences.** `GET /config/flags`-style endpoints are the sanctioned cross layer mechanism, and "off by
default in `main`" is enforced by the owning backend's setting. The standard does **not** commit to a flag
service. A future need for cohort / percentage / kill switch rollout is raised with the owner as its own
design decision.

---

## D-005. Cross user public profile resolution. A hub owned read only contract

- **Date.** 2026-06-28
- **Status.** Accepted
- **Tier / scope:** Epic · repos: hub (`kriegerdataforge`) owns. All tenant backends consume
- **Design doc.** This session's stress test (the leaderboard identity gap)

**Context.** Identity decoupling forbids a tenant DB a per app user/identity table or a cross DB FK to
`kdf_users`, and the SDK maps `sub` → `KDFUser.username` for the **current** token holder only. So a feature
that must display **other** users (a leaderboard's names/avatars, social, mentions) had no sanctioned way to
resolve arbitrary `user_id`s. Steering an agent toward either a rule violating per app user cache or an
unflagged hub change.

**Decision.** Add a **fourth contract ownership row**. *"Other users' public profile"* is owned by the **hub**
and consumed by tenant backends via a **hub owned read only batch endpoint** (e.g. `GET /users/public?ids=…`)
returning display fields only, **never** a per app user table or cross DB FK. Because it extends the hub's
identity surface, it **leads the contract first sequence and carries a design note**. Documented in
`AGENT_OPERATING_STANDARD.md` (contract map + worked example C), `DESIGN_AND_EPICS.md` (Discovery → Identity),
and `skills.md` (the gamification scenario).

**Alternatives considered.**

- *Per app user cache table synced from the hub.* Rejected. Violates identity decoupling, stale data +
  ownership problems.
- *Resolve via the SDK.* Rejected. The SDK is auth only and resolves the current token holder, not arbitrary
  ids. Widening it couples every tenant to a profile contract.

**Trade-offs.** A leaderboard now depends on a hub round trip (batchable / cacheable), accepted. It keeps
identity single sourced in the hub.

**Consequences.** The `GET /users/public` batch endpoint is **hub work to implement** when the first
cross user display feature is built. Display fields only (no PII beyond the public profile), rate limited, and
consumed **read only** by tenant backends.

---

## D-006. Decouple the Tier-2 E2E tests out of cicd into each tenant repo

- **Date.** 2026-07-07
- **Status.** Accepted
- **Tier / scope:** Epic · repos: `kriegerdataforge-cicd` (engine) + `fitness-app-frontend`,
  `tiffanys-space`, `kriegerdataforge-auth-ui` (journeys), referencing the two app backends
- **Design doc:** [`docs/design/e2e-test-decoupling.md`](design/e2e-test-decoupling.md) · **Log:**
  [`docs/design/e2e-test-decoupling-LOG.md`](design/e2e-test-decoupling-LOG.md)

**Context.** The Tier-2 full stack E2E was first built entirely under `kriegerdataforge-cicd/e2e/`, including
every *tenant specific* part. Onboarding one tenant edits cicd in **five** places (a new Playwright spec in
`tests/`, a `profiles:` service block in `docker-compose.e2e.yml`, a `TENANTS` entry + client cred keys in
`ci_stack.py`, a `CLIENTS` entry in `seed_e2e.py`, and a `journey` enum/`case` in `e2e-compose.yml`). This
directly violates the repo's Tier-1 scope (`CONTRIBUTING.md`). Cicd is the **reusable** platform library, but
the `e2e/tests/` folder was becoming a per tenant graveyard and three engine files carried a hardcoded tenant
registry, so cicd bloats **linearly** with non-reusable content as the platform scales to N tenants. Root
cause. An E2E journey is inherently cross repo, and the first cut co-located the reusable *engine* with the
tenant specific *content*.

**Decision.** **Separate the reusable engine from tenant content.** cicd keeps a **tenant agnostic** engine.
The driver (`ci_stack.py`, made **data driven**: it discovers each sibling repo's `e2e/manifest.json` instead
of a hardcoded `TENANTS` dict), a `docker-compose.shared.yml` (db + hub + auth-UI only), a generic
`seed_shared.py`, the reusable `e2e-compose.yml` workflow (generic `journey` + `repos` inputs, no enum/repo
list), and the Playwright harness. **Each tenant repo owns its journey as data + a spec**, an `e2e/`
directory with `tests/<tenant>.spec.ts`, a compose **fragment** (only its services, absolute
`${E2E_WORKSPACE}/<repo>` build contexts so multi-`-f` merge resolves correctly, Phase-0-validated), and an
`e2e/manifest.json` the engine reads. **Onboarding a new tenant then touches only that tenant's repo.** Also
added a **scope guardrail** (`AGENTS.md` critical rule #12 + `CONTRIBUTING.md` two tier rows + a "scope smell
test") so a future model does not re-introduce tenant content here. Migration is phased and
backward compatible. Cicd engine ships additively with the old path kept as a fallback (Phase 1), tenants move
one at a time (Phase 2), then the fallback is deleted (Phase 3). Gates stay dormant throughout.

**Alternatives considered.**

- *Leave the E2E in cicd as is.* Rejected. Unbounded per tenant bloat, violates Tier-1 scope.
- *Fully self contained per repo (cicd holds nothing E2E-related).* Rejected (owner, 2026-07-07). Duplicates
  the ~350-line driver + compose merge logic + harness into every tenant, which then drift independently,
  *more* total maintenance, and it discards the reusable workflow benefit that is precisely cicd's purpose.
- *Relative cross repo compose contexts.* Rejected. Multi-`-f` merge resolves relative paths against the
  first file's directory (the wrong repo). Absolute `${E2E_WORKSPACE}` contexts avoid the trap.

**Trade-offs.** Each tenant carries only its spec, compose fragment, and manifest (the Playwright
config/`package.json` stay shared via the cicd checkout), plus a brief migration window where a
moved but not yet wired journey must be verified by dispatch. Accepted, because the gates are dormant and
Phase 1's fallback keeps everything green until each tenant lands.

**Consequences.** The tenant contract is a declarative `e2e/manifest.json`. Cicd must **discover** tenants,
never enumerate them. Future tenant onboarding = **one PR in that tenant's repo** (add `e2e/` + the
`e2e-gate.yml` caller), **zero cicd edits**. The `e2e/README.md` "Promoting the E2E to a merge gate" routing
table and `MANUAL_SETUP.md` tenant onboarding steps are updated as the phases land (tracked in the log).

---

## D-007. E2E as a per repo CI job (composite action), not a callable workflow

- **Date.** 2026-07-07
- **Status.** Accepted
- **Tier / scope:** Epic · repos: `kriegerdataforge-cicd` (composite action) + `fitness-app-frontend`,
  `tiffanys-space`, `kriegerdataforge-auth-ui` (thin per repo jobs)
- **Design doc:** [`docs/design/e2e-cijob-refactor.md`](design/e2e-cijob-refactor.md) · **Log:**
  [`docs/design/e2e-cijob-refactor-LOG.md`](design/e2e-cijob-refactor-LOG.md) · **Supersedes** the
  `e2e-compose.yml` `workflow_call` gate from D-006's completion.

**Context.** D-006 relocated each journey's *test assets* into its tenant repo and made the driver
data driven, but left the **reusable workflow** `e2e-compose.yml` (`workflow_call`) still hardcoding
per tenant content that grows on every onboard. The journey dropdown enum, the App token `repositories:`
list, and 6 fixed `actions/checkout` steps. So the *gate* path still required a cicd edit per tenant. The
scope creep the epic set out to kill, relocated to the workflow. The owner also wanted the E2E to be a
**real CI job** in each tenant repo, toggled by that repo's own GitHub **variable**, not a callable workflow
indirection.

**Decision.** Replace the reusable workflow with a **cicd composite action** `.github/actions/run-e2e`
(a reusable *step*, not `workflow_call`) that carries the whole run logic **generically**. It reads the
**calling repo's `e2e/manifest.json`** for the sibling repos, mints an App token scoped to
`{hub, auth-ui, sdk}` + those repos, checks them out via a token authenticated clone loop (replacing the
fixed checkout steps), and runs `ci_stack.py up --journey X` → `npm test`. Each tenant repo owns a thin
`.github/workflows/e2e.yml` job gated by `vars.RUN_E2E_GATE` that checks itself out into the sibling layout
and `uses:` the action (passing `journey` + the App secrets as inputs, since composite actions can't read
`secrets`). **No central registry**. Control is fully per repo (the variable + the repo's own manifest).
Cicd keeps **no tenant list anywhere**. `e2e-compose.yml` is deleted. Tenant manifests drop the
non-functional `$comment`.

**Alternatives considered.**

- *Keep the reusable `workflow_call` workflow, make it generic via a `repos` input / a cicd registry*.
  Rejected by the owner. Still a callable workflow indirection. The owner wants a real repo owned CI job.
- *Fully self contained per repo job (inline checkout + run, no cicd action).* Rejected. Duplicates ~40
  lines of orchestration YAML into every tenant repo, which drifts. The composite action keeps the logic
  reusable in cicd (its purpose) while still being a repo owned job.
- *Central `e2e/registry.json` in cicd as the control plane.* Rejected, with a per repo `RUN_E2E_GATE`
  variable + the manifest as SoT, a registry is a redundant second control surface that must agree with
  the variable.

**Trade-offs.** A composite action is a slightly less common pattern than the ecosystem's reusable
workflows, and the dynamic checkout leg (clone loop + runtime token scope) is only provable on a runner
(validated by the first owner dispatch). Accepted. It's the only shape that is simultaneously a real
repo owned CI job, reusable (no per tenant cicd growth), and registry-free.

**Consequences.** Onboarding a tenant = its own `e2e/` assets + a ~15-line `e2e.yml` + flipping
`RUN_E2E_GATE`. **zero cicd edits**, because the action reads the tenant's manifest and never learns tenant
names. `KDF_APP_ID`/`KDF_APP_PRIVATE_KEY` must exist as repo secrets (the `ops-setup-e2e` flow provides
them). Its `USE_GITHUB_APP` variable becomes vestigial for E2E (the action always uses the App token), a
minor future cleanup. Owner manual runs move to `workflow_dispatch` on each tenant `e2e.yml` (repo
write access gates them, the old `_authorize-owner` gate was only needed because cicd is public).

---

## D-008. Every repo owns a distinct E2E journey scoped to its dependency subgraph

- **Date.** 2026-07-07
- **Status.** Accepted
- **Tier / scope:** Epic · repos: **all** ecosystem repos gain an `e2e/` journey. The two tenant
  backends (`fitness-app-backend`, `tiffanys-space-backend`) and the hub (`kriegerdataforge`) join the
  three that already have one (`fitness-app-frontend`, `tiffanys-space`, `kriegerdataforge-auth-ui`).
- **Design doc:** [`docs/design/e2e-every-repo-journeys.md`](design/e2e-every-repo-journeys.md) · **Log:**
  [`docs/design/e2e-every-repo-journeys-LOG.md`](design/e2e-every-repo-journeys-LOG.md) · **Builds on**
  D-006 (decoupling) + D-007 (composite action, the action already reads the *caller's* manifest, which is
  what makes this possible with no engine change).

**Context.** D-007 made each repo run the journey defined by its **own** `e2e/manifest.json`. Only the
three journey owning repos had one. The owner wants **every** repo, including the two tenant backends and
the hub, to have a real full stack E2E that proves *that repo's* robustness, not just the frontends. The
owner specified, per repo, the exact set of downstream services its journey must stand up.

**Decision.** Every repo owns a **distinct** journey scoped to its **dependency subgraph**. The repo **plus
everything downstream it depends on** (toward the auth DB), and **never its upstream consumers**. Each repo
owns its own `manifest.json` + Playwright spec + (where needed) compose fragment. This is **not** duplication
of D-006's single ownership rule. Each journey is a genuinely *different* stack + assertion, so no two repos
define the same journey:

| Repo | Stack the journey brings up | Assertion |
| --- | --- | --- |
| `kriegerdataforge` (hub) | hub + auth db | OIDC/auth endpoints against the built image + real DB, extensive |
| `kriegerdataforge-auth-ui` | auth-ui + hub + auth db | `auth` browser journey (login → consent → code), exists |
| `fitness-app-backend` | fitness-be + fitness db + auth-ui + hub + auth db | headless OIDC login → assert backend API (no frontend) |
| `fitness-app-frontend` | + fitness frontend | full browser journey (login → `/database`), exists |
| `tiffanys-space-backend` | tiffanys-be + tiffanys db + identity | headless OIDC login → assert backend API |
| `tiffanys-space` | + tiffanys frontend | full browser journey, exists |

The backend/hub specs **reuse the existing Playwright harness**. They perform a headless OIDC login through
auth-ui to mint a **real** hub token, then use Playwright's API request context to hit the backend (or the
hub directly). **Zero changes to `ci_stack.py` or the `run-e2e` action**. It already reads the caller's
manifest and runs the staged spec. The new journeys are `app: false` (opt in), `journey: all` is **not
used**. Each repo runs only its own journey.

**Downstream only is the key property.** A backend PR's gate stands up only the *stable identity layer* it
depends on, **not** its frontend, so the gate never depends on the frontend's `main` being in lockstep.
This is the deliberate cross repo lockstep escape hatch. Gates reach only downstream, never up.

**Alternatives considered.**

- *Backends/hub re-run their tenant's **browser** journey via a shared reference (a `journey-repo` input on
  the action)*. Rejected. It brings up the **consumer** (the frontend) for a backend PR, re-coupling the
  gate to the frontend's `main`. Contradicts the owner's downstream only dependency graph. Also needless.
  Each repo owning its own (distinct) manifest is simpler and needs no new action input.
- *Cover backends/hub with pytest integration tests only (no stack E2E).* Rejected. The owner wants
  full stack proof per repo (built Docker image + real network + real DB), which in process integration
  tests (`test_oidc_e2e_db.py`, etc.) cannot give.

**Trade-offs.** The backend + hub specs are **net new** tests (headless OIDC + API assertions) and overlap
somewhat with existing in process integration tests. Accepted for the built image / real network coverage
and the per repo ownership the owner wants. Each is proven locally then owner merged, one repo at a time.

**Consequences.** The `e2e-compose.yml` deletion (D-007's last step) now waits until **all** repos are on
the action. The two backend `e2e-gate.yml` callers are replaced by real `e2e.yml` jobs first, so nothing
dangles. Onboarding any future repo = its own `e2e/` subgraph journey + a thin `e2e.yml`, still zero cicd
edits.

---

## D-009. Agentic Workflow Standard v1.3. Documentation standard + contributor onboarding template

- **Date.** 2026-07-12
- **Status.** Accepted
- **Tier / scope:** Epic · repos: **all** (kit content, synced from `cicd/kit/common/`)
- **Design doc.** None (additive kit content change, this entry is the record). Builds on D-001
  (propagation model) and D-003 (v1.2 hardening + the vendored `KIT_VERSION` marker).

**Context.** The 2026-07 ecosystem wide documentation wave established per repo conventions the kit
neither mandates nor describes. `docs/guides/CONTRIBUTOR_ONBOARDING.md` in every repo (a shared
8-section spine), README onboarding front doors, the repo tailored `docs/prompts/` authoring toolkit,
the `docs/` taxonomy, and the deprecate-with-a-banner pattern (proven on the hub's and tiffanys'
stale `SETUP_AND_ONBOARDING.md`). A `/generate`'d repo is born without these conventions, and an
agent has no canonical source for them. Separately, the 2026-06/07 remediation waves produced
hard won, ecosystem wide security lessons not yet in `skills.md` (per request CSP nonce for dynamic
Next apps, fail closed CSRF defaults, RP-initiated logout, BuildKit `--mount=type=secret` for
install time tokens, the compactor symbol collision trap, the no public PyPI policy, test key and
`kdf_sdk.testing` rules).

**Decision.** Ship an **additive kit minor. V1.3.0**:

- **New synced file** `docs/agent/DOCUMENTATION_STANDARD.md`, ground-truth/accuracy discipline, the
  docs taxonomy, the README front door standard, the contributor onboarding mandate, the
  `docs/prompts/` toolkit description (tailoring + boundary rules), and deprecate-with-a-banner.
- **New synced template** `docs/agent/templates/contributor-onboarding.template.md`. The proven
  8-section onboarding spine, including the ecosystem access rows (per developer `register-dev`
  OIDC clients, fine grained `GH_PACKAGES_PAT`).
- **Surgical edits** to `WORKFLOW.md` (docs work pointer, Windows `PYTHONIOENCODING` bump note;
  sequence PRs per repo), `skills.md` (the security lesson harvest above), `DEFINITION_OF_DONE.md`
  (docs standard + conditional E2E-journey bullets), and `AGENT_OPERATING_STANDARD.md` (artifacts
  table + maintenance list).
- Registry `files[]` grows **9 → 12**. Both `KIT_VERSION` markers bump together to `v1.3.0`.

The per repo instances (README, `docs/prompts/*`, `CONTRIBUTOR_ONBOARDING.md`) remain per repo and
are still never synced. The D-002 boundary is unchanged. The kit standardizes and templates them.

**Alternatives considered.**

- *A separate README front door template file.* Rejected. ~15 inherently repo entangled lines, an
  inline fenced exemplar in the standard suffices and keeps the sync set at +2.
- *Shipping the 7 `docs/prompts/` bodies as kit templates.* Rejected for v1.3.0. Each prompt is
  shared body + repo tailored header, which a byte identical engine cannot carry. The standard
  documents the toolkit and its tailoring rule instead. Candidate for a future kit minor + ADR.
- *Folding everything into `skills.md` / `WORKFLOW.md`.* Rejected. Wrong altitude, docs governance
  is a distinct concern, and a new `docs/agent/` file is automatically version gate exempt in
  consumers.

**Consequences.** The weekly `check` drift cron reports **all 14 repos drifted until the owner runs
Distribute** (the two new files count as missing). Expected, not an incident. Consumer sync PRs
remain docs only and version-gate-exempt. The 6 repos lacking README front doors are brought up to
standard in per repo follow up PRs (cicd's own README in the same PR as this entry). cicd's root
copies of the kit files are hand synced in this PR, as always (cicd is sync excluded).

## D-010. Reports ecosystem standard. Projects boards provisioning (engine + ops form)

- **Date.** 2026-07-12
- **Status.** Accepted
- **Tier / scope:** Epic (Wave 1 of 6) · repos: cicd now. Reports-sdk / report-form / both app
  stacks / terraform / templates in later waves
- **Design doc:** [`docs/design/reports-ecosystem.md`](design/reports-ecosystem.md) · epic
  tracker. `kriegerdataforge/docs/epics/reports-ecosystem-standard-PLAN.md` (+ `-LOG.md`)

**Context.** The AI bug reporter (submit → PII redact → AI cluster → GitHub issue + Projects v2
item) is fully built and deployed, but only inside `fitness-app-backend/api/reports/`, only for
the fitness board, admin-click-only. Tiffany's report UI is broken (its backend never received
the module), no repo can adopt the feature without copy paste, and the ecosystem has no standard
ticket boards for developers, or the first external collaborator, to work from.

**Decision.** Promote it to an ecosystem standard (owner approved 7-wave plan, see the hub
tracker). This wave ships the cicd control plane piece:

- `scripts/projects_registry.json`. 6 user owned boards (Fitness / Tiffany's Space / Platform /
  Infra / Portfolios / Templates, membership partitions the ecosystem) + the standard field
  schema (Status target options, Priority, Type, Severity, Repo derived per board).
- `scripts/provision_projects.py`. Registry driven check/execute engine (distribute_kit skeleton
  + rotate_secret error aggregation). Idempotent. Adopt by title / pinned `existing_node_id`.
  Every mutation guarded by an existence read, GraphQL POSTs deliberately never status-retried.
  Auth is **App first** (no GraphQL `viewer` dependency, App installation tokens have none) with
  an owner staged classic PAT fallback (`SECRET_VALUE_NEW`, `project`+`repo`, revoked after) iff
  the API refuses App tokens for user owned ProjectsV2.
- `ops:provision-projects` issue form + workflow (D-002 pattern: owner only gate, awk field
  parser, metadata only issue summary, board node ids are metadata, not secrets).
- What stays deliberately manual (the API can't). Built in **Status** option reshaping, custom
  views, failed collaborator invites. The engine prints exactly what remains, recipes in
  [`docs/guides/PROJECTS_BOARDS.md`](guides/PROJECTS_BOARDS.md).

**Alternatives considered.** One board per repo (rejected: the shipped reporter routes per app;
fe/be work would split across boards) · a long lived Projects scoped PAT (rejected: App first
keeps zero new long lived credentials) · centralizing all apps' reports in fitness-be (rejected:
per client audience isolation refuses other apps' JWTs, per app modules enable template bundling)
· Vercel cron for the later triage schedule (rejected by owner: orchestration must live in GitHub,
cloud agnostic).

**Consequences.** `agents/README.md`'s brainstormed issue triage agent row is superseded for the
bug report domain (triage runs in process in each app, cicd only schedules it, the skeleton
remains for the other agent concepts). Wave 2 consumes the printed board node ids
(`GH_REPORTS_*PROJECT_ID`). Later waves add. `ops:distribute-app-secrets` + App token package
installs (W2.5), npm plumb (W3.5), the disabled weekly triage trigger + `reports_registry.json`
(W4.1), and kit v1.4.0's `REPORTS_STANDARD.md` (W6, D-011).

**Update, 2026-07-12 (W1-ops finding, cicd v0.2.65).** The first live `execute` resolved the open
auth question. **neither a GitHub App installation token nor a fine grained PAT can create/modify
user owned Projects v2**, GitHub exposes a Projects permission only for organizations, so on a
personal account `createProjectV2` on a user `ownerId` is refused (*"does not have permission to
create projects"*). The App path is out (proven live) and so is `CICD_PAT`. It is a *fine grained*
token, so the owner standard "cicd ops use `CICD_PAT`" can't apply to Projects provisioning.
**Resolution.** Provisioning runs on a short lived **classic** PAT with the `project` scope that the
owner stages in `SECRET_VALUE_NEW` for the run and revokes after (`repo` scope optional, only for
automatic repo linking, which the engine now treats as best effort so a `project`-only token still
creates every board + field). `ops-provision-projects.yml` passes `GH_TOKEN: secrets.SECRET_VALUE_NEW`
(App token mint step dropped), `_resolve_token` validates the token with a read probe and prints
classic PAT guidance on refusal. Runtime board *item* writes by the reports app go through the App
installation token (a separate path).

**Update, 2026-07-12 (reserved field fix, cicd v0.2.66).** The first classic PAT `execute` created
all 6 boards + the Priority/Type/Severity fields, then each board failed on the derived **`Repo`**
field with `createProjectV2Field` → *"Name cannot have a reserved value"*. `Repo`/`Repository` is a
**reserved** name. Projects v2 has a built in Repository field (auto populated per item), so a custom
one is both rejected and redundant. Dropped the custom `Repo` field (`_target_fields` now returns just
the standard schema, `_repo_field_options` removed). Repo grouping/filtering uses the built in field.
The 6 created boards' node ids are now **pinned** in `projects_registry.json` (`existing_node_id`) so
re-runs adopt these exact boards by id. Idempotent re-run completes the half provisioned boards
(adopt → skip existing fields → link repos).

**Update, 2026-07-13 (W2.5: App secret distribution + App token package installs, cicd v0.2.67).**
The Wave-2 close out ships the two cicd side pieces the Consequences block promised:

- **`ops:distribute-app-secrets`** (owner requested). `scripts/distribute_app_secrets.py` +
  issue form + workflow (D-002 pattern) copying this repo's `KDF_APP_ID` / `KDF_APP_PRIVATE_KEY`
  to every consumer repo carrying `distribute_source_env` in `secret_registry.json`. It
  generalizes `ops-setup-e2e.yml`'s fixed 6-repo copy step. The registry's 12-repo list (the six
  E2E-journey repos **plus** the two reports package repos and the four templates, the full
  App credential consumer set, and deliberately a superset of the epic plan's ten so the registry
  is the ONE authoritative inventory of copies for the org move cleanup) is now the allow list,
  and the workflow's App token is scoped `secrets:write` to exactly those repos (computed by the
  engine's `targets` mode, never hardcoded). `check` is a read only audit (names + timestamps.
  The API cannot return values), `execute` seals each value to each target's public key
  (idempotent PUT, per target error aggregation). Swapped/missing source envs abort **before**
  any write via shape checks that name the expected format, never the value (unit tested
  invariant, incl. "output never contains a value"). This also closes the §8.3a rotation gap:
  consumer copies of a rotated App key were previously stale until each repo was re-provisioned
  by hand. The runbook now fans out as step 4, before the old key is deleted.
- **`ci-python-*` package installs are App token first**. The five `needs_sdk_auth` lanes
  (tests / lint / typecheck / security / integration) mint a short lived installation token
  (`contents: read` only, auto revoked at job end) when the caller sets `USE_GITHUB_APP` and
  holds the distributed App secrets, falling back to `GH_PACKAGES_PAT` unchanged otherwise
  (non-breaking: no new inputs, `secrets: inherit` already carries the App pair). No
  `repositories:` filter on the mint. The private package set grows (kdf_sdk, kdf_reports, …)
  and the token is read only, so installation wide read beats editing five lanes per new package.
  `cd-python-vercel.yml` deliberately keeps the PAT (Vercel builds are a PAT lane per the epic's
  token model). The npm lanes follow in W3.5.
- **Registries.** `GH_PACKAGES_PAT` gains `kriegerdataforge-reports-sdk` as a repo secret target
  (its CI installs kdf_sdk as a peer dep, the exact class of gap PR #84 fixed),
  `kit_registry.json` repos += `kriegerdataforge-reports-sdk` + `kriegerdataforge-report-form`
  (born with kit v1.3.0, so they enter in sync). Docs. WORKFLOWS.md backfills the W1
  `ops-provision-projects.yml` row (missed in v0.2.64) and adds the new flow,
  SECRET_ROTATION §8.2's PAT recipe now names BOTH package repos (a token scoped to one breaks
  the other's installs).

**Update, 2026-07-13 (W3.5: npm GH Packages token model, the App token plan is NOT viable,
cicd v0.2.68).** The W3 auth spike resolved against the plan's happy path, by GitHub docs
(*"GitHub Packages only supports authentication using a personal access token (classic)"*, plus
the Actions `GITHUB_TOKEN`) and confirmed live by the `@needless2say/report-form` publish
pipeline. **GH Packages rejects fine grained PATs** (so `GH_PACKAGES_PAT` can never serve npm.
There is no scope to add) **and GitHub Apps have no Packages permission at all** (nothing to
grant, the planned "ci nextjs App token npm plumb" is impossible). The plan's documented fallback
activates:

- **`GH_NPM_TOKEN`.** A new classic PAT, `read:packages` ONLY. Is the ecosystem npm install
  credential for consumer CI, Vercel builds, Docker builds, and local dev. New paste mode
  registry entry (repo level secrets on `fitness-app-frontend` + `tiffanys-space`, Vercel
  frontend project env vars with TODO ids the engine skips until filled, Terraform backfill is
  a post epic review item) + rotation recipe §8.2a (first mint adds the `check` block).
- The four `ci-nextjs-*` lanes and `cd-nextjs-vercel.yml` **export `GH_NPM_TOKEN` to `npm ci`**
  (always defined, empty for token less consumers, avoiding npm's "Failed to replace env in
  config" hard error while keeping the 401 fail closed tell). Non-breaking. No inputs changed.
- Publishing needs **no secret at all** (the package repo's own `GITHUB_TOKEN`,
  `packages:write`), and consumer CI can use zero secret per repo **Actions access grants** on
  the package instead of the token. Both documented in the npm template's
  `PRIVATE_GH_PACKAGES.md` (W3.1). Related scope constraint recorded there and in report-form
  D-001. GH Packages package scope must equal the repo owner, so the widget is
  `@needless2say/report-form` until the org move.

**Update, 2026-07-14 (W4: the scheduled triage trigger, disarmed at birth, cicd v0.2.69).**
The doorbell for the per app AI triage. `scripts/trigger_triage.py` +
`scripts/reports_registry.json` (one entry per app × environment) POST each selected app's
`X-Cron-Secret`-gated `POST /reports/triage/cron`. The AI, PII redaction, and GitHub writes all
stay in process in the app (`kdf_reports`).

- **Two workflows, one engine.** `trigger-reports-triage.yml` (weekly `cron '23 9 * * 1'` →
  `--apps enabled --environment prod`, plus `workflow_dispatch`) and the owner gated
  `ops:triage-reports` issue form (dry-run/execute, dev/prod, result commented on the issue,
  D-002 pattern). **Disarmed twice over** (plan directive 8). The schedule job is gated on the
  unset `RUN_REPORTS_TRIAGE` repo variable AND every registry entry ships `enabled: false`.
  Manual runs need neither, so the pipeline is verifiable before it is armed.
- **Failure semantics.** POSTs are never status retried (a `502`-that-triaged must not
  double fire, PL-134 makes true double fires safe anyway). All selected secrets resolve before
  the first POST. Per app failures aggregate. A quiet week is green (`202`, `total_reports=0`).
- **Metadata only output (unit tested).** Success echoes whitelisted scalar batch counters.
  Non-2xx maps to fixed interpretations. Response bodies (which can carry user report content)
  and secret values never reach logs or issue comments.
- **Secrets.** New dual store registry entries `REPORTS_CRON_SECRET_FITNESS_APP` /
  `_TIFFANYS_SPACE` (cicd side copies, authoritative value = Terraform app side, recipe
  §8.13a). **Base url identity is part of the threat model.** The tiffanys URLs were verified
  to serve the Tiffany's Space openapi before being committed. The fitness URLs ship as `TODO_`
  placeholders (their real Vercel domains carry random suffixes, the engine refuses explicit
  requests against placeholders). A cron secret POSTed to a look alike host would leak it.
- Ops guide. `docs/guides/REPORTS_TRIAGE_OPS.md` (arming checklist, per app first time wiring,
  rotation order).

## D-011. Agentic Workflow Standard v1.4. The reports standard joins the kit

- **Date.** 2026-07-14
- **Status.** Accepted
- **Tier / scope:** Epic close out (reports ecosystem D-010, Wave 6) · kit v1.3.0 → **v1.4.0** ·
  all 16 kit synced repos

**Context.** Waves 0–5 built and proved the reports standard end to end, six provisioned boards,
two certified packages (`kdf_reports` v0.2.0, `@needless2say/report-form` v0.2.1), both app
stacks migrated (tiffanys' broken pipeline reconnected), the disarmed weekly trigger, and
dark by default template bundling. Per the epic's directive 9, the standard is documented only
where it was built. Agents landing in any OTHER repo (or a future generated app) had no kit level
statement of what the standard is, what must not be weakened, or where the worked examples live.

**Decision.** Ship an **additive kit minor. V1.4.0**. One new kit file,
`docs/agent/REPORTS_STANDARD.md` (skills.md-style *(app repos)* annotations, since the kit syncs
to every repo type). The pipeline in one paragraph, the two certified packages + tag pinning
rules, backend/frontend adoption recipes (alembic template revision, env block, BFF allow list
gotcha, `GH_NPM_TOKEN` classic only), the trigger enrollment runbook pointer, the DO NOT WEAKEN
security posture (PII redaction boundaries, server stamped `app_slug`, PL-117 label allow list,
fail closed cron, human only Priority, reserved `Repo` field), the six board catalog pointer,
and a per repo type applicability table. Registry `files[]` grows **12 → 13**. Both
`KIT_VERSION` markers bump together to `v1.4.0`. Cicd's root copies hand synced (README index
row included). Rider. `GH_NPM_TOKEN`'s registry targets += `template-nextjs` (W5.2 bundled the
widget there, the secret itself is an owner paste/copy).

**Alternatives considered.** Folding the content into `AGENT_OPERATING_STANDARD.md` (rejected:
it's a domain standard, not an operating principle, skills.md set the precedent for
repo type annotated domain docs) · a per repo doc only in adopting repos (rejected: the kit's
whole point is that every agent sees the same standard, non-adopting repos get the
applicability table).

**Consequences.** Owner runs **Distribute** (`ops:distribute-kit`) to fan v1.4.0 out to the 16
consumer repos (kit only PRs are version gate exempt, the weekly drift alarm stays red until
distributed). Future reports standard changes update the packages first, then this kit doc in
the same wave.

**Epic close out (D-010).** All seven waves delivered: W0 hub tracker · W1 boards engine + 6
live boards (classic PAT finding) · W2 `kdf_reports` v0.1.0 + both backends + terraform +
`ops:distribute-app-secrets` · W3 `@needless2say/report-form` v0.2.1 published privately
(workflow_run publish fix, `GH_NPM_TOKEN` model, GH Packages is classic-PAT/GITHUB_TOKEN only)
+ both frontend swaps (tiffanys pipeline reconnected) · W4 the disarmed weekly trigger +
v0.2.0 board field setting (+ the reports-sdk unit CI silent skip repair) · W5 template
bundling (fastapi dark flag, nextjs widget + example) + collaborator onboarding docs · W6 this
kit release. Post epic review backlog lives at the end of the hub PLAN doc (nextjs parity epic,
hub adoption, fitness TriageDashboard port, terraform backfill of fitness `GH_REPORTS_*`, E2E
journey extension). Runtime arming (cron secrets, base_urls, board Status reshape, schedule
variables) remains owner-paced. The standard ships complete and OFF.

## D-012. Agentic Workflow Standard v1.4.1, docs freshness corrections to the kit

- **Date.** 2026-07-19
- **Status.** Accepted
- **Tier / scope:** Kit patch (docs freshness wave 2026-07-19) · kit v1.4.0 → **v1.4.1** ·
  all 16 kit synced repos

**Context.** The 2026-07-19 docs freshness effort across the ecosystem flagged three defects in
the distributed kit. (1) every identity decoupling passage named the hub's auth table
`kdf_users`. The real table is `kdfusers` (no underscore, verified against the hub's models and
both app backends), (2) the Windows bump caveat (added in D-009) claimed "the bump script's
emoji output can crash on cp1252. Run `PYTHONIOENCODING=utf-8`", which misdescribes repos whose
bump scripts are ASCII only (the npm template family), (3) app centric mechanics shipped
unqualified to every repo type, `WORKFLOW.md` taught vercel-compact-after-`api/`-changes and
OpenAPI client regeneration as if universal, and `DEFINITION_OF_DONE.md`'s conditional sections
(test tiers, migration + rollback, cross repo contract rows) read as demands even for
static export portfolios and package repos.

**Decision.** Ship a **correction only kit patch. V1.4.1** (no files added or removed, registry
`files[]` unchanged at 13). (1) `kdf_users` → `kdfusers` in `skills.md`,
`AGENT_OPERATING_STANDARD.md`, `DEFINITION_OF_DONE.md`, `REPORTS_STANDARD.md`, and the
design spec + contributor onboarding templates, (2) the Windows caveat reworded generically in
`WORKFLOW.md` and the onboarding template. Some repos' bump scripts emit emoji and can crash on
cp1252 Windows consoles, on `UnicodeEncodeError` rerun with `PYTHONUTF8=1`, (3) applicability
qualifiers, not deletions. `WORKFLOW.md`'s Quick lane and Step 4 scope `make vercel-compact` to
repos with an `api/` + Vercel compactor, Epic step 4 gains a one line "OpenAPI/SDK mechanics
apply to repos with an API surface" scoping, and `DEFINITION_OF_DONE.md` gains a scope note
("conditional sections apply only to repos that have that surface") plus a "tiers this repo
actually has" qualifier on the test row. All three `KIT_VERSION` markers bump together, cicd's
root copies hand synced byte-identical.

**Alternatives considered.** Per repo kit forks (rejected: the kit's value is byte identical
sameness, qualifiers keep one text true everywhere) · deleting the app centric sections
(rejected: most kit consumers ARE app repos, scoping is a two line fix) · rewriting the
`kdf_users` mentions inside historical ADRs (rejected: this log is append only, D-005/D-009
record what was written then, this entry supersedes the detail).

**Consequences.** Owner runs **Distribute** (`ops:distribute-kit`) to fan v1.4.1 out to the 16
consumer repos, until then the weekly drift check stays red for the consumer repos (kit only
sync PRs remain version gate exempt). Docs-only. No behavior, contract, or registry shape
change.

## D-013. Version scripts sync. Strict single increment gate + distributed dev script tooling

- **Date.** 2026-08-11
- **Status.** Accepted
- **Tier / scope:** Standard · repos: all 17 consumers (scripts synced from `cicd/scripts/common/`)
  · feature doc: [`docs/features/version-scripts-sync.md`](./features/version-scripts-sync.md)

**Context.** An invalid version jump (`0.10.6 → 0.10.8` in the hub) passed every gate. The
per repo `scripts/bump_version.py` copies. Forked into four drifted variants (plain Python,
npm+lockfile, auth-ui one off, script call). Blindly increment the LOCAL VERSION file, so two
`make bump-patch` runs silently produce +2. Each repo's `ci-version-check` Makefile recipe only
failed on "unchanged" or "behind" (`sort -V`), and the central
`scripts/common/check_version.py` that every consumer CI runs only required "strictly greater".
The one strict +1 implementation (`bump-version-check.yml`, with a dead double read hack) was
consumed solely by this repo's own ci.yml.

**Decision.** (1) **One canonical script family** in `scripts/common/`. `bump_version.py`
(computes the bump FROM `origin/main`'s VERSION: double bump idempotent, bump minor after patch
corrects instead of stacking, local file fallback with a warning), `check_version.py` (strict
single increment vs the base branch + consistency of every version target, legacy flags accepted
as no ops), and `version_targets.py` (shared target resolution, auto detect by presence across
all repo shapes, FastAPI incl. `vercel_api/pyproject.toml`, Python package, Next.js/npm,
VERSION only, with an optional per repo `scripts/version_targets.json` manifest that is
authoritative and hard fails on declared but missing files). One configurable family, never
per type forks. (2) **A script sync engine mirroring the kit's** (ADR D-001). Registry
`scripts/scripts_registry.json` (src→dest, 17 repos = kit's 16 + kriegerdataforge-fmt), marker
`scripts/SCRIPTS_VERSION`, engine `distribute_scripts.py` on a new shared
`common/repo_sync.py` (transport + generic SyncItem fan out extracted from `distribute_kit.py`,
whose CLI and white box tests are unchanged), ops issue form + `ops:distribute-scripts`
label triggered owner gated workflow. Each sync PR also REWRITES the repo's `ci-version-check:`
Makefile recipe (target line + tab indented block, idempotent regex patch) to a thin
`$(PYTHON) scripts/check_version.py --base-branch …` call. (3) **Version gate exemption
extended** registry derived to script sync paths, `Makefile` exempt ONLY on
`chore/scripts-sync-*` head branches. (4) `bump-version-check.yml` rewritten as a thin runner of
the canonical checker.

**Alternatives considered.** Per repo type scripts (rejected: recreates the copy drift disease
this cures) · refuse on invalid bump keeping local file basis (rejected: origin/main basis makes
the failure mode unrepresentable rather than merely detected) · `--registry` parameterization of
distribute_kit.py (rejected: can't express the Makefile patch item, pollutes a working engine) ·
distributing scripts without the Makefile patch (rejected: `make ci` would stay weak locally.
The exact gap that let the jump through).

**Consequences.** Consumer CI gets strict the moment this merges (consumers run the central
script from `.cicd@main`). Local `make ci` gets strict per repo as its sync PR merges. Four
repos (fmt/sdk/reports-sdk/template-python-package) move from consistency only to strict local
checks. Auth-ui gains a local increment check it never had. The `SKIP_INIT` knob and per repo
`CI [x/y]` recipe numbering are retired. Backends' `vercel_api/pyproject.toml` stays covered by
auto detection, and the hub's becomes bump-managed. Sync PRs are review gated, never
auto-merged. Owner runs check → distribute via the ops issue.

## D-014. Vendored script layout. Scripts/kdf_scripts/ excluded from tenant style/lint

- **Date.** 2026-08-11
- **Status.** Accepted
- **Tier / scope:** Standard patch to D-013 · repos: all 17 consumers · SCRIPTS_VERSION 1.0.1 → **1.1.0**

**Context.** The distributed version scripts landed at flat `scripts/` paths inside each
tenant's kdf-fmt (and ruff) scope. They are only guaranteed clean under CICD's configs.
Tenant configs vary (different `[rules.overrides]`, several repos check baseline less), so
sync PRs sometimes failed tenant style CI. A distribution being vetoed by the very
configs it cannot control.

**Decision.** Treat distributed scripts as **vendored code**. They move to
`scripts/kdf_scripts/`, and every tenant's `kdf-fmt.toml` (plus ruff config where one
exists, 4× `ruff.toml` exclude, 4× `pyproject.toml [tool.ruff] extend-exclude`) excludes
that directory. CICD alone governs the style of what it ships. Mechanics. The sync engine
gains **delete items** (`SyncItem.desired = None`, Contents API DELETE, drift iff the file
exists) and per repo item builders. The registry gains `deletes[]`, `kdf_fmt_patch`, and
per repo `ruff_config`. The Makefile patcher path rewrites every script reference with a
negative lookbehind guard (`kdf_scripts/bump_version.py` itself ends with the substring
`scripts/bump_version.py`, a naive replace would double nest on re-runs) before
re-asserting the canonical recipe. The version gate exemption derives from
`files[].dest ∪ deletes[]` and the branch gated config set widens to
{Makefile, kdf-fmt.toml, ruff.toml, pyproject.toml}. Per repo
`scripts/version_targets.json` manifests deliberately stay OUTSIDE the vendor dir
(tenant owned config).

**Alternatives considered.** Teaching kdf-fmt a vendored dir marker convention (rejected:
the owner wants the formatter generic for any codebase, not coupled to this ecosystem's
distribution feature, also needs a tool release + re-pin across 9 repos) · keeping flat
paths with per file excludes in every tenant config (rejected: grows per file, invisible
ownership boundary) · maintaining the canonical scripts clean against all 17 tenant
configs forever (rejected: unbounded maintenance, already failed once).

**Consequences.** One distribute wave (17 PRs). Adds the three files under
`kdf_scripts/`, deletes the flat copies, patches Makefile (`_BUMP` + recipe paths),
kdf-fmt.toml, and the declared ruff config. Future distributed scripts are born excluded
in every repo and template. Minor version (1.1.0), not major. Consumer facing entry
points (`make bump-*`, `make ci-version-check`) are unchanged, only the vendored file
locations moved, and the wave itself performs the migration.

## D-015. Agentic Workflow Standard v1.4.2, the kit names no preview stack

- **Date.** 2026-09-19
- **Status.** Accepted
- **Tier / scope:** Kit patch · kit v1.4.1 → **v1.4.2** · all 16 kit synced repos

**Context.** The ecosystem has three states, LOCAL, DEV and PROD, and only DEV and PROD are
deployments. There is no preview or staging deployment anywhere, every deploy is a production
deploy to its own account. The kit still told an agent to verify an epic "on the local/preview
stack" and to check a repo outside the local compose "against a preview deploy", in the epic
lane of `WORKFLOW.md` and in `DESIGN_AND_EPICS.md` section 3.5. An agent following that text
would look for a deployment that does not exist.

**Decision.** Ship a **correction only kit patch, v1.4.2** (no files added or removed, registry
`files[]` unchanged at 13). Both passages now say the local stack, and a repo outside the local
compose is verified standalone. All three `KIT_VERSION` markers bump together, and the same four
lines change in cicd's root copies.

**Alternatives considered.** Name DEV as the fallback for a repo outside the local compose
(rejected: DEV is a shared deployment, a slice is verified before it merges, and nothing unmerged
reaches DEV) · leave it for the next kit release (rejected: it is four lines, and one consumer
repo had already corrected the sentence locally, which is the drift the kit exists to prevent).

**Consequences.** Owner runs **Distribute** (`ops:distribute-kit`) to fan v1.4.2 out to the 16
consumer repos. They vendor an older kit today, so one sync carries D-011, D-012 and this patch,
and the repo that corrected the sentence locally converges on this text at that sync. Docs-only.
No behavior, contract, or registry shape change. Other mentions of a Vercel preview target in this
repo (secret rotation, deployer tests) name Vercel's own target and are unchanged.

## D-016. The e2e engine declares the deployed shape, and the deploys are put right

- **Date.** 2026-09-25
- **Status.** Accepted
- **Tier / scope:** Engine, action and the two Vercel deploys · one pull request, the auth UI review's Phase C start

**Context.** The auth UI review campaign measured (its Phase B, register rows 5, 6, 31, 40, 41, 42 there and
row 83 in the hub) that the e2e engine could not start the current hub, its compose declared the hub a DEV
deployment over a plain http issuer with no service key, which the hardened hub refuses three times over, and
carried four settings and six `MINIO_*` the hub no longer reads. The action minted its App token from the
branch's manifest, so a branch could widen the token's reach before review, cloned every sibling at its default
branch, so a change spanning two repos could not be tested on a branch, ran whatever journey its input named,
and kept the token in cicd's checkout. The Next.js deploy wrote the deploy token to `$GITHUB_ENV`, where every
install script inherited it, and installed twice. Both deploys granted `id-token: write` to a job holding the
token while the pinned CLI never requests one, and both headers described a reviewer no environment has. The
Python deploy migrated the schema behind whatever release `vercel --prod` had left serving.

**Decision.** One change, the owner's answers of 2026-09-25 to Phase C's design step.

- **The engine has the deployed shape.** The hub and the auth UI declare `local`, the third state, what the
  hub's own suites declare. The issuer is `https://localhost:<port>` behind a Caddy edge inside the stack, the
  shape of the local stack's edge and of Vercel's, under a per run certificate authority `ci_stack.py`
  generates beside the keypair (the authority's key is never written). A Mailpit sink, pinned, receives every
  message the hub sends over the real path, STARTTLS under the run's certificate and a login, the hub trusting
  the authority through `SSL_CERT_FILE`, and a spec reads the links from the sink's API. The service key gate
  is on with a per run key, the browser's address rides `FORWARDED_CLIENT_IP_HEADER`, registration and the
  link bases are set for the lifecycle journeys, the dead settings are gone, and every published port binds
  the loopback interface. `E2E_EDGE_PORT` and `E2E_MAIL_PORT` move the ports beside a local stack. `--target
  runner` builds the auth UI's production image and puts the hub behind a second edge, since that image
  refuses an http hub.
- **The action reads two manifests.** The default branch's, through the API, for the token's reach, and the
  branch's for the journey and the specs, which may name only repositories the default branch's already does.
  The `journey` input is optional and must match the manifest when given. Every sibling is cloned at the
  caller's own branch name when it has one and at its default branch otherwise, `sibling-ref` overriding on a
  manual run. cicd's checkout keeps no credential, and the auth UI's copy of the hub contract is held to the
  hub's recording on every run.
- **The Next.js deploy** trims the token into a masked step output that the pull and the deploy steps read,
  never `$GITHUB_ENV`, and builds once, `vercel build` doing the install from the pulled project settings
  with no token, since it calls no Vercel API.
- **The Python deploy** deploys without the domains, records the schema revision, migrates, smokes the new
  deployment's `/healthz`, undoes the migration when the smoke fails, and only then promotes. An optional
  `VERCEL_AUTOMATION_BYPASS_SECRET` rides on the smoke when deployment protection covers the URL.
- **Both deploys** drop `id-token: write`, say approval happens only where an environment configures a
  reviewer, and name the repository secret in their diagnostics.

**Alternatives considered.** Keying the hub's https rule on the state so the engine could stay on http
(rejected, the rule is the hub's and every state is https, S1's question 1) · packaging the hub's own Python
mail sink as a service (rejected for now, it would need an HTTP face of its own, Mailpit has one) · an allow
list of repositories in cicd for the token (rejected, one more place a tenant is registered, the default
branch manifest is tenant agnostic) · a per repo `ref` input per sibling (rejected, the same branch name in
both repos is the shape a two repo change already takes).

**Consequences.** The first green run of the engine since the hub's hardening, measured 2026-09-25 on the
owner's machine on alternate ports, the auth journey's two tests passing through the edge. Callers of the
action need no change, `journey` still accepted. Callers of the deploys need no change, and the first DEV
deploy proves the token free `vercel build` and the deploy, migrate, smoke, promote order. Every journey repo
needs the two App secrets before its job runs (`ops-setup-e2e`). Pinned by `scripts/tests/test_e2e_engine.py`
and `scripts/tests/test_workflow_contracts.py`. The engine was touched a third time after D-006 froze it, for
the deployed shape alone, still with no tenant name. Recorded in the auth UI's `AUTH_UI_REVIEW_B_ADJUDICATION.md`
section 13 and its plan's section 9.

## D-017. The bump moves a FastAPI app's committed openapi.json, and CI only reads

- **Date.** 2026-09-25
- **Status.** Accepted
- **Tier / scope:** Standard patch to D-013 · repos: all 17 get the script, it acts where a FastAPI app's
  committed spec carries VERSION (today the hub) · SCRIPTS_VERSION 1.2.0 → **1.3.0**

**Context.** The hub's app reads its version from `api/main.py`, a declared target since D-013, so the
`info.version` of its committed `openapi.json` moves with every bump. Two hub unit tests compare that file with a
fresh generation, one of them byte for byte, and the bump did not write it. Every hub pull request bumps, so
every one needed `make openapi` after the bump, and hub #366, #367, #368 and #369 each went red on that one line,
`2 failed` over a spec dump that reads like many failures. On 2026-09-19 the owner declined chaining the
generators into the bump targets, the bump only bumps versions.

**Decision.** `bump_version.py`, the script every repo vendors and a developer runs through `make bump-*`, moves
the `info.version` of a committed root `openapi.json` along with the version targets. It moves the value only when
the spec carries a version being bumped from, the base branch's or the local VERSION, which holds where the app
reads VERSION, and it leaves any other spec alone and says so. The write is surgical, the first `"version"` key,
since a generated document opens with `openapi` and then `info`, and a re-read refuses it unless `info.version` is
what moved. So every other byte stays as the generator wrote it, and a byte for byte spec test holds. The spec is
planned before anything is written, so one the bump cannot move stops it with nothing changed. The owner's rule,
stated 2026-09-25, is that cicd's workflows never change a file in a repo. They check state, run tests, or run
other code that writes no repo file, and writing belongs to the bump script a developer runs. `check_version.py`,
`version_targets.py` and every workflow are unchanged.

**Alternatives considered.** A sixth `openapi` kind in `version_targets.py` (rejected by the owner, that module is
also what the CI version check runs, and the write belongs in the bump script) · chain `make openapi` into
`make bump-*` (declined by the owner on 2026-09-19, the bump only bumps versions) · let the two hub tests ignore
`info.version` (rejected, the committed spec would name a build it does not describe, the drift D-013 declared
`api/main.py` to stop) · stop committing `openapi.json` (rejected, it is the input to the generated clients and the
reviewable contract diff) · move every root `openapi.json` (rejected, `fitness-app-backend` and
`tiffanys-space-backend` commit a spec whose app publishes a literal `1.0.0`, and their spec tests would fail on
the next bump) · parse and re-dump the document (rejected, it matches the generator only while both use the same
dump settings, the surgical write depends on none).

**Consequences.** A repo gets the behavior when its vendored `bump_version.py` reaches 1.3.0 at the next scripts
sync, and the hub then stops needing `make openapi` after a version only bump. `make openapi` stays the step after
an API change, and the two tests still catch a forgotten one. `fitness-app-backend` and `tiffanys-space-backend`
keep their spec untouched, and the bump starts moving it by itself once their apps read VERSION and the spec is
regenerated. No workflow, check, manifest or target kind changes, so nothing has to merge in a set order. Pinned by
`scripts/tests/test_bump_version.py`.

---

## D-018. The first DEV dispatch of the Python deploy, what alembic and Vercel actually answer

- **Date.** 2026-09-25
- **Status.** Accepted
- **Tier / scope:** `cd-python-vercel.yml` and `run-e2e/action.yml` · one pull request, D-016's implementation put
  right, its decision stands

**Context.** The owner dispatched the hub's CD to DEV at 0.12.5 the evening D-016 merged, the first run of the new
order, an hour after a DEV apply. Three things were measured in its log. The migrate step recorded `[Alembic]` as
the revision in place, the first word of the first line the hub's own `alembic/env.py` prints to stdout, so the
seven migrations ran and the undo, when the smoke failed, could not (`Can't locate revision identified by '[Alembic]'`).
The smoke saw a 302 six times, Vercel's deployment protection sending a plain request to `vercel.com/sso-api`,
where the step expected a 401, so its message named a generic failure. And the hub's E2E dispatch of the same
evening never started, GitHub refusing the action at load because two input descriptions carried a
`${{ secrets.* }}` expression as prose, and a composite action has no `secrets` context, which actionlint does
not flag. The database migrated was DEV's, by the host in the hub's `.env.dev`, nothing was promoted, and the
`PROD environment` line in that log is the same print's label for an unset `ENVIRONMENT`.

**Decision.**

- The revision in place is read from `alembic current --verbose`, whose revision lines alembic itself writes as
  `Rev: <id>`, never from the first line of stdout. A report with no `Rev:` line and no `Current revision(s) for`
  header stops the step before the upgrade, so `base` is recorded only when alembic itself reported no revision,
  and a failing alembic fails the step instead of being silenced into an empty capture. The migrate and undo
  steps declare `ENVIRONMENT` from the `environment` input, so a repo's env.py labels its line with the state the
  run deploys to rather than the SDK's fail closed reading of an unset one. It picks no database,
  `DB_DATABASE_URL` does. The report is never printed, its header carries the database URL.
- The smoke reads curl's `%{redirect_url}` beside the status and names Vercel's protection on a redirect to
  `vercel.com/sso-api` as well as on a 401, telling no bypass secret apart from one Vercel refused.
- The action's descriptions name the secret to pass in words. Everything above `runs:` in a composite action is
  literal text, pinned.

**Alternatives considered.** Filtering stdout for a twelve character hex id (rejected, alembic's default id shape
and not a rule of its own, and a custom id would read as an empty database and be undone to `base`) · querying
`alembic_version` directly (rejected, the repo's env.py owns the URL and its driver) · exempting deployment URLs
from the protection (rejected, the bypass secret keeps them closed).

**Consequences.** Pinned by `scripts/tests/test_workflow_contracts.py`, which also runs the migrate step's shell
under bash against an alembic that prints the hub's lines, and `scripts/tests/test_e2e_engine.py`. No input
changes, the tenant backends calling the deploy see the truthful label and nothing else. The hub's DEV release
needs the project's `VERCEL_AUTOMATION_BYPASS_SECRET` in its `dev` environment and a shared rate limit store
applied before its next dispatch, both in the auth UI's `docs/security/DEV_ROLLOUT_RUNBOOK.md`, section 8. DEV's
database is at head with the previous release serving until that dispatch promotes.

## D-019. A release deploys to PROD only after its E2E run passed on that release

- **Date.** 2026-09-26
- **Status.** Accepted
- **Tier / scope:** `cd-nextjs-vercel.yml`, `cd-python-vercel.yml`, `scripts/check_e2e.py`, and one line in every
  consumer's `cd.yml` · one pull request here, the callers' lines ride with their next pull requests

**Context.** The owner deployed the auth provider and both tenant pairs to DEV on 2026-09-26 and signed in across the
two apps. Asked what stood between DEV and PROD, the E2E dispatches of the runbook's Round 2 had never run green, the
one dispatch of the evening before had failed at load on the action's descriptions (D-018). Nothing in the deploys
asked whether they had. The deployer gate answers who may deploy, no gate answered whether the release was tested,
and the owner asked for one, mandatory, refusing with a clear reason and recording its pass to GitHub the way the
deployer check does.

**Decision.** A `verify-e2e` job sits between `authorize` and `deploy` in both Vercel deploys. It resolves the release
tag `v<version>` to its commit, the commit the deploy job checks out, and asks GitHub for a successful run of the
consumer's own E2E workflow on that commit whose jobs ran and passed. On `prod` none means the job fails and the deploy
never runs, the reason on the line and in the step summary with the dispatch to make, on the tag. When one exists the
summary names the run, its number, time and link. On `dev` the same lookup is reported and never denies, DEV is the soak
that precedes the E2E dispatch on the release. The record is GitHub's own, the run on that commit, so nothing is
written anywhere to be forged or to drift, and a run whose job was skipped, the dormant modes, reports `skipped` and
never counts. The listing needs `actions: read`, which a called workflow holds only when its caller grants it, so every
consumer's `cd.yml` grants it on the deploy job, one line each.

**Alternatives considered.** A commit status written by the E2E job and read by the deploy (rejected, a second record
of a fact GitHub already holds, and anyone with write access can post a status) · requiring the E2E as a ruleset
check on `main` (kept as the pull request gate, but it tests the branch, not the release, and a rollback to an older
version would pass on the newest run) · gating `dev` too (rejected, the owner's order is DEV first, then the E2E on the
release, then PROD).

**Consequences.** `scripts/check_e2e.py` (stdlib, unit tested in `scripts/tests/test_check_e2e.py` against a map of the
API's answers) and the job pinned by `scripts/tests/test_workflow_contracts.py`. The consumers' `cd.yml` files carry the
permission line in their working trees, the hub, the auth UI, the four tenant repos and the two templates. A `prod`
dispatch of a release whose E2E has not run on the tag now fails in under a minute and says what to dispatch.

## D-020. A spec that calls the hub direct holds its own service key

- **Date.** 2026-09-26
- **Status.** Accepted
- **Tier / scope:** `e2e/ci_stack.py`, `e2e/docker-compose.shared.yml` · with the hub's `e2e/tests/hub.spec.ts`

**Context.** D-016 turned the hub's service key gate on in the E2E stack, the deployed shape, with one key, the auth
UI's. The hub journey's spec reaches the hub's port directly for discovery, JWKS, the token exchange, userinfo and the
PKCE refusal at `/authorize`, that is the journey's point, the hub's own surface with no proxy in between. The first
dispatch of that journey after D-016, on 2026-09-26, failed three of its four tests, each on the gate's 403, and the one
that passed was the one that only drives the browser through the auth UI. The DEV hub answers the same 403 to a bare
curl of its discovery document, by design, every caller of the hub holds a key and the SDK sends it.

**Decision.** The driver mints a second shared secret, `e2e_service_key`, registers it in the hub's `SERVICE_API_KEYS`
as the `e2e` entry beside `auth-ui`, and writes it to `e2e/.env` as `E2E_HUB_SERVICE_KEY`. A spec that calls the hub
direct sends it as `KDF-Service-Key`, and the hub's spec refuses to run without it rather than skip, a skip would be a
green run that tested nothing. Its own entry rather than the auth UI's, the name a key is registered under is what the
hub's audit rows record, so a spec's calls read as the spec's and the auth UI's as the auth UI's.

**Alternatives considered.** Exempting discovery from the gate in the hub (rejected, the gate is the deployed shape and
the E2E exists to test it) · the spec reaching the hub through the auth UI's proxy (rejected, the journey tests the
hub's surface, the proxy is the auth UI journey's) · reusing `AUTH_UI_SERVICE_KEY` (rejected, the audit rows would name
the auth UI for the spec's calls).

**Consequences.** Pinned by `test_a_spec_that_calls_the_hub_direct_is_handed_its_own_service_key` and the deployed
shape test. The hub's spec change rides with the hub's next pull request, and its E2E reads the engine from `main`
here, so this merges first.

## D-021. The E2E workflow takes a release version, and names its run after it

- **Date.** 2026-09-26
- **Status.** Accepted
- **Tier / scope:** `scripts/check_e2e.py` · the `e2e.yml` of every deploying repo, the hub, the auth UI and the four
  tenant repos

**Context.** D-019's gate finds the release's E2E run by the tag's commit, so the dispatch had to be made on the tag
in the dispatch form's ref picker. The first day of it, the auth UI's and three tenants' tags fell behind `main` on
merges without a bump, the green runs on `main` no longer counted, and the owner asked for the dispatch to take the
release version outright and for the run to mark that version as tested.

**Decision.** Every `e2e.yml` gains a `version` input on its manual dispatch. Given one, the job checks out the tag
`v<version>`, the commit the PROD deploy checks out, names itself `E2E v<version>` and, once the journey passed,
writes the release and commit it tested to its step summary. The gate keeps the lookup by the tag's commit and adds a
second, the workflow's successful dispatched runs whose passed job carries that name. The mark is the run itself,
GitHub's own record, made by the workflow from the same input that chose the checkout, so what the name says was
tested is what the job checked out. No status, tag or file is written anywhere. The input is text, a dispatch form
cannot list a repo's tags, and the release version is what the CD form asks for too, so the two forms read alike.

**Alternatives considered.** A commit status on the tag's commit (rejected in D-019 and still, a second record anyone
with write access can post) · a second tag `e2e-passed-v<version>` pushed by the run (rejected, a write to the repo
from CI, the owner's rule is that CI never writes repo files, and a tag is a ref anyone with write access can move) ·
a choice input listing versions (impossible, a dispatch form's choices are static).

**Consequences.** `scripts/check_e2e.py` searches the newest thirty dispatched runs for the name, pinned by three
tests in `scripts/tests/test_check_e2e.py`. Each consumer's `e2e.yml` carries the input, the job name, the checkout
ref and the summary step in its working tree, riding with that repo's next pull request. A repo without the change
is still gated the D-019 way, on the tag's commit.

## D-022. The E2E App token reaches the reports SDK too

- **Date.** 2026-09-26
- **Status.** Accepted
- **Tier / scope:** `.github/actions/run-e2e/action.yml`

**Context.** The four tenant E2E dispatches of 2026-09-26 failed at the same line, the tenant backend image's
`pip install` cloning `kriegerdataforge-reports-sdk` and GitHub answering `Repository not found`. The action mints its
App token for the repos the journey names plus the shared constants, the hub, the auth UI and `kriegerdataforge-sdk`,
and a GitHub App token answers not found, never forbidden, for a private repo outside its reach. Every tenant backend
has pinned the reports SDK beside the auth SDK since the reports ecosystem epic, and the hub's and the auth UI's
journeys never noticed because neither installs it.

**Decision.** The reports SDK joins the shared constants the token reaches. It is an ecosystem constant like the auth
SDK, one repo every backend installs, so it lives in the action and not in each manifest, D-007's rule.

**Consequences.** Pinned in `test_the_action_reads_the_journey_and_the_token_reach_from_the_right_manifests`. The App
must be installed on the reports SDK repo as it is on the others, or the mint step refuses and says so by name.

## D-023. The tenant fragments meet the D-016 stack, https issuer and a tenant service key

- **Date.** 2026-09-26
- **Status.** Accepted
- **Tier / scope:** `e2e/ci_stack.py`, `e2e/docker-compose.shared.yml` · with the four tenant repos' `e2e/docker-compose.e2e.yml`

**Context.** D-016 put the auth UI behind an https edge and turned the hub's service key gate on, and the hub's and the
auth UI's journeys were made to meet it. The four tenant fragments were not. Each still named the issuer as
`http://localhost:3002`, so the fitness journey's first dispatch after D-022 sent the browser to a plain http authorize
URL nothing answers, and each backend held no service key, so its JWKS fetch from the hub would have been the gate's
403 once a login got that far. The backends verify tokens against the issuer the hub signs, the edge's https origin.

**Decision.** The driver mints a third shared key, `tenant_service_key`, registers it as the `tenant` entry of the
hub's `SERVICE_API_KEYS` and hands it to the compose as `E2E_TENANT_SERVICE_KEY`. Each tenant fragment sets its
backend's `KDF_SERVICE_KEY` to it and names the issuer `https://localhost:3002` wherever it names it, the backends'
`KDF_JWT_ISSUER`, the frontends' `KDF_OIDC_ISSUER` and tiffanys' `AUTH_ISSUER`. The back channels stay http inside the
network, the frontends reach the auth UI at `http://kdf-auth-ui:3000` and the backends the hub at `http://kdf-api:8000`,
so no container needs the run's authority. One key for every tenant backend in a disposable stack, the deployed shape
holds one per tenant, and the audit rows of the stack read `tenant` for all of them.

**Consequences.** Pinned by the deployed shape test. The four fragments ride with their repos' next pull requests, and
a fragment without the change fails at the first login redirect the way the fitness dispatch did. Measured on the
stack once the fragments were right, the next wall was the login submit. The auth UI's `next dev` compiles `/login` on
its first request, the spec's click lands before the page's JavaScript attached, the submit is a native POST the page
answers with itself and empty fields, and a retry that only clicks again submits an empty form. The tenant specs fill
and click on every attempt now, the way the hub's does not yet need to.

## D-024. A release deploys only after its whole test suite passed, not only E2E

- **Date.** 2026-09-27
- **Status.** Accepted
- **Tier / scope:** `ci-python-tests.yml`, `ci-python-integration.yml`, `ci-nextjs-tests.yml`,
  `scripts/check_e2e.py` (the lookup, see the validation below) · every deploying repo's `e2e.yml`, the two
  repos with a `mutation-tests.yml`, the hub and the auth UI, and the hub's `system-tests.yml`

**Context.** D-019 and D-021 gate a PROD deploy on a green E2E run for the release, and nothing else. A
repo's unit and integration lanes only ever run in `ci.yml`, on a PR's head commit before it merges, so
by the time a release tag exists, nothing has run against that tag's own commit, the merge is a new
commit on `main` and `ci.yml` fires on `pull_request` alone. Mutation testing runs weekly from `main` on
a schedule, or by hand per lane, never tied to a release, and is slow enough that the hub and the auth
UI kept it off the PR path on purpose (D-015). Asked to gate PROD on the whole suite, the owner also asked
that PR `ci.yml` stay the fast unit and integration check it is today, and that the cost of the heavier
lanes, including mutation, land on the one path that already exists for a release, the E2E dispatch,
rather than double the cost of every PR or every merge to `main`.

**Decision.** A release dispatch of `e2e.yml` (the `version` input, D-021) grows new jobs, `unit-tests`
and, for a backend, `integration-tests`, calling the same reusable lanes `ci.yml` already calls
(`ci-python-tests.yml`, `ci-python-integration.yml`, `ci-nextjs-tests.yml`), and for the hub and the auth
UI a `mutation-tests` job calling that repo's own `mutation-tests.yml` with `lane: all`. Each of the three
reusable test lanes gains an optional `ref` input, empty by default, so a release dispatch can point it
at the tag `v<version>` instead of the run's own ref, the same commit the `e2e` job's own checkout already
uses. Every new job is gated `if: inputs.version != ''`, so a PR, push or scheduled run of `e2e.yml` skips
them exactly as before, at no added cost, and the `e2e` job's own `if` now also requires each of them to
have succeeded or been skipped before it runs. A failure in any of them therefore fails the whole
workflow run, GitHub never reports it `success`, and `check_e2e.py` denies the deploy the same way it
already denies a missing or failed E2E run (D-019, D-021). The gate's lookup did change, a run with the
input empty no longer counts, see the validation below.
The two mutation workflows drop their `schedule` trigger, mutation testing now runs once per release
instead of on a timer, and keep `workflow_dispatch` for an ad hoc per lane run.

**Alternatives considered.** Running `ci.yml` again on `push` to `main` (rejected, the owner's stated
reason, it doubles CI minutes on every merge for a check the release path can run once instead) ·
looking up the PR that merged into the release commit and reading its pre merge CI status (rejected,
that never tests the actual commit being deployed, only its parent PR's head, and a bad merge could
still ship untested) · dispatching mutation testing as its own workflow per release and having the gate
check for a second, differently named job (rejected, `needs` inside `e2e.yml` gets the same guarantee for
free, one job name for the gate to find, matching D-021's reasoning for a single mark) · gating `dev` too
(rejected for the same reason D-019 rejected it, DEV is the soak that precedes the release dispatch).

**Consequences.** A release now takes longer to clear for PROD, the unit, integration and (on the hub
and the auth UI) mutation lanes run before E2E instead of alongside or before it in a separate workflow,
serial where `ci.yml`'s jobs run in parallel, since `needs` orders them ahead of `e2e`. PR `ci.yml` is
unchanged, still the fast unit and integration check on every PR. A repo without unit or integration
jobs in `e2e.yml` (none, after this change, across the six deploying repos) is gated on the
`E2E v<version>` job name alone. The decision function never learns a new lane's name.

**Validation, 2026-09-27, before the first push.** Each finding was measured, and each fix is pinned by a
test and a mutant.

- **The gate counted a run that skipped every lane.** Its first lookup took any green run whose head is
  the tag's commit, by any job that passed. A push to `main` under `RUN_E2E_CD`, or a dispatch with the
  input empty on the tag or on `main` right after the release, has that head, skips the lanes, names its
  job `E2E`, and passed the gate on the journey alone. A run now counts only when its passed job is
  named `E2E v<version>`, in both lookups. The deny message no longer offers a dispatch on the tag.
- **A release dispatch on any branch counted.** A dispatch runs the workflow of the ref it names, so a
  branch whose `e2e.yml` dropped the lanes and kept the job's name passed the gate. The second lookup
  now takes a run dispatched on the repository's default branch alone, read from the API and not a
  name. `main` is ruleset protected in all seven repos (measured). The first lookup needs no such rule,
  its head is the tag's commit and the workflow it ran is the release's own.
- **The hub's mutation job was handed no secret.** Its install reads `GH_PACKAGES_PAT`, a called
  workflow is handed no secret it is not passed, and the install would have failed on an empty token on
  every release. `secrets: inherit` on the job.
- **The hub's system suite was not in the release.** `system-tests.yml` takes `workflow_call` and a
  `ref`, and `e2e.yml` calls it as a fourth lane the journey needs.
- **The hub's mutation workflow was red on GitHub**, run 35567824725 of 2026-09-21, the one run it ever
  had. The unit control run of the auth and oauth lanes failed on a missing signing keypair, which
  `.env.test` supplies on a developer's machine and no runner holds, and AD-M-33 survived, its line runs
  on Windows alone. The runner makes a throwaway keypair for the unit suite and a mutant may name its
  `platform` (hub D-025). Measured on Linux, Python 3.14.7, an environment holding nothing of the
  machine's, no dotenv file, auth 27 of 27, oauth 18 of 18, admin 17 of 17 and one not run.
- **The auth UI's own suite was red.** Its pins refuse `secrets: inherit` outside `cd.yml`, since
  `e2e.yml` runs on a pull request too, and refuse a `uses:` without a full commit id. The unit lane is
  handed no secret, as `ci.yml` hands it none, and a workflow of the repo called by its path is first
  party.
- **`always()` started the journey in a cancelled run**, `!cancelled()` in all six. **A merge to `main`
  cancelled a release under test**, the push starts `e2e.yml` in the ref's concurrency group, so a
  release dispatch has a group of its own, `e2e-<ref>-<version>`. The called workflows' groups carry
  the ref they are given for the same reason.

Measured after the fixes. The new gate run read only against the six live releases allows all six, four
found on the tag's commit and two dispatched on `main`. `scripts/tests/test_check_e2e.py` holds the new
rules, seven hand mutants of the gate killed. Merge order, this repo first, a consumer's `e2e.yml`
passes the `ref` input and fails at startup against a lane that does not take it.

## D-025. The Next.js apps' integration suites are a lane of their own in a release

- **Date.** 2026-09-27
- **Status.** Accepted. Owner decision.
- **Tier / scope:** `ci-nextjs-integration.yml` (new) · `fitness-app-frontend` and `tiffanys-space`, their
  `e2e.yml` and `Makefile`

**Context.** D-024 gave every release a unit lane, and the backends an integration lane. The two tenant
frontends keep an integration suite too, the flows under `src/__tests__/integration/`, and it ran inside the
unit lane, Jest's one run matches every `__tests__` tree. A release showed unit tests and the journey and no
integration job, and the owner asked for one.

**Decision.** A reusable lane, `ci-nextjs-integration.yml`, the unit lane's own steps with
`make ci-integration-tests` as its one target. Each tenant frontend's `Makefile` gains that target, Jest with
its roots narrowed to the integration tree, and each `e2e.yml` calls the lane on the release tag as a job the
`e2e` job needs. The unit lane is unchanged, it runs the whole Jest suite, the integration tree included.

**Alternatives considered.** Taking the integration tree out of the unit lane (rejected, the coverage
thresholds are set for the whole suite and a pull request's `ci.yml` would lose the tree unless it grew a
job, which D-024 kept fast) · an input on `ci-nextjs-tests.yml` naming the target (rejected, the job would
still be named Unit Tests, and the name is what the owner reads) · a lane for the auth UI (not built, it
holds no integration suite, its integration with the hub is the contract step and the journey of its `e2e`
job, a lane that ran part of its unit suite again under another name would claim a test that does not exist).

**Trade-offs.** The integration tree runs twice in a release, once in each lane, 10 and 22 tests, seconds.
The lane takes no coverage, a part of the suite cannot meet a threshold set for all of it.

**Consequences.** Pinned in `scripts/tests/test_workflow_contracts.py`, the four test lanes check out the
ref they are given and each Next.js lane runs its one target. Merge this repo first, a consumer that calls
a lane `main` does not hold fails at startup.

## D-026. A release runs every check a pull request runs, the consumer's ci.yml called on the tag

- **Date.** 2026-09-27
- **Status.** Accepted. Owner decision.
- **Tier / scope:** every reusable check lane and `secret-scan.yml` (a `ref` input) · the six deploying repos'
  `ci.yml` and `e2e.yml`

**Context.** D-024 and D-025 put the test lanes in a release, unit, integration, system, mutation and the
journey. A pull request is held to more, lint, style, the type check, the build, the bundle's staleness, the
security scans, the secret scan and the production image, and none of it ran on the commit a release ships.
The owner asked for every check of every repo in the run that signs off a PROD deploy.

**Decision.** Each consumer's `ci.yml` takes `workflow_call` and a `ref`, and hands the `ref` to every lane it
calls and every checkout of its own. Its `e2e.yml` calls `./.github/workflows/ci.yml` on `v<version>` as one
lane, `ci`, which the `e2e` job needs, beside the lanes a release alone runs. The test lanes D-024 had copied
into `e2e.yml` are gone, `ci.yml` holds them. Every lane of this repo a consumer calls takes `ref`. The
`ci` job is granted `contents: read` and `pull-requests: read`, what `ci.yml` holds, a called workflow may
hold no more than its caller grants. The version check runs on a pull request alone. The secret scan reads
the tree at the tag, `fetch-depth` 1, when called with a ref.

**Alternatives considered.** Each check as its own job in `e2e.yml` (rejected, a second list of lanes and
their inputs to keep in step with `ci.yml`, the hub's copy of its unit job was one such and is removed) · a
suite workflow per stack in this repo (rejected, the inputs differ per repo and `ci.yml` already holds them)
· CodeQL in the release (rejected, off by default and it files findings, it does not judge a commit).

**Trade-offs.** A release waits on about ten more jobs. `pip-audit` and `npm audit` read the advisory
database of the day, so a release can fail on an advisory published after its pull request merged, which is
the point and can hold a hotfix. A pull request now runs `ci.yml` with one more trigger and an empty `ref`,
its checks and their names are unchanged.

**Consequences.** Merge this repo FIRST. A consumer's `ci.yml` hands `ref` to every lane, and a lane at
`main` that does not take it stops the consumer's `ci.yml` at startup, its pull requests included. Pinned
here in `scripts/tests/test_workflow_contracts.py`, every lane checks out the ref it is given, and in
`scripts/tests/test_consumer_release_workflows.py`, the six consumers' shape, read where their checkouts sit
beside this one. The hub and the auth UI pin their own, mutants RE-M-53 to RE-M-69 and UI-F-121 to UI-F-132.
A release tests the tag, so each consumer needs a release cut after its change merged.

## D-027. The PROD Gate, a workflow of its own, the owner's list of lanes and a verdict job the deploy reads

- **Date.** 2026-09-27
- **Status.** Accepted. Owner decision. Supersedes D-021 and D-024 where they made the journey's job the mark,
  and D-026 where it ran every job of `ci.yml`.
- **Tier / scope:** `scripts/check_prod_gate.py` (was `check_e2e.py`) · `cd-nextjs-vercel.yml`,
  `cd-python-vercel.yml` · three new lanes, `ci-python-system.yml`, `ci-python-mutation.yml`,
  `ci-nextjs-mutation.yml` · the six deploying repos' `prod-gate.yml`, `e2e.yml` and `ci.yml`

**Context.** The first release runs under D-026 failed in five of the six repos, and no test failed in any of
them. Every job that installs a private package stopped at its install, `Invalid username or token`. The
package token `GH_PACKAGES_PAT` expired that day, 2026-09-27, the date `scripts/secret_registry.json` records
for it. It worked in pull request runs at 18:51 UTC and was refused from 19:54 UTC on. The hub's lanes that
call this repo passed, the hub has set `USE_GITHUB_APP` and they mint a token per job, and the hub's own four
jobs, which read the package token alone, failed. The four tenants have the App's credentials and not the
variable, so every lane fell back to the token. The two frontends also failed their integration lane, they
were dispatched for tags cut before the target the lane runs existed.

The owner then named the lanes a release is held to, one list for the FastAPI repos and one for the Next.js
repos, asked for the workflow to be named for what it does, and for the image build to leave the gate and
stay in the repo, Vercel runs no image and a later deploy target will.

**Decision.**

- **A workflow of its own.** Each deploying repo holds `prod-gate.yml`, named PROD Gate, started by a dispatch
  with a required `version` and by nothing else. `e2e.yml` is the journey alone again, callable, and the gate
  calls it as its last lane with the secrets it reads handed over by name.
- **The owner's lanes.** `ci` is the repo's `ci.yml` less the jobs a pull request alone is held to, the version
  check, the style check and the image build, each marked `if: github.event_name == 'pull_request'`. Beside it,
  the integration tree for a Next.js repo, the system suite for a FastAPI repo, and the mutation lanes for
  both. The four tenants held no mutation suite, the two tenant backends no system suite and the auth UI no
  integration suite, so each was written, and three lanes were added here to run them.
- **A verdict job.** The gate's last job needs every lane, runs whenever the run was not cancelled, and passes
  only when every lane's result is `success`. It is named `PROD Gate v<version>`. The verdict is a program
  handed to `python3`, so a test runs it on every result GitHub can write.
- **The deploy reads the gate.** `check_prod_gate.py` reads `prod-gate.yml` and the job `PROD Gate v<version>`.
  A run of `e2e.yml` opens nothing, which closes what D-024 left open, the green release runs made before it,
  each with a job the old check read.
- **The App before the package token.** The three new lanes mint the App's token first, as every lane here
  that installs does, and the hub's own four jobs now do the same.

**Alternatives considered.** Renaming `e2e.yml`'s `name` and leaving it the gate (rejected, every pull request
would then show a skipped check named PROD Gate, and the old release runs would still open PROD) · the verdict
as a job with no condition, which GitHub skips when a lane fails (rejected, the run is red either way and the
owner asked which lane, a job that runs says so) · the verdict in `jq` (rejected, no test on a developer's
machine could run it) · the mutation runner handed out by the scripts sync (rejected for now, it would land in
seventeen repos, the tenants hold a copy each and a test holds the copies equal). **Reopened by D-040.** A file the
sync hands out may now name its repos, and the engine reaches the four that run Python mutants alone.

**Trade-offs.** A release waits on the mutation lanes, minutes each. `pip-audit` and `npm audit` read the
advisories of the day, so a release can fail on one published after its pull request merged. The style check
no longer holds a release, a pull request is where it is held.

**Consequences.** Merge this repo FIRST, a consumer's gate calls three lanes that do not exist before it.
Pinned in `scripts/tests/test_check_prod_gate.py`, `scripts/tests/test_workflow_contracts.py` and
`scripts/tests/test_consumer_release_workflows.py`. The hub and the auth UI pin their own gates. The owner
rotates `GH_PACKAGES_PAT`, the deploy's Vercel build still reads it, and sets `USE_GITHUB_APP` to `true` on the
four tenant repos so their lanes stop depending on it. When a deploy target runs the image, the `if` comes off
the `docker-build` job of that repo's `ci.yml` and the gate builds it. See
[`docs/guides/PROD_GATE.md`](guides/PROD_GATE.md).

## D-028. The KDF Code Review Process is a kit standard, and its guard and launcher live here, unsynced

- **Date.** 2026-09-28
- **Status.** Proposed. Accepted when the owner merges the pull request that carries it.
- **Tier / scope:** Epic · `kit/common/docs/agent/` (`CODE_REVIEW_PROCESS.md` and four templates, kit v1.5.0) ·
  `scripts/kit_registry.json` · `tools/claude-code/` · `scripts/tests/test_claude_code_tools.py` · every kit repo
  receives Markdown only, through the existing sync

**Context.** The owner has had the hub, the auth UI and the SDK reviewed the same way, the repo cut into slices, each
slice read by the session that fixes it, then by fresh Claude and ChatGPT sessions from one brief, then by Sol in
rounds, every finding reproduced and every fix pinned, the whole run kept in files under `docs/security/`. The owner
will run that process often and wants it to be a staple of the ecosystem, templated and as secure as it can be. Until
now it lived in three plan documents and in the habits of the sessions that ran it. Preparing the SDK campaign
measured three gaps in how a session is kept inside its role. A Bash deny rule does not cover the PowerShell tool,
`git tag --list` was refused through one and ran through the other, and PowerShell was this machine's default shell.
Pattern rules miss `git -C repo push origin main`, the spelling an orchestrator working across repos uses all day.
And every session runs under the owner's own GitHub login, so the repository ruleset's admin bypass covers a session
as it covers the owner, and GitHub cannot separate them.

**Decision.**

- **The process is a kit standard.** `docs/agent/CODE_REVIEW_PROCESS.md` holds the roles, the cycle, the rules, the
  severity scale and the Blocks rule, the artifacts and their names, the security model, the runbook and the campaign
  checklist. Four templates hold the shapes that worked, `review-plan`, `review-brief`, `review-report` and
  `review-adjudication`. The kit version is v1.5.0, a minor bump as D-009 did for added files. The five files join
  `kit_registry.json`, and the existing engine carries them to every repo as owner reviewed pull requests.
- **The tooling is not in the kit.** The kit is language agnostic Markdown (D-001), and vendored code trips the
  tenants' own linters (D-014). The guard, the launcher, the wiring checker and the installer live in
  `tools/claude-code/` of this repo and each machine installs them from a clone.
- **The guard is a PreToolUse hook that reads commands like a shell.** It replaces pattern rules as the primary fence
  and leaves them as the second. The owner rules apply in every session, nothing merges, approves, tags, releases,
  deploys or reaches `main`, a push names its branch and goes to `origin`, and settings, hooks, the MCP list and git
  hooks are protected files a session cannot edit. The reviewer role adds read only git, no GitHub CLI, no writing
  shell command, no redirect into a file, no secret file, no outward facing tool and file edits only under
  `docs/security`. The role is chosen by `KDF_ROLE=reviewer` when the session is launched, so no repo needs a settings
  file of its own.
- **The launcher fails closed.** `kdf-review.sh` refuses to start unless the guard is wired and passes two canary calls,
  starts the reviewer with the role and without the owner's self edit switch, and compares a git snapshot taken
  before and after. Anything but a new file under `docs/security` is contamination, exit 3.
- **The owner keeps three acts.** Adding the settings block by hand, the installer never edits settings and the guard
  refuses a session that tries. Setting each reviewed repo's ruleset bypass to "For pull requests only". Merging.
- **Git Bash is the shell.** `defaultShell` is `bash` and the PowerShell tool is denied, so one shell means one rule
  surface. The guard still reads PowerShell commands.

**Alternatives considered.**

- Deny rules alone. Measured insufficient, see the context.
- The tooling in the kit. Rejected, it breaks the Markdown only premise and lands Node and shell in Python repos.
- A reviewer settings file in each repo. Rejected, its edit fences are layout specific, it is one more file per repo,
  and `claude rc` refuses `--settings`, so a phone session could not be given a shared one.
- A `dontAsk` mode with an allow list for reviewers. Rejected, it stalls an unattended review on the first command the
  list forgot, and a probe that runs a script writes wherever the script says anyway.
- A Python guard. Rejected, it needs an interpreter path on every machine, and Node runs wherever Claude Code and the
  Next.js repos do.
- A repo of its own for the tooling. Rejected as more than a few files need, this repo already holds the kit.

**Trade-offs.** The guard adds about 65 ms to each call its matcher names. It needs Node. It reads command text, so a
determined program in a one line script can still write anywhere, which is why the launcher checks git afterward. It
guards a session against its own mistakes and against text that leads it astray, it is not a sandbox. The ruleset
setting is the owner's, no file in a repo can make it.

**Consequences.** After this merges the owner runs Distribute, and each kit repo gets a Markdown only sync pull request
that the version check exempts. Each machine runs `install.sh`, adds the printed block to its settings, and runs
`install.sh --check`. A rule change adds cases to `guard-cases.json` first. A campaign copies the plan template and runs
the cycle, and the SDK's plan and the auth UI's files are the worked examples. See
[`tools/claude-code/README.md`](../tools/claude-code/README.md).

## D-029. The review process scales from one function to the ecosystem, and every review reads a pinned commit

- **Date.** 2026-09-29
- **Status.** Proposed. Accepted when the owner merges the pull request that carries it. Extends D-028.
- **Tier / scope:** Epic · `kit/common/docs/agent/CODE_REVIEW_PROCESS.md` and its four templates, kit v1.6.0 ·
  `tools/claude-code/kdf-review.sh` · `scripts/common/repo_sync.py`, `scripts/distribute_kit.py` · every kit repo
  receives Markdown only, through the existing sync

**Context.** The owner wants the KDF Code Review Process to serve any size of review, a function, a file, several
files, a feature, a repo, several repos, or more. D-028's standard was written for a repo and told the reader not to
use it for a single pull request. The owner also could not reach Codex from a phone, so a Codex review can start only
hours after the Claude review of the same slice. Under D-028 both reviewers read the working tree "at the same time".
A late reviewer would read a tree the orchestrator had changed since, and could open the first reviewer's report,
which lives in the same `docs/security`. Separately, the owner's double submission of the Distribute form on
2026-09-29 made every repo answer 422, an open pull request already existed, which read as sixteen failures. Before
merging, the owner turned down a copy of the repo per reviewer, "this does not scale well. I want the other models to
be able to review the repo itself without me creating these environments", and asked that every model follow
`.gitignore` the way Claude's search does. The same evening the owner opened `.env.local` to every model, "those are
secrets for my local docker setup", approved five enhancements, the guard holding reviewers to `.gitignore`, Codex in
the cloud, the role pointer in every `AGENTS.md`, a check that the pin is pushed and a tool that measures a brief's
line counts, asked for cicd's own housekeeping, and put a sixth, moving secret files out of the folder during a Codex
review, in the backlog.

**Decision.**

- **Scales.** The standard opens with the scale, spot (one function, a few files or a pull request's diff, no plan,
  the brief is the plan), feature, repo, multi repo (one plan in the lead repo, a seam slice per contract), and
  ecosystem (a program of campaigns in the hub). The rules, the severity scale and the security model are the same at
  every scale, the plan, the slices, the Sol rounds and Phase B scale with it.
- **The pin.** At step 2 and step 5 the orchestrator commits the slice's state with the brief and pushes it. The brief
  names that commit. Every reviewer reads the repo folder itself at the pin, with the repo's own environment, one
  review of a folder open at a time, and the orchestrator changes nothing in that folder until both reports are in.
  `kdf-review.sh --pin` checks that the folder is at the pin with no tracked file changed. While a review is open the
  other report of the scope waits in the repo's `.git/kdf-review` folder, out of the working tree, so neither reviewer
  sees the other's, whichever goes first.
- **Codex.** `--prepare` opens Codex's turn in the same folder and prints the one line. `--collect` closes it only when
  nothing but new files under `docs/security` changed and HEAD is still at the pin, and otherwise leaves it open for
  the orchestrator to put right. Codex runs outside Claude Code with no guard, so collect is its fence. Remote tracking
  refs are left out of the check, an editor's background fetch moves them.
- **Both families, always**, rule 15. When one model family cannot run for a while, the other goes ahead and the
  missing review reads a later pin when it can run. It is never skipped, and the slice does not close without it.
- **Follow `.gitignore`**, rule 6 of `AGENT_ROLES.md` for every role. What git ignores is not the project, so no model
  searches, opens or quotes it, and a reviewer reviews only what git tracks. `WORKFLOW.md`, every brief and the
  `AGENTS.md` pointer say so. Measured on 2026-09-29, Claude Code's Grep skips ignored paths but reads one named to it,
  and its Glob and Read do not look at `.gitignore` at all, so the guard now reads Read, Grep and Glob calls. A
  reviewer is refused a path git ignores in those tools and in every shell program that prints a file, the reports the
  launcher holds, a recursive `grep`, `rg -u` and `--no-index`. The hook matcher adds `Read|Grep|Glob`, and every
  such call pays the guard's 65 ms, 83 ms for a reviewer's, which also asks git.
- **`.env.local` is open to every model**, the owner's decision, since it holds the local stack's settings, and
  D-030 makes that safe by moving every credential to `.env.kdf`. A `.env.local` that still holds one stays closed in
  every session, and the charter tells every other model to check with `grep -q` before it opens one. The guard's
  secret list now matches the charter's, every `.env` file but an example, where it had missed `.env.dev` and the
  `.env.local.bak`, `.remote` and `.friend` copies found on the owner's machine.
- **The pin is pushed, and the brief's facts are measured.** `--pin` refuses a commit no branch of `origin` holds.
  `kdf-brief.js` prints the commit line and the scope table's line counts at the pin, and checks a written brief's
  table, and the launcher runs that check before every pinned review.
- **Codex in the cloud.** It reads a review branch that stays at the pin, `review/<pfx>-<slice>`, on GitHub, where no
  ignored file exists, and the owner starts it from a phone. Its report comes back on the branch of the pull request
  it opens, and `--collect-branch` writes it into the folder only when the branch is built on the pin and adds nothing
  but new files under `docs/security`. Every report's header lists what its reviewer read first, and every collect
  warns when the header does not name the pin or that list.
- **cicd's housekeeping.** cicd's own CI runs the secret scan it offers every other repo, and its root copies of the
  kit, which had fallen behind, are synced and held equal to `kit/common` by a test. `kriegerdataforge-fmt` joins the
  kit registry and the Platform board. `AGENTS.md` names `make ci`, which exists.
- **A fresh review before merging.** Two fresh sessions read the kit and the tooling on 2026-09-29, and every
  finding was reproduced before it was fixed. A reviewer's edit to a tracked file under `docs/security`, a brief, a
  plan or a log, now fails the review, and the guard refuses a reviewer that write. The orchestrator writes a report's
  adjudication rows only once both reports of the pin are in, so the second reviewer never reads them. A reviewer never
  starts, stops or resets the running stack and probes it through the tests or a script. A mutant the brief names is
  the one edit a reviewer may make, restored with `git status --porcelain` unchanged. A cloud reviewer's commit of its
  report is its one git write. A late pin under rule 15 carries the first family's report, so its brief names what to
  skip. The template links resolve where the templates are copied to.
- **Distribute can run twice.** Both engines skip a file whose sync branch copy already matches, and look for an open
  pull request from the sync branch before opening one. A second run brings the branch up to date and prints "PR
  already open" in place of a 422.
- **Roles for every model.** The owner asked that the limits the guard enforces on Claude also reach the models that
  read only `AGENTS.md` and the kit. A new kit file, `docs/agent/AGENT_ROLES.md`, writes four roles for any model or
  tool, implementer by default, orchestrator, reviewer and chat reader, and ten rules every role keeps, the guard's
  owner rules in words and `.gitignore`. `WORKFLOW.md`, which every `AGENTS.md` sends an agent to for every task,
  opens with them, and every review brief states the reviewer's role in its own text, since a reviewer of any model
  reads its brief. The guard and the charter change together.

**Alternatives considered.**

- A git worktree copy per reviewer at the pin, set up by a command per repo. Built first, and measured on the SDK at
  `97d2fe9`, a copy set up from public packages in 32 seconds ran all 887 tests and `mypy` clean. Rejected by the
  owner, each review needs an environment of its own, a virtual environment or `node_modules`, and Codex would be
  opened in a folder made for it. Its two gains, a copy holds no secret and the orchestrator works on meanwhile, are
  traded for the folder the owner already uses.
- The late reviewer reads the moved tree and is told not to open the other report. Rejected, independence would rest
  on an instruction, and the late reviewer would read code the first never saw.
- Codex skipped at step 2 when it cannot run, and kept for step 5. Rejected, the owner's decision is that both models
  read every slice twice.
- The roles written only into `WORKFLOW.md` and the briefs. The owner wanted the pointer in every `AGENTS.md` too.
  `AGENTS.md` is per repo and not synced, so it is a pull request per repo with a version bump each. This repo's
  carries the pointer now, the SDK's rides with its review's first slice, and the others follow the v1.6.0 sync, so
  the page they point to is there first.
- Moving the secret files out of the folder while Codex reads it. Held in the backlog by the owner, issue #236. A reviewer's
  tests and the running stack read those files, and a move that is cut off between out and back leaves a repo without
  its settings. Codex in the cloud gives the same protection with nothing moved.

**Trade-offs.** A review freezes its folder. The orchestrator reads, plans and works in other repos meanwhile, and a
slice waits for Codex as long as Codex waits for the owner, unless Codex runs in the cloud. Codex on the owner's
machine reads the folder that holds the owner's local secret files, and its sandbox limits what it writes, not what it
reads, so rules 5 and 6 alone keep it from them, a `.env.local` that still holds a package token included. Codex in
the cloud reads GitHub, where no ignored file exists. For a model that does not run the guard the roles are
instructions, not enforcement, and what holds it is its own sandbox, collect for a reviewer, and GitHub's rulesets.
Every Read, Grep and Glob call now costs a guard run.

**Consequences.** After this merges the owner reinstalls the guard, adds `Read|Grep|Glob` to the hook matcher, then
swaps `Read(**/.env.local)` in the deny list for `Read(**/.env.kdf)`, `Read(**/.env.dev)` and `Read(**/.env.prod)`, in
that order, and runs Distribute once, kit v1.6.0. A `.env.local` that still holds a credential stays closed until it
is split under D-030. Every slice's step 2 pins, and the SDK plan's section 13 runs both reviewers in the SDK folder
with no setup. The launcher's tests prove the pushed pin, the pin check, the brief check, one review of a folder at a
time, the held report in both orders, collect's fence, the cloud branch's fence, and the recovery of a Claude run that
was cut off.

## D-030. Two local env files, `.env.local` open to every model and `.env.kdf` closed, and secret files closed to every session

- **Date.** 2026-09-29
- **Status.** Proposed. Accepted when the owner merges the pull request that carries it, cicd #235. Each repo adopts
  it in a pull request of its own.
- **Tier / scope:** Epic · kit `skills.md`, `docs/agent/AGENT_ROLES.md` rule 5 and the contributor onboarding template ·
  `tools/claude-code/kdf-guard.js` and `check-wiring.js` · then every repo's env examples, Makefile, compose,
  `.gitignore` and onboarding doc

**Context.** The owner opened `.env.local` to every model on 2026-09-29, for the local docker stack. The app repos
also keep real credentials there, the GitHub package tokens and, for a collaborator without a hub checkout, the SSO
client secret the DEV hub issued, and the hub's example adds third party keys. Moving secret files out of the folder
while a reviewer reads it went to the backlog, #236. The owner's answer, "why not have 2 .env files for local",
"`.env.local` for setup of the docker containers to run" and "`.env.kdf` for github tokens and the sso secrets that
are sensitive", so it is "not spread out among alot of different files". The owner keeps `.env.dev` and `.env.prod`
for admin scripts against the DEV and PROD databases, "leave those files alone", and a future tenant may keep its own.
The owner also asked that secret files be protected in every session, not only in reviews, and settled the spelling,
`.env.dev` and `.env.prod`.

**Decision.**

- **`.env.local`** holds every value that works only on this machine, local database and MinIO passwords, local
  signing keys, session secrets, ports and URLs. It is open to every model once its repo has adopted the standard, a
  tracked `.env.kdf.example` beside it, and only while it holds none of the credentials named there or built in.
  Until then it fails closed, since it may hold anything. The fresh review found why, the hub's `vercel_api/.env.local`,
  which `vercel env pull` wrote, holds Vercel and database credentials no built in name covered.
- **`.env.kdf`** holds every credential that works beyond this machine, `GH_PACKAGES_PAT`, `GH_NPM_TOKEN`, the hub's
  `KDF_OIDC_CLIENT_SECRET` and `KDF_SERVICE_KEY`, and third party keys such as `AUTH_RESEND_API_KEY`,
  `AUTH_TWILIO_AUTH_TOKEN` and `AUTH_ADMIN_EMAIL_PASSWORD`. It is closed, and it replaces `.env.github`. Each file has
  a tracked example, and a repo's `.env.kdf.example` names its own credentials.
- **`.env.test`, `.env.dev` and `.env.prod`** stay as they are, closed. A session starts a stack or a test through the
  repo's make target. The spelling is `.env.dev` and `.env.prod` everywhere, the kit's onboarding template included.
- **Secret files are closed to every session.** The guard refuses a read, write, copy, source or pass of one, in the
  shell and to Read, Grep, Edit and Write, and allows only a check that one exists. A redirect counts whatever the
  program, since the fresh review found `ls . > .env.kdf` passing, and so does a curl style `@file`. A search pattern
  that names no file, `'^\.env'`, is not a path. A `.env.local` that is not open counts as a secret file.
  `check-wiring.js` recommends Read denies for `.env.kdf`, `.env.dev` and `.env.prod` as a second fence, and adds
  `WebFetch|WebSearch` to the matcher, so a reviewer, who downloads nothing, is refused the web too.

**Alternatives considered.**

- A file per kind of credential, `.env.github` for tokens and another for SSO secrets. Rejected, the owner wants one
  closed file.
- Moving the secret files out of the folder during a review. In the backlog, #236, a crash or a running stack makes it
  unsafe.
- Letting `source` and `--env-file` pass a secret file, since they print nothing. Rejected, a sourced file is one `env`
  away from printed, and the make targets already read the files for the commands that need them.

**Trade-offs.** Each repo needs one adoption pull request, its examples split, its Makefile reading the tokens from
`.env.kdf`, compose handing a container only the `.env.kdf` values it needs, `.gitignore` covering `.env.kdf` and
tracking `.env.kdf.example`, and its onboarding doc. Measured on 2026-09-29, the Next.js template and terraform do not
ignore `.env.kdf` yet, and ten repos would ignore `.env.kdf.example`. Until a repo's `.env.local` is split, the guard
keeps it closed while it holds a credential. A session can no longer create `.env.kdf` from its example, the owner
fills it.

**Consequences.** Each repo gets one pull request carrying its env split, and its `AGENTS.md` role pointer follows in
a pull request of its own. The owner splits their own `.env.local` files, moving the credential lines to `.env.kdf`,
never a session. `.env.dev` and `.env.prod` are left alone.

**Refined during the rollout, 2026-09-29.** The owner asked for the rollout before #235 merged, "go through all of my
repos and create the .env.kdf.example file", so the adoption pull requests opened that night, one per repo, while a
repo whose clone held the owner's uncommitted work was changed in a worktree of its own. Two findings of the sessions
doing it changed the standard. Compose loads `.env.kdf` after `.env.local`, so an empty line in a copied example
blanked a value `.env.local` still held, and every line of `.env.kdf.example` now starts commented out, so a copy
overrides nothing until a person fills it. The guard read a repo's credential names only from active lines, and it now
reads commented ones too, so a `.env.local` holding such a name stays closed. cicd adopted the standard in #235
itself, and its E2E stack reads the sibling repos' package tokens from `.env.kdf` first.

## D-031. Every review is archived in its repo, in a folder dated the day it opened, laid out by how it ran

- **Date.** 2026-09-30
- **Status.** Proposed. Accepted when the owner merges the pull request that carries it. Kit v1.7.0, reaching every
  repo with the next Distribute.
- **Tier / scope:** Epic · kit `docs/agent/CODE_REVIEW_PROCESS.md` sections 1, 3, 4, 5, 7, 9, 10, 11, 12 and 14,
  `AGENT_ROLES.md`, `WORKFLOW.md`, `DOCUMENTATION_STANDARD.md`, the four review templates, a new
  `review-readme.template.md`, the kit README and registry · `tools/claude-code/kdf-guard.js`, `kdf-review.sh`,
  `kdf-brief.js`, their README and tests · then every repo's `AGENTS.md` role pointer, its code review prompt and its
  past reviews, one pull request per repo

**Context.** The owner, 2026-09-30, "I want claude to archive the prompts in the repo its reviewing for me to have a
tracked archive of every review that gets completed", "organized by folder names with dates, as in the review was
initialized on the start date so I can review past reviews by looking at the directory names", and "the inside of that
directory should be organized in a manner that makes sense to how the review went, like by rounds". The first draft of
this decision put the archive at `docs/security/reviews/`. The owner moved it, "I prefer the docs/reviews/ directory
more because the reviews are code reviews and they wont be all dedicated for security", and asked for "all of the past
code reviews" to be organized the same way, "so that its easier for me and other agents to look through". Until now a
review's files sat flat in `docs/security/`, named by prefix and slice, beside every security document, the review
prompt of the documentation toolkit wrote to `docs/code_review/`, and the Sol dispatches, the only prompts not written
to a repo, lived on a Claude Artifact page alone. The owner keeps Codex on the one line prompt that names a brief in the
repo. The SDK review session also found that a brief could never name the commit that holds it.

**Decision.**

- **One root, `docs/reviews/`, and one folder per review,** `docs/reviews/<YYYY-MM-DD>-<scope>/` in the repo it reads.
  The date is the day the review opened, the day the owner asked for it, and it never changes, so the folder names
  list the reviews in the order they began. `<scope>` is the prefix in lower case with a few words when they help.
  `docs/reviews/README.md` is the archive's front door, one line per review, newest first.
- **The reviewer write zone moves with it.** The guard lets a reviewer write files only under `docs/reviews`, the
  launcher refuses a report or a Codex report anywhere else, and its contamination check and `--collect-branch` accept
  only new files there. `docs/security/` holds the repo's security posture, its audits, threat notes, runbooks and the
  register, and no reviewer writes in it. One root and not both, least privilege.
- **Inside, the review as it ran.** A `README.md` index from the new template, the plan at the root from the feature
  scale up, a folder per slice, `s1-<name>` on to `phase-b`, and in each the adjudication log and a folder per step that
  sends a prompt or receives an answer, `step-2-review`, `step-4-sol/round-<n>`, `step-5-final` and
  `step-5-second-read-<n>`. A spot review has no slice folder. The file names do not change, so a file read alone still
  names its review and slice, and the finding ids do not change.
- **Every prompt is kept.** The brief and both reports sit together in their step folder. Each Sol dispatch is written
  to its round folder word for word as the page holds it, and each answer word for word as the owner pasted it back,
  before it is adjudicated. The Artifact page stays the place the owner copies from.
- **The pin a brief can name.** Step 2 commits the slice's state, then the brief alone in a second commit, and that
  second commit is the pin. The brief names the state commit and says the pin is the commit that adds the brief on top
  of it, `git rev-parse HEAD` printing the pin and `git rev-parse HEAD~1` the state. `kdf-brief.js facts`, run on the
  state, prints that line.
- **Across repos** the folder name is the same in every repo, the lead repo's holds the plan and the seam slices, and
  every other repo's README names it. A review that grows keeps its folder.
- **Past reviews move in.** The flat reviews in `docs/security/` and the `docs/code_review/` areas move into dated
  folders under `docs/reviews/`, each dated by the day it began and laid out by how it ran, its rounds, slices or areas,
  with their text unchanged and only the links that point at them fixed. Audits, their trackers and the register stay
  in `docs/security/`. A review still running moves into its folder with its next pull request.

**Alternatives considered.**

- `docs/security/reviews/`, the first draft, which changed no fence. Rejected by the owner, the reviews are code
  reviews and not all of them are about security.
- `docs/review/` and `docs/code-review/`, which the owner also offered. `docs/reviews/` was the owner's first choice,
  and it matches the plural folders beside it, `docs/guides/`, `docs/features/`, `docs/epics/`.
- Keeping `docs/code_review/` for the review prompt's reports. Folded in, one home for every code review.
- Both roots writable during a transition. Rejected, no running review writes under `docs/security` any more, and a
  second zone would only widen what a reviewer may touch.
- The scale or the closing date in the folder name. Rejected, a review can grow into a larger scale and closes weeks
  after it opens, and a folder must not be renamed while links point at it. The README carries both.
- Shorter file names inside the folders, `PROMPT.md` and `REPORT.md`. Rejected, the launcher's one line, the finding ids
  and a file opened on its own all read better with the full name.

**Trade-offs.** Every repo's `AGENTS.md` role pointer names the zone, so each repo needs a pull request of its own,
which also points its code review prompt at `docs/reviews/` and moves its past reviews in. Until the owner reinstalls
the guard, a Claude reviewer is still held to `docs/security`, so no review pins a brief under `docs/reviews/` before
that. The launcher's lines grow longer, a step folder sits three levels under `docs/reviews/`. The tests prove the
zone at depth, guard cases for a nested report allowed, for `docs/security`, a look alike folder and a traversal
refused, and a launcher run through the held report and collect with nested paths.

**Consequences.** Kit v1.7.0, cicd's own copies and its own `AGENTS.md` pointer in step, and Distribute opens a sync
pull request in every repo. After merging, the owner pulls the cicd clone, runs `bash tools/claude-code/install.sh`
and `--check`. Each repo's pull request carries its pointer, its code review prompt and its past reviews. The SDK
review, open since 2026-09-28, holds S1's pin until the new guard is installed, and moves its plan and S1's files into
`docs/reviews/2026-09-28-sdk/` with S1's pull request.

## D-032. What a review finds that cicd owns is fixed here as it is found, and a package token is one step's

- **Date.** 2026-10-01
- **Status.** Proposed. Accepted when the owner merges the pull request that carries it. Kit v1.8.0 and the version
  scripts 1.4.0, reaching every repo with the next Distribute. The reusable lanes take effect at the merge, every repo
  calls them at `main`.
- **Tier / scope:** Standard · the eight reusable lanes `ci-python-*.yml` that can clone a private package ·
  `scripts/common/check_version.py` and `bump_version.py` · `tools/claude-code/kdf-review.sh`, its README and tests ·
  kit `skills.md` and `docs/agent/CODE_REVIEW_PROCESS.md`

**Context.** The first slice of the kdf-sdk review, S1, left five items for cicd in its adjudication log, each a
register row for later. Its reviewers also asked whether the package token, which the SDK's own canary keeps from a
backend's test suite, was out of that suite's reach. It was not. On Linux a process reads the environment of another
process of the same user from `/proc`, measured in a container, and a suite read the token from the process that
started it. The SDK's canary now runs in two steps, the install with the token and the suites in a step that never held
it. Every reusable Python lane here had the same exposure in a wider form, it wrote the token into the job's global
git config, a file every later step reads, the tests among them. The owner, 2026-10-01, "I agree with the change in
how the build works to avoid any sensitive secrets leaking during the build process so please proceed with that and
make any necessary changes to the agentic workflow docs in the cicd repo so I can distribute it across all repos",
and "keep updating the cicd repo agentic workflow kit as you go and find new issues and fixes for them and I will
distribute the fix when the entire review is finished in the kdf-sdk repo".

**Decision.**

- **A package token is one step's.** Each of the eight lanes hands the token to the one step that clones, the install
  step, the style lane's install of the formatter, and the audit step of the security lane, through git's per process
  settings in that step's `env`, `GIT_CONFIG_COUNT`, `GIT_CONFIG_KEY_0` and `GIT_CONFIG_VALUE_0`. Nothing is written
  to a git config file, and no later step names the token. A caller that does not ask for package access gets a count
  of zero. The mint of the App's token is unchanged.
- **The security lane pins its two tools.** `bandit` and `pip-audit` install at a version the lane names, 1.9.4 and
  2.10.1, the hub's and the SDK's pins, and a caller may name another. They were installed by a bare name, the newest
  release on the day.
- **The version scripts leave a full clone full.** `check_version.py` and `bump_version.py` fetched the base branch
  at a depth of one commit in every clone, which turned a developer's full clone shallow. They ask git first and
  pass the depth only in a clone that is already shallow, a runner's checkout.
- **On a runner, a version check that could not fetch does not pass.** It skipped the increment check with a warning
  whenever the base could not be read. With `GITHUB_ACTIONS` set, a fetch that failed with no base to read is a
  failure. A new repo whose `main` holds no `VERSION` yet, and a developer offline, still get the warning.
- **The review launcher holds a reviewer's notes with its report.** While a second reviewer reads, every other
  untracked file in the brief's folder waits out of the tree beside the first report and comes back with it. The SDK
  review's third narrow read left three probe files there and the orchestrator moved them out by hand.
- **The process says where such findings go.** What a review finds that cicd owns is fixed here by a pull request as
  it is found, and the slice's log names the pull request. The playbook gains the rules behind these fixes, the token
  as one step's, the verdict job of a required check on `always()`, an allowlist for tooling that runs another repo's
  tests, every tool pinned, a mutant that dies of its rule's assertion, and a list held name by name in its test.

**Alternatives considered.**

- Two jobs in place of two steps, the clone of the private repositories in a job that holds the secrets and every
  step that runs a repo's code in a job that names none. It is the only shape that also holds against a process that
  becomes root, a hosted runner grants `sudo` and root reads the runner's own memory, where every secret the job
  names sits, the App's private key among them. Not taken here, it hands private sources between jobs as artifacts
  and changes every caller. Recorded as the next step, the owner's decision.
- Writing the git config and removing it after the install. Rejected, a step that fails in between leaves the file,
  the file is on disk while the install's own build hooks run, and the environment is the smaller mechanism.
- Failing the version check whenever the base is unreadable. Rejected, a repo's first pull request and a developer
  offline are both honest cases.

**Trade-offs.** No session dispatches a workflow. One of the eight lanes ran on GitHub all the same, the style lane,
which this repo's own CI calls from the pull request's tree. On pull request 245 it minted the App's token and
installed the private formatter through the step's environment, with no step that writes a git config. The other
seven carry the same block and run first on the next pull request of a Python repo after the merge. What holds them
until then, `actionlint` on all eight, text level contract tests of each lane's steps, and the mechanism measured
with git on Windows and on Linux, a count of zero reads no setting, a count of one rewrites the URL, and no config
file is written. Every caller's install command was read, each is `pip install` or
`make setup`, and no suite of the hub, the two tenant backends, the template, the reports package or the formatter
installs or clones in its test step. `cd-python-vercel.yml` still writes the token into the git config of its deploy
job, which holds the deploy secrets either way, and `.github/actions/run-e2e` still installs `cryptography` by a bare
name. Both are left for the owner's word.

**Consequences.** Kit v1.8.0 and scripts 1.4.0, cicd's own copies in step. After the merge the first pull request of
any Python repo proves the lanes, and a red install there is this change. The owner runs Distribute once, when the
SDK review is done. Later slices of that review add to the kit the same way, one pull request per batch of findings.
The SDK's adjudication log names this pull request where its register rows for cicd stood.

## D-033. A closed slice keeps an answer key and a report names its exact model, so the archive benchmarks models

- **Date.** 2026-10-01
- **Status.** Proposed. Accepted when the owner merges the pull request that carries it. Kit v1.9.0, reaching every
  repo with the next Distribute.
- **Tier / scope:** Standard · kit `docs/agent/CODE_REVIEW_PROCESS.md` sections 3, 8, 9 and 14, a new
  `review-answer-key.template.md`, the report, adjudication and README templates, the kit README and registry ·
  cicd's own copies

**Context.** The owner, 2026-10-01, of the prompts and reports every review keeps, "I think this would be a good idea
to keep them so that I can continue to have more data to test open source models on to see what they can do and how we
can benchmark them against other industry scale models", and of the reports that come back, "so we can compare the
reports of the open source models to the industry models, like claude and chatgpt to see what models working
individually and combined can do". A pilot the same day ran four open weights models on the owner's machine, Codex CLI
on Ollama in a container that reads the code and reaches nothing else, each with the auth UI's S1 step 2 brief at its
pin, and scored every report against what the S1 adjudication log established. The archive held everything the scoring
needed, but not in a form it could use. Turning the log and git into an answer key took a helper session about 250k
tokens and 13 minutes, and several rows could only be inferred, since the log says what was fixed and not always
whether the defect was in the tree an earlier reviewer read. The report template asked only for "model and effort", and
one local model wrote "about two hours" for a run of 19 minutes.

**Decision.**

- **An answer key for every slice, written when it closes.** `<PFX>_REVIEW_<slice>_ANSWER_KEY.md` beside the
  adjudication log, from the new template, written once at step 6 from the finished log and git, before the slice's
  pull request opens. It names the commit every reader read, the step 2 brief as it stood at the pin, and one row per
  finding of every source with its id, source, the reviewer's model, severity, Blocks, verdict, where it was at the
  pin, the commit that brought it in and the one that fixed it, whether it was in the tree the step 2 reviewers read,
  how that was decided and what a reviewer needed to find it. Then the declined findings with their measurements and
  the counts. It adds no verdict of its own, each row cites its log row, and a corrected log row is corrected in the key
  in the same commit. At spot scale it is `<PFX>_REVIEW_ANSWER_KEY.md`.
- **A report names its reviewer exactly.** The header gives the model and version as the tool names it, the tool it ran
  in, the effort, the tokens when the tool reports them, and the start and end times as the clock showed them.
- **Same commit comparisons, and benchmark runs kept apart.** The archive is also a benchmark, section 3. Only reports
  of the same commit compare fairly, step 2, step 5 and each second read read one pin, and each Sol round reads a later
  commit. Runs of other models made later never go into `docs/reviews/`, which stays the record of what the review did
  and which a later reviewer reads. A benchmark keeps its runs and scores elsewhere and copies the keys it needs.
- **The Sol files stay word for word.** Each dispatch already names the branch and commit it was written against, and
  the answer key gathers every round's commit beside the other readers'.

**Alternatives considered.**

- Building a key on demand from the log, as the pilot did. Rejected, it is costly, and the facts it needs fade, while
  the orchestrator at close knows which defect was in which tree.
- A machine readable key in JSON. Rejected for now, the kit is Markdown alone (D-001), a Markdown table parses, and a
  person reads it.
- Writing the local runs into the review folders beside the reviews. Rejected, the folder is the record of the review,
  and a later reviewer would read a weaker model's report as context.
- Making an open weights model a reviewer family now. Not decided here. Rule 15's two families stand, and the pilot
  measures whether any local model could be one.

**Trade-offs.** One more file per slice and some work at its close, most of it a copy of rows the log already holds. Two
more header lines a reviewer fills. A key can only be as exact as its log, so a log that does not say which tree held a
defect leaves that row unsure.

**Consequences.** Kit v1.9.0 and cicd's own copies in step, and Distribute opens a sync pull request in every repo. The
SDK review writes its first answer key when S1 closes. Closed reviews from before this decision have no key, and one
is built for a past slice only when a benchmark needs it, as the pilot built the auth UI's S1.

## D-034. A supporting session builds what a review finds outside the reviewed repo

- **Date.** 2026-10-01
- **Status.** Proposed. Accepted when the owner merges the pull request that carries it. Kit v1.10.0, reaching every
  repo with the next Distribute, together with v1.8.0 and v1.9.0.
- **Tier / scope:** Standard · kit `docs/agent/CODE_REVIEW_PROCESS.md` sections 2, 4 and 12 and its status line, kit
  `docs/agent/AGENT_ROLES.md` sections 1 and 4 · cicd's own copies

**Context.** Since v1.8.0 a finding that shows a defect in something cicd owns is fixed in cicd by a pull request from
a worktree as it is found, and the process did not say who builds it. In the SDK review's S1 the orchestrator built
those fixes itself, beside adjudicating the reviews, and the next one was large, running a lane's tests in a job that
names no secret at all (SDK finding S1-48, D-032's next step). The owner, 2026-10-01, of how the review runs from here,
"going forward where the code review has 1 main Fable orchestrator and a supporting OPUS session on the side that you
can offload ideas to and other things you find", and to the orchestrator, "I want you to focus on the code review, so I
want you to hand this task off to the other agent".

**Decision.**

- **A second role, the supporting session.** A long running session the owner starts beside the orchestrator, in the
  same folder, today Opus beside a Fable orchestrator. It builds what a review finds outside the reviewed repo, in
  cicd, this kit, the reviewer tooling or another repo, each fix one pull request from a worktree of the repo that owns
  it, and reports the pull request back.
- **A handoff carries four things.** The finding, the evidence that proves it, what is already done, and what would
  prove the fix.
- **Between pins, and read before it is relied on.** A fix takes effect between pins and never under an open one, so
  every reviewer of a pin reads one tree. The orchestrator reads what the supporting session built before the reviewed
  repo relies on it, and the slice's log names that pull request where a register row would have stood.
- **Two folders, two owners.** The supporting session never reviews, and never edits, commits, checks out or stashes
  anything in the reviewed repo's folder. The orchestrator keeps that folder for the whole review.
- **Optional.** A review without a supporting session runs as before, the orchestrator does that work itself, between
  pins the same way.

**Alternatives considered.**

- The orchestrator fixes everything itself, as in S1. Rejected by the owner's word, it pulls the orchestrator off the
  review for work that does not need the review's context, and a large fix delays the next pin.
- Deferring what cicd owns to a register row until the review closes. Rejected already by D-032, a defect in a shared
  lane or in the review's own tooling reaches every repo in the meantime.
- Handing each fix to a fresh session. Rejected, a fix outside the repo often needs the history of earlier fixes, and a
  long running session keeps it.

**Trade-offs.** Two sessions to run and to keep apart, and a handoff to write for each fix. The supporting session's
work is one more thing the orchestrator reads before relying on it, which is the point.

**Consequences.** Kit v1.10.0 and cicd's own copies in step, and Distribute opens a sync pull request in every repo,
carrying v1.8.0, v1.9.0 and v1.10.0 together. The SDK review runs this way from S1 on, its first handoff being the lanes
that run a caller's code in a job that names no secret.

## D-035. Code a lane does not trust runs in a job that names no secret, its private packages fetched by a job that runs only git

- **Date.** 2026-10-02
- **Status.** Proposed. Accepted when the owner merges the pull request that carries it. The reusable lanes take effect
  at the merge, every repo calls them at `main`. No kit change, nothing to Distribute.
- **Tier / scope:** Standard · the seven reusable lanes `ci-python-tests.yml`, `-integration`, `-system`, `-mutation`,
  `-security` (its pip-audit job), `-lint` and `-typecheck` · a new `fetch-private-packages.yml` ·
  `scripts/fetch_private_packages.py`, `scripts/render_fetch_job.py` and `scripts/fetch_private_job.template.yml` · the
  proof in `ci.yml` and `tests/fixtures/secretless/` · the workflow reference and the control plane security doc

**Context.** D-032 made the package token one step's, so no later step of a lane reads it from a git config file or
from another process's environment. It recorded what that does not close. A hosted runner grants passwordless `sudo`,
and a process that becomes root reads the memory of `Runner.Worker`, where every secret the job names sits, the
technique of the tj-actions/changed-files compromise of March 2025. Each lane named `KDF_APP_ID` and
`KDF_APP_PRIVATE_KEY` in its mint step, in the same job as the caller's install and tests, and that private key mints
tokens for every repo the App is installed on. A dependency of any backend that became root in CI could have taken
the App itself. The kdf-sdk review's S1-48 measured the environment half of this on Linux. The owner, 2026-10-01, "I
agree that this is an important enhancement and should be implemented", and of how it proves itself, "because then it
can be used as you are doing the code review to see if it works properly". The review session handed the task over with
its finding and its evidence, the arrangement of D-034.

**Decision.**

- **Two jobs when a caller asks for package access.** The lane's fetch job is the only job that names a secret. It
  checks out the caller's tree with no credential kept and runs nothing of it, reads its requirement files as text,
  mints the App's token for exactly the repos it clones, clones each pinned ref into a bare mirror, no working tree, so
  no hook and no filter runs, and uploads the mirrors as one artifact kept for a day. The install job names no secret
  at all. It downloads the mirrors and hands git one rewrite per repo, from `https://github.com/Needless2Say/<repo>.git`
  to the mirror on disk, through `GIT_CONFIG_COUNT`, `KEY_n` and `VALUE_n` in the job's environment, then runs the
  caller's install and test commands as before, and pip's direct git URLs clone from disk.
- **The install job keeps its id and its name.** A ruleset requires a called job as `<caller job> / <called job name>`,
  so no repo's required check changes. The fetch job adds a check no ruleset requires.
- **Fail closed.** A skipped required job counts as passing, so the install job runs on `always()`, a cancelled run
  included, and its first step ends it failed when the run was cancelled or, with `needs_sdk_auth`, when the fetch did
  not succeed. GitHub reads `cancelled()` only in an `if`, so the check is that step's `if` and its run says why. On
  `!cancelled()` a cancel while the fetch ran would have skipped the job and passed the check, the kdf-sdk's S1-49
  again. A Dependabot run, which gets no secrets, fails as it does today.
- **A caller that does not ask keeps one job.** The fetch job and the install job's three mirror steps run only with
  `needs_sdk_auth`. The kdf-sdk calls its lanes without it.
- **What the fetch reads.** A pin is `git+https://github.com/Needless2Say/<repo>.git@<ref>`, a `#subdirectory=` tail is
  part of the URL, a comment is a `#` at a line's start or after whitespace, a backslash continues a line, and `-r`,
  `-c`, `--requirement` and `--constraint` are followed within the same tree and refused when they name a URL or leave
  it, and a file of the tree that is a link is followed only to a place inside the tree. Any other reference to the
  owner's repos that pip could install fails the plan early, a git+, git@ or ssh:// URL, an archive or wheel link, or a
  pip option line, while a plain https link to a repo's page, as a pyproject's `[project.urls]` holds, passes. The rule
  is not the fence, a pin it missed fails closed in the install job, which has no mirror and no token for it. A ref out
  of a requirement file is a tag or a full commit id. A branch is allowed only for a repo the caller
  lists by name in `extra_repos`, and the manifest records the commit it resolved to. `scan_files` reads requirement
  files inside such a mirror with `git show`, and `token_repositories` is the narrower fence per call, the kdf-sdk
  canary mints for one backend and the three packages.
- **An allowlist, and the public caller rule.** The fetch mirrors only the owner's repos a lane can need, the three
  packages and the three backends, all private, and this public repo as the stand in for the proof. A public calling
  repo may mirror only a public one. Its run artifacts are readable by anyone, so a public repo has no private package
  to fetch.
- **The fetch job is written into each lane, not called.** A reusable workflow that calls another by a `./` path is
  documented to take it "from the same commit as the caller workflow", and the documentation does not say which
  repository that is when the lane itself was called from another repo. Rather than guess, the fetch job is one
  template, `scripts/fetch_private_job.template.yml`, written into the seven lanes and into `fetch-private-packages.yml`
  by `scripts/render_fetch_job.py` with `fetch_private_packages.py` inline, so the code the job runs is the workflow's
  own text at its own commit. A test fails when a copy differs. `fetch-private-packages.yml` is for a caller that runs
  its own install job, the kdf-sdk canary, which calls it from its own top level workflow.
- **The style lane stays one job.** It installs only the pinned kdf-fmt and runs it over files, no code of the caller
  executes, and this public repo's own CI calls it, where a mirror artifact would publish the formatter. This rests on
  kdf-fmt never importing or executing what it formats. A kdf-fmt that one day did would have to split too.
  **Corrected by D-038.** The claim that no code of the caller executes was false three ways. `python -m` put the
  checkout first on the import path, so a `pip.py` in a pull request ran in pip's place in the step that held the
  token and a `kdf_fmt/` in the formatter's place in the job that named the App's key, and `check_command` is the
  caller's own text. The style lane splits too, and this repo runs its own one job check.
- **Proved on the pull request.** No session dispatches a workflow, so this repo's own CI calls the unit test lane by a
  local reference with package access on. Its fetch job mirrors this repo, a tag the fixture pins and the pull
  request's branch. The install job installs a probe package from the mirror through the rewrite, reads the tag back
  the same way, and then, as root, hunts every process's environment and the memory of `Runner.Worker` and
  `Runner.Listener` for the header of a private key and for any token whose sha256 equals the one the fetch job
  published. It must find none, and it must find the job's own `GITHUB_TOKEN` there, or it read the wrong memory. A
  positive control job names the App's secrets, mints a token and runs the same hunt, which must find both. Only
  counts and booleans are printed. Measured on the pull request that carries this decision, the install job's hunt read
  579 MB of two runner processes and found 13 token shaped runs, its own `GITHUB_TOKEN` among them, no private key
  header and no copy of the fetch job's token, in memory or in any of 38 environments. The control read 630 MB and
  found the key's header 91 times and its own token 3 times in memory. The first run found no token in either job, its
  pattern assumed `ghs_` and 36 letters and digits, and the App's installation token minted that day was 390
  characters, so the hunt now matches any run of token characters after a known prefix by the sha256 of its prefixes.

**Alternatives considered.**

- A composite action or a nested reusable workflow for the fetch. Not taken, the commit a nested `./` reference resolves
  to is not documented for a lane called from another repo, and an action pinned at `@main` would let a pull request
  here test main's fetch instead of its own.
- Shallow mirrors. Rejected, pip clones with `--filter=blob:none`, and a filtered clone of a shallow repository failed,
  measured with git on Windows on 2026-10-02, so each pinned ref keeps its history. A plain clone of a shallow mirror
  and a filtered clone of a full one both worked.
- A cache in place of an artifact. Rejected, a cache of a public repo can be restored by a fork's run.
- Encrypting the artifact with a key passed between the jobs. Rejected, a job output is not a secret, and the key would
  sit beside the ciphertext for anyone who reads the run.

**Trade-offs.** What it closes. The App's private key and the package token are no longer in the memory or the
environment of any job that runs a caller's code, so a dependency that becomes root during an install or a test reads
neither. What it does not close. The `GITHUB_TOKEN` is in every job at `contents: read`, though no checkout of these
lanes keeps it in the tree's git config, no caller's install or test command reaches its own remote (measured over the
eight callers on 2026-10-02). The fetch job still holds the key while it runs git and its own script, and a compromise
of git, the runner image or a pinned action there would reach it. **The price.** The full history of each private repo
the fetch clones, up to every ref it needs, sits in the calling repo's run artifacts for a day, readable by everyone who
can read that repo. The mirrors are not shallow, because pip clones with a filter and a filtered clone of a shallow
mirror fails. For a backend that is the history of the packages it pins, for the kdf-sdk canary it is the three
backends' whole histories in the SDK's artifacts. Every one of these repos is private, and the owner is its only reader.
**The cost.** One more job per lane per pull request, a minute or two, and seven lanes of about seven hundred lines
each, most of them the inline script.

**Consequences.** The first pull request of any Python repo that sets `needs_sdk_auth` after the merge runs the two
jobs, and a red fetch there is this change. Follow ups. `cd-python-vercel.yml` still writes the package token into its
deploy job's git config, a job that holds the deploy secrets either way. `.github/actions/run-e2e` still installs
`cryptography` by a bare name. An extra repo that only a plain clone reads, as the canary reads a backend, could be
fetched at depth one by an opt in, a plain clone of a shallow mirror works, which would shrink the price. The kdf-sdk
wires its canary to `fetch-private-packages.yml` between pins and reports its first run.

## D-036. Sol bundles go to the workspace's temp folder

- **Date.** 2026-10-02
- **Status.** Proposed. Accepted when the owner merges the pull request that carries it. Kit v1.11.0, reaching every
  repo with the next Distribute.
- **Tier / scope:** Standard · kit `docs/agent/CODE_REVIEW_PROCESS.md` section 9 and its status line · cicd's own copy

**Context.** A Sol page carries, for each dispatch, a command per shell that joins the dispatch's files into one bundle
the owner attaches to the Sol chat. The pages wrote it into the system's temp folder, `/tmp` in Git Bash and `$env:TEMP`
in PowerShell, which on Windows is `C:\Users\<user>\AppData\Local\Temp`, a folder the owner could not find and that only
fills up. The owner, 2026-10-02, "can it be put somewhere in a directory in this directory I am in like
/d/KriegerDataForge/temp/ so I can copy paste from there ... so I can also delete those files after they are done so
they do not take up space", and "Its better to have a temp directory here where I can manage them and delete them when
needed since these code combinated files are only temporary and not needed for long term".

**Decision.** A page's bundle commands run from the workspace folder that holds the clones and write into its `temp/`
folder, made when missing, one lower case file per dispatch, `kdf-<pfx>-<slice>-dispatch-<n>.txt` as every page so far
has named it, and print the full path they wrote. A bundle is made again just before its dispatch is attached, so it
matches the commit the page names, and the page is built at the commit its prompts should name, saying so when later
commits carry only the review's own records. Bundles are scratch, outside every repo, never committed, and the owner
deletes them after the round.

**Alternatives considered.**

- A gitignored folder inside the repo under review. Rejected, the review launcher counts every new file in a folder it
  reviews, and a repo's own tools, the formatter, the linters and a recursive search, would read the bundles.
- The system's temp folder, as before. Rejected, the owner can neither find nor manage it.

**Trade-offs.** The workspace's `temp/` folder sits in no repo, so nothing cleans it, and the owner deletes the files by
hand, which is what the owner asked for. A page built before this rule writes to the system's temp folder until its
builder is changed.

**Consequences.** Kit v1.11.0 and cicd's own copy in step. The kdf-sdk review's orchestrator was told directly and moves
its page's bundle lines now, so the Distribute can wait for a later kit change.

## D-037. Every slice closes with a measured retrospective, and the owner decides each change it proposes

- **Date.** 2026-10-02
- **Status.** Proposed. Accepted when the owner merges the pull request that carries it. Kit v1.12.0, reaching every
  repo with the next Distribute.
- **Tier / scope:** Standard · kit `docs/agent/CODE_REVIEW_PROCESS.md` sections 2, 3, 4 and 14 and its status line · the
  new `review-retro` template · the readme and adjudication templates · `tools/claude-code/kdf-retro.js` · cicd's own
  copies

**Context.** Every change to the process so far came from friction, a step that went wrong, a handoff, the owner's yes
and a kit pull request, D-031 to D-036 among them. Nothing stepped back after a slice to measure how it went. The owner,
2026-10-02, asked that each round be evaluated for what went well and what can be improved, "to make the code review
process more accurate, faster, more token efficient, and overall better structured", "something similar to model
training, whether it be reinforcement learning or something to continuously improve upon and make the code-review
process as good as it can be". Then the owner answered four questions. A retrospective at each slice's close, plus
Phase B and the review's end. Its numbers produced by a script and not by the orchestrator. Proposals approved as a
short list in the chat. And accuracy first, then the owner's time, then tokens.

**Decision.** Once a slice's answer key is written, the orchestrator runs `tools/claude-code/kdf-retro.js` on the slice
folder and writes `<PFX>_REVIEW_<slice>_RETRO.md` from the new template, the tool's tables pasted as printed and then
its analysis, why each escape was missed, the friction with its evidence, how earlier changes did, and its proposals.
The tool reads the answer key's findings table by the template's exact columns, and refuses a key with others, every
report's Time spent, Reviewer and Usage lines, and the Sol rounds, and prints per source the findings raised, agreed and
declined, the escapes, which are agreed findings in the tree the step 2 reviewers read that a later step found, each
report's minutes and tokens, and every Sol dispatch without its archived answer. The supporting session, or the
orchestrator when the review has none, turns the proposals into a short list in the chat, problem, change, the number
it should move and the cost, and the owner says yes or no to each. Nothing changes without the owner's yes. An approved
change lands between slices, a larger one at the review's end, and is recorded in the improvement ledger of the bench
repo, and later retrospectives say whether it moved its number, a change that did not being reverted. Accuracy first,
the escape rate, then the owner's time and waiting, then tokens, and never tokens at the cost of catches. A one off is
noted and acted on only when its cost is clear, and a few changes land at a time so their effects can be told apart.

**Alternatives considered.**

- The orchestrator counts the numbers itself. Rejected by the owner's answer, it spends tokens on arithmetic and two
  retrospectives would count in two ways.
- A retrospective after every step. Rejected, it costs more tokens and more of the owner's time than it saves.
- One retrospective when the whole review closes. Rejected, the later slices would repeat the first one's mistakes.
- Changes made without the owner's yes, as the orchestrator sees fit. Rejected, the owner decides every change to the
  process.

**Trade-offs.** The tool reads only answer keys written from the v1.9.0 template on, so a review closed before that has
no numbers until its key is written again. Minutes and tokens are as good as the reports' headers, and a report that
does not state them prints unknown. The ledger lives in a private repo of its own, outside the reviewed repos.

**Consequences.** Kit v1.12.0 and cicd's own copies in step, the template registered for the sync, `kdf-retro.js` beside
`kdf-brief.js` and not synced, like the rest of the tooling. The kdf-sdk review's S1 closes with the first
retrospective.

## D-038. The style lane runs no caller code where a secret is, and a release tags the commit it read

- **Date.** 2026-10-02
- **Status.** Proposed. Accepted when the owner merges the pull request that carries it. Supersedes D-035's paragraph on
  the style lane.
- **Tier / scope:** Standard · `ci-python-kdf-fmt.yml` · the new `ci-kdf-fmt-self.yml` and this repo's `ci.yml` ·
  `create-github-release.yml` · `scripts/fetch_private_job.template.yml` and `scripts/render_fetch_job.py` · the tests

**Context.** The kdf-sdk review's Sol dispatch 3 (SDK-S1-D3-R1-1) found D-035 wrong about the style lane. D-035 left it
one job because no code of the caller executed there. It did, three ways. The install step ran `python -m pip` in the
caller's checkout with the token in its environment, and `python -m` puts the working directory first on the import
path, so a `pip.py` at the root of a pull request ran in pip's place in the one step that held the token. The check step
ran `python -m kdf_fmt.cli`, so a `kdf_fmt/` folder in the tree ran in the formatter's place, in a job that named
`KDF_APP_PRIVATE_KEY`, which a process that becomes root reads from the runner's memory. And `check_command` is the
caller's own text. The review session measured both shadowings on Python 3.14.2, and `python -I` stopped both. The mint
named no `repositories` either, so its token read every repo the App is installed on. Someone who can open a same repo
pull request can already reach the secrets another way, so the review session rated it low, but the record was false.
Probing the same dispatch found S1-54. `create-github-release.yml` ran `gh release create` with no `--target`, so GitHub
put the tag on the default branch's tip when the command ran, and a second merge landing between the push and that line
would take the first one's tag. Every backend pins the SDK's tag, and the tag naming the gated commit is the point of
the SDK's D-020.

**Decision.** The owner chose, 2026-10-02, to split the style lane like the other seven, "For every private repo, the
style lane becomes two jobs like the other seven ... cicd, the one public repo, keeps its own one-job style check with
Python's isolated mode and a token limited to kdf-fmt". The lane takes the template's fetch job, which here always
runs, reads no requirement file, mirrors only `kriegerdataforge-fmt` at the caller's `kdf_fmt_ref` and mints for that
repo alone. Its check job keeps the id `style` and the name `Style (kdf-fmt)`, so every ruleset's required check is
unchanged, names no secret, fails closed on the template's guard, checks out with no credential kept, and installs the
formatter from its mirror with `python -I -m pip`. The default `check_command` is `python -I -m kdf_fmt.cli check
--no-cache`. Isolated mode covers the install step and that default only. A caller's own command is its own text, and
in a job that names no secret a shadowed `kdf_fmt` can only fake a style pass, which a pull request could do anyway by
changing `check_command`, so the lane's safety rests on the check job naming no secret. The template's plan inputs and
its guard's condition became fields filled per copy, and the seven lanes and the standalone render exactly as before.
The fetch refuses a public caller's mirror of a private repo, so this public repo calls its own one job check,
`ci-kdf-fmt-self.yml`, whose job keeps the name `Style (kdf-fmt)`. It mints for `kriegerdataforge-fmt` alone, installs
and runs in isolated mode, and its command, baseline gated, is fixed in the file and is not an input. A release names
its commit, `create-github-release.yml` records the commit it read `VERSION` from, the triggering commit, and passes it
to `gh release create` as `--target`.

**Alternatives considered.**

- Isolated mode and a narrowed token alone, the lane one job. Offered to the owner and not chosen, the caller's
  `check_command` would still run where the App's key sat.
- Mirroring the formatter for this public repo too. Rejected, a public repo's run artifacts are readable by anyone and
  would publish the private formatter.
- `--target "$GITHUB_SHA"`. The same commit on the push to `main` that triggers a release. The checkout's commit is
  named so the tag holds the tree `VERSION` was read from whatever the trigger.

**Trade-offs.** One more job per call of the style lane, as for the other seven. This repo's own style check still
holds the token in one job, resting on its pull requests coming from the owner alone, Dependabot's and a fork's runs
getting no secret, the token reaching only `kriegerdataforge-fmt`, and its command being fixed and isolated. This
repo's CI cannot run the shared lane's check job, since it cannot mirror the formatter, so its fetch job is the template
the secretless proof runs on every pull request and its check job is held to the template by the tests.

**Consequences.** Every private repo's style check runs on two jobs from its next CI run, and no caller changes. The
kdf-sdk's own `check_command`, with its baseline, keeps working and reaches no secret. A release's tag can no longer
name another commit than the one whose `VERSION` it carries. D-035's paragraph on the style lane now points here.

---

## D-039. The first retrospective's changes, standing questions, counted runs and Codex in the cloud on trial

- **Date.** 2026-10-03
- **Status.** Proposed. Accepted when the owner merges the pull request that carries it. Kit v1.13.0, reaching every
  repo with the next Distribute. Applies D-037 for the first time.
- **Tier / scope:** Standard · kit `docs/agent/CODE_REVIEW_PROCESS.md` sections 4, 6, 7, 8, 11 and 14 and its status
  line · the brief and report templates · `tools/claude-code/kdf-review.sh` and `kdf-retro.js` · the new
  `tools/codex-cloud/kdf-codex-setup.sh` · `create-github-release.yml` · cicd's own copies · the tests

**Context.** The kdf-sdk's S1 closed on 2026-10-03 with the first retrospective D-037 asked for. Its answer key held
60 agreed findings in the tree the step 2 reviewers read, and 43 of them, 72 percent, were found by a later step. 26 of
the 43 fell into three classes no brief had asked about. Twelve were a tool acting on a path the caller names, the
mutation runner's `--worktree` among them, eight were the environment a child program is handed, one more reader each
time, make, pydantic-settings, git, pip, uv, Python, and six were two parsers of one string, the database fence's
`urlsplit` against the driver's `make_url`. A Blocks fix found in the last Sol round earned a narrow second read of its
own, one more turn of Codex at the owner's machine, and S1 already read one such fix in its final reviews, which found
four more defects in it. Six Codex turns waited for the owner at the machine, hours to a day each. Seven of the twelve
reports printed unknown minutes and every one printed unknown tokens, since reviewers wrote their time in words, as an
estimate or inside another line, and no reviewer could count its own tokens. The step 2 Claude read took about three
hours against the launcher's two hour default. The orchestrator's handoff also carried a tidy of D-038, the release
workflow's tag check still pasted the tag into its script.

**Decision.** The owner approved all six proposals on 2026-10-03, a yes to each in the chat, and the supporting session
built them.

- **Three standing look for questions.** Every brief's look for list ends with three bullets kept word for word from
  the template, the paths a tool acts on, the environment a child is handed with its readers named for Python and for
  Next.js and Node, and two parsers of one string. The scope table gains a Destroys column that marks every tool which
  deletes, resets, cleans or overwrites, and where it is told to act. `kdf-brief.js check` reads the first two columns
  as before. The report template asks a probe of such a check to run the consumer's own parser on the check's inputs.
- **The last Sol round's Blocks fixes are read by the final reviews.** The final brief names each first in its look for
  list, and it earns no narrow second read of its own. A Blocks finding of the final reviews still does.
- **Runs are counted, not reported.** The launcher runs `claude -p` with `--output-format stream-json --verbose`, its
  stdin closed, so the run's log holds each event as it happens, one JSON object a line, and a detached run is watched
  by its log. After a clean run it writes `<report stem>.usage.json` beside the report from the stream's last result
  event, Claude Code's own count, the models, the start and end it saw, the duration, the turns, the tokens summed over
  every model, fresh and cached, and the cost. The report is never touched and the result's text is not copied. A
  failed run names claude's exit, the reason its result event gives, or that the log holds none when the run was
  stopped or crashed first, and the log's last lines. `kdf-retro.js` reads a report's minutes and tokens from that file
  first, and marks the row counted by the launcher. For the reports it did not start it now clocks two times joined by
  "to" or a dash, a bare end after a dated start, and a label closed by a colon or shared with another, "Time/reviewer".
  On S1's own folder that turns five readable times of twelve into ten. Every collect warns when a report the launcher
  did not start lacks its Usage line or a Time spent line with two clock times, and the report template asks for
  `From HH:MM to HH:MM` on a line of its own.
- **Four hours.** The launcher's default `--timeout` is 14400 seconds, and a run past it says it was stopped.
- **Codex in the cloud, on trial for the kdf-sdk's S2 alone.** The owner makes a fine grained token for that one
  environment, Contents read only on the private repos the reviewed repo installs, 30 days, never `GH_PACKAGES_PAT`,
  stores it as the environment's secret `KDF_CODEX_PACKAGES_TOKEN` and pastes `tools/codex-cloud/kdf-codex-setup.sh` as
  its setup script. OpenAI's documentation says an environment's secrets reach the setup script alone and are removed
  before the agent phase, and that the agent has no internet by default. The script runs the repo's own `make setup`
  with the token in the environment of that command alone, git reading no global or system config, pip keeping no
  cache, and its output masked. It then searches the home folder, the repo with its environment, the temp folder and
  pip's cache for the token's value, in every file's text and every path's name, the value read from a pipe and never
  from a command line, and fails the setup, naming only the paths, when it finds it.
- **The tidy.** The release workflow's tag check reads the tag from its environment, as the release step does, and
  matches it as a fixed string.

**Alternatives considered.**

- The report template's lines made exact and checked, with no count by the launcher. Taken too, for Codex and any
  reviewer the launcher does not start, but a model cannot count its own tokens, so for Claude the launcher counts.
- `--output-format json`, one result object when the run ends. Built first and replaced before the merge at the
  orchestrator's reading, since S1's long reads were watched by their log and a single object at the end shows nothing
  while a read runs. The stream's last event is the same result.
- Codex in the cloud as the default road at once. Not taken, the owner chose one slice on trial, and the product page
  now calls the environments "Codex Cloud (Legacy)".
- The setup script writing the token into git's config or a requirements file. Rejected, the rehearsal below shows an
  image's credential helper writes a token git saw in a URL to `~/.git-credentials` when git reads the global config.

**Trade-offs.** The log is JSON a line rather than plain text, and holds every event of the run, what each tool read
among them, in the launcher's work folder in the system temp folder as before. The usage file is one more file per
Claude report for the orchestrator to commit. A Codex review in the cloud cannot run the consumer check, which needs
the token after setup, and the token lives in OpenAI's store for 30 days. Three standing bullets lengthen every brief
by six lines.

**Proof.** The setup script was rehearsed in `python:3.14.7-slim` with a fake token and a local git server standing in
for GitHub, the reviewed repo's Makefile handing the token to git as the kdf-sdk's does. A token planted in the home
folder failed the setup with exit 3 and its path alone printed. With the script's git guard removed and a credential
helper set up as an image might, git stored the token in `~/.git-credentials` and the self check failed the setup. The
shipped script then installed the private stand in, its `direct_url.json` recorded the URL without the token, and the
value was found nowhere on the container's disk. The tests repeat each case with a stub install, and the launcher's
and the retrospective tool's tests run on a stub claude that streams a real run's shape, measured with
`claude -p --output-format stream-json --verbose` on 2026-10-03, an init event, the assistant's events, a rate limit
event and the result last.

**Consequences.** S2's briefs carry the three questions and its final reviews read the last round's fixes, its Claude
reports arrive with their counts, and S2's retrospective reads the trial and the escape rate against S1's 72 percent.
The owner deletes the trial's token when the trial ends.

## D-040. One mutation engine for every repo that runs Python mutants, vendored by the scripts sync

- **Date.** 2026-10-03
- **Status.** Proposed. Accepted when the owner merges the pull request that carries it. Reopens the alternative
  D-027 rejected, the runner handed out by the scripts sync. Follows D-039, cicd #255, `VERSION` 0.2.120.
- **Tier / scope:** Standard · `scripts/common/mutation_runner.py` · `scripts/scripts_registry.json` and
  `scripts/distribute_scripts.py`, a file entry may name its repos · `ci-python-mutation.yml` · the tests · then one
  pull request each in the hub, fitness-app-backend and tiffanys-space-backend, and the SDK's after its pull request 125

**Context.** Four repos held a Python mutation runner of their own, the hub's of 672 lines, one file of 645 in both
tenant backends, and the SDK's, 1,053 lines after its review's slice S1. That slice found that `--worktree .` forced a
checkout and ran `git clean -fdx` in the developer's own checkout, which deleted uncommitted work, the credentials file
and the environment and reported a green run (SDK-S1-D3-R1-2). Its final reads and four narrow reads then found git
acting where the runner had not looked, through the caller's `GIT_` variables, a repository that appeared after the
judgement, a link at the mutated path, and a link swapped in between a judgement and the act. The SDK's runner at
`50150fe` closes each, and the other three still carry the two bare commands, since a fix made to one copy reaches no
other. The owner, 2026-10-02, "All workflows related to functionality like this should be in the common cicd repo so
that all tenant repos benefit from 1 reusable workflow engine ... and each repo can have its own type of tests", and on
2026-10-03, "Build now, before S2".

**Decision.**

- **One engine, here.** `scripts/common/mutation_runner.py` is the SDK's runner at `50150fe` with every rule carried
  whole, the `GIT_` free environment, the two judgements, the folders it owns, the walk for a link, each act asked of
  git first, the restore, the results file's shape, the path resolved once and the prune hint. What changed is what a
  repo alone knows. The repo is two folders up from either seat, and a repo's unit settings come from its tables
  package, whose `mutation_tests/__init__.py` may define `unit_settings(environment)`, returning names mapped to
  strings, the SDK's two values, a backend's own, the hub's with the throwaway keypair it makes when the process holds
  none. The engine stays stdlib only. The worktree's mark `kdf-mutation` in git's folder, the default worktree
  `<temp>/kdf-mutation/<repo>/<lane>` and the results file `mutation-<lane>.json` beside it are the SDK's, so a
  worktree the SDK's runner made is still recognised and the lane uploads from the same place.
- **Vendored like the version scripts.** The scripts sync hands it byte for byte to
  `scripts/kdf_scripts/mutation_runner.py`, the folder every repo's style and lint configs already exclude. A `files[]`
  entry of the registry may now name its `repos`, and this one names the four, so the other thirteen repos are never
  handed it, which answers D-027's reason. `SCRIPTS_VERSION` 1.5.0.
- **The reusable lane runs it.** `ci-python-mutation.yml` runs the vendored engine, and a caller that still holds
  `mutation_tests/run.py` has not moved and runs its own, so no merge order breaks a caller. The pull request that
  moves a repo deletes its runner. The fallback goes once the SDK, the last to move, has.
- **The tests split by owner.** The engine's tests are here, the SDK's two files pointed at a repository made for each
  case, with the unit settings and whole runs in such a repository. A repo keeps the tests of its tables, the lanes its
  gate and Makefile name, every node id and every anchor, against the vendored engine, and the hub keeps its keypair's.
- **The engine's own mutants are here too.** Every fix is pinned twice, a test and a mutant, and the engine's mutants
  were the SDK's 36 of its runner and the hub's RE-M-84. They are `mutation_tests/engine.py` here, EN-1 to EN-37, with
  EN-38 to EN-44 for what this decision added, and the engine runs that table on itself in the CI job `Mutation
  (engine)`. A repo's switch drops its mutants of its old runner, the SDK's 36 and the hub's one.

**Alternatives considered.**

- A package installed from this repo by a git URL. Rejected, every repo would pin and bump one more dependency, and
  the scripts sync already owns this shape.
- The lane running this repo's copy instead of the caller's. Rejected, a developer's `make test-mutation` and the lane
  would run two engines between a merge here and the sync.
- The engine split in two modules under the 1,000 line limit. Rejected, a repo vendors one file and the worktree's
  rules read in one place, so `kdf-fmt.toml` turns KDF-605 off for this file alone.

**Trade-offs.** A fix here reaches a repo when the owner runs the scripts sync and merges its pull request, as the
version scripts do. The hub's default worktree moves from `<temp>/kdf-mutation/<lane>` to
`<temp>/kdf-mutation/kriegerdataforge/<lane>`. A worktree an older runner made carries no mark, so the engine refuses
it and names `git worktree remove --force`, once per developer machine.

**Consequences.** Merge order, D-039's pull request, this one, then each repo's switch in any order, then the scripts
sync, whose pull request carries nothing for a repo that already holds the engine. The SDK's switch follows its pull
request 125 and is the same change as the others. `Mutation (engine)` is a required check only once the owner adds it
to the ruleset. Pinned in `mutation_tests/engine.py`, `scripts/tests/test_mutation_runner.py`,
`scripts/tests/test_mutation_runner_worktree.py`, `scripts/tests/test_distribute_scripts.py`,
`scripts/tests/test_workflow_contracts.py` and `scripts/tests/test_consumer_test_tooling.py`.

---

## D-041. A lane's default requirement files include the `.in` files a repo compiles from

- **Date.** 2026-10-03
- **Status.** Proposed. Accepted when the owner merges the pull request that carries it. Corrects D-035's default list.
- **Tier / scope:** Quick · the `requirement_files` default of the seven split lanes and of
  `fetch-private-packages.yml` · `scripts/fetch_private_job.template.yml` · `docs/reference/WORKFLOWS.md` · the tests

**Context.** D-035's fetch job mirrors only the private repos pinned in the files `requirement_files` names, and its
default named `requirements.txt requirements-dev.txt requirements-test.txt pyproject.toml`. A repo that locks with uv
or pip-compile keeps its private pins in the `.in` files too, and the backends keep the kdf-fmt pin in
`requirements-dev.in` alone. A lane that installs `requirements-dev.in` then found kriegerdataforge-fmt missing from
the mirrors and failed at install. The shared mutation engine's builder (D-040) met it on the engine's pull requests,
in tiffanys-space-backend's four CI lanes and the hub's integration lane, and those repos' pull requests now pass their
files by name. Both backends' PROD Gate system and mutation lanes would have failed the same way at their next release,
their last PROD Gate having run before D-035. reports-sdk and template-python-package keep a private pin in
`requirements-dev.in` and pass no list, so each was one pull request from the same failure. Each lane declares its
inputs by hand, outside the template's rendered sections, so no test held the eight defaults to the template's.

**Decision.** The owner chose, 2026-10-03, to fix the default rather than each repo. The default is now
`requirements.txt requirements.in requirements-dev.txt requirements-dev.in requirements-test.txt requirements-test.in
pyproject.toml`, a missing file still skipped. A test holds each lane's default and the standalone's equal to the
template's, a test plans a pin found only in each `.in` file on the default and fails on the old list, and a test plans
a pin that sits in both a `.in` file and its lock once.

**Consequences.** No new access. The fetch still mirrors only the allowlisted repos the files pin, and a caller that
passes its own list keeps it, so the three engine pull requests' lists stay right and can be dropped later. A caller
gets the fix when it next runs a lane at this commit or later.

---

## D-042. The shared mutation lane runs the vendored engine alone

- **Date.** 2026-10-03
- **Status.** Proposed. Accepted when the owner merges the pull request that carries it. Ends D-040's transition.
- **Tier / scope:** Quick · `ci-python-mutation.yml` · `docs/reference/WORKFLOWS.md` ·
  `docs/features/version-scripts-sync.md` · the tests

**Context.** D-040 let `ci-python-mutation.yml` run a caller's own `mutation_tests/run.py` while one existed, so no
merge order broke a caller, and said the fallback goes once the SDK, the last to move, has. It has. The SDK's switch
merged as its pull request 127 on 2026-10-03, after hub 392, fitness-app-backend 201 and tiffanys-space-backend 132.
The lane's callers were read on GitHub that day, the SDK's `merge-gate.yml` and both backends' `prod-gate.yml`, the
hub running the engine from its own `mutation-tests.yml`, and no other repo naming the lane. Each caller's `main`
holds no `mutation_tests/run.py` and holds `scripts/kdf_scripts/mutation_runner.py` as blob `4820a7e`, cicd's own.
The SDK's pull request showed the engine's file as changed rather than added, which read as a copy an earlier sync had
placed. Its history says otherwise, the path first appears in that pull request's `59ac7fc`, and git pairs it with
the deleted `mutation_tests/run.py` as a rename.

**Decision.** The lane runs `scripts/kdf_scripts/mutation_runner.py` alone. A runner of the caller's own left in the
tree is never run, and a caller without the engine fails at once with an error naming the scripts sync, before any
mutant is applied. A test runs the step's own shell both ways, with a stale `mutation_tests/run.py` beside the engine
and without the engine, and fails on the old step in both.

**Consequences.** A new repo that runs Python mutants receives the engine from the scripts sync before its lane can
pass, the registry entry naming it. An engine fix lands in cicd alone and reaches the four repos with the next sync.

---

## D-043. The canonical kdf-fmt pin is v1.3.0, and cicd formats with the version it hands out

- **Date.** 2026-10-03
- **Status.** Proposed. Accepted when the owner merges the pull request that carries it. Each repo's own pins move in a
  pull request of its own, after this one.
- **Tier / scope:** Quick · `scripts/scripts_registry.json` `requirements_patch` · this repo's `ci.yml` style job ·
  `scripts/tests/test_distribute_scripts_requirements.py`

**Context.** The owner's Distribute scripts run of 2026-10-03, scripts 1.5.0, opened seven pull requests and left ten
repos NEEDS MANUAL ATTENTION. The registry's canonical kdf-fmt pin was v1.1.1, while kdf-fmt had moved to v1.2.0 and
then v1.3.0 (kriegerdataforge-fmt D-008, the owner's approved item 7 of the SDK S1 retrospective, which names the line
it refuses and skips a wrap that would change the program). The hub pinned v1.2.0, two repos pinned v1.1.0 in
`requirements-dev.in`, and seven Next.js and portfolio repos called the style lane at v1.1.0. The distributor never
moves a pin, since a kdf-fmt version change can move a style baseline, so each of the ten stopped. cicd's own style
job ran v1.1.0, a version behind the pin it handed out, and nothing held the two together.

**Decision.** The canonical pin is v1.3.0, in both `kdf_fmt_ref` and the kdf-fmt spec, and this repo's style job
calls `ci-kdf-fmt-self.yml` at v1.3.0. The Makefile reads `KDF_FMT_VERSION` from `ci.yml`, so it moves with it. cicd's
style check passes on v1.3.0 with its baseline unchanged, with no new finding. A test reads the live registry and holds
the ref, the spec's ref and this repo's `ci.yml` to one version, and it fails on the old `ci.yml`.

**Consequences.** Every repo moves its `requirements-dev.in` pin and its `ci.yml` `kdf_fmt_ref` to v1.3.0 in its own
pull request, which runs its style check on v1.3.0 and fixes any new finding there. Distribute scripts is then run
again, and the ten repos receive scripts 1.5.0. The seven sync pull requests already opened carry v1.1.1 in
`requirements-dev.in`, and their repos' pin pull requests move it.

---

## D-044. A public repo's style check is one job that leaves no artifact

- **Date.** 2026-10-03
- **Status.** Proposed. Accepted when the owner merges the pull request that carries it. Completes D-038 for public
  callers, this repo among them, and retires its `ci-kdf-fmt-self.yml`.
- **Tier / scope:** Standard · the new `ci-kdf-fmt-public.yml` · `ci-kdf-fmt-self.yml` removed · this repo's `ci.yml` ·
  `ci-python-kdf-fmt.yml`'s header ·
  `docs/reference/WORKFLOWS.md` · `docs/security/CONTROL_PLANE_SECURITY.md` · the tests · the two public portfolios'
  `ci.yml`

**Context.** D-038 split the style lane so its check job names no secret, the formatter reaching it as a mirror in a
run artifact. A run artifact of a public repo is readable by anyone, so the fetch refuses a public caller's mirror of
the private formatter. D-038 gave this public repo its own one job check, `ci-kdf-fmt-self.yml`, and left the two
public portfolios, `arthurs-portfolio` and `kriegerdataforge-portfolio`, calling the shared lane, whose fetch now fails
them on every run with "kriegerdataforge-fmt is private and the calling repo is public". The kdf-fmt v1.3.0 pin pull
requests of 2026-10-03 (arthurs-portfolio 99, kriegerdataforge-portfolio 69) showed it, no pin can make it green.

**Decision.** The owner chose, 2026-10-03, "A public-repo lane". `ci-kdf-fmt-public.yml` is this repo's own check
made callable. One job named `Style (kdf-fmt)`, so a caller's check keeps the name `style / Style (kdf-fmt)`. The token
is minted for `kriegerdataforge-fmt` alone and read only, App token first and `GH_PACKAGES_PAT` after. A first step
fails by name when no token reaches the job, a fork's or Dependabot's run, so such a run never passes. The install and
the check run in isolated mode, the check's command is fixed, and the caller names only an optional `baseline` file,
a plain name in the repo's root. Nothing is uploaded. This repo's own `ci.yml` calls the new lane too, with its
`kdf-style-debt.json` baseline, so its check keeps the name `style / Style (kdf-fmt)`, and `ci-kdf-fmt-self.yml` is
retired, leaving one one job style check that cannot drift from a second.

**Consequences.** This repo's check runs on the new lane from this pull request on. The two portfolios' style check
passes once this merges and each repo holds the token,
`USE_GITHUB_APP` with `KDF_APP_ID` and `KDF_APP_PRIVATE_KEY` or `GH_PACKAGES_PAT`, which the owner sets. Without one it
fails with the message that says so, as a fork's run does. Pinned by
`test_a_public_caller_runs_the_style_check_in_one_job_that_leaves_no_artifact`,
`test_the_public_lane_mints_for_the_formatter_alone_and_installs_isolated`,
`test_this_public_repo_runs_its_own_style_check_in_isolated_mode`,
`test_the_public_style_lane_fails_closed_without_a_token` (whose cases fail on a step that never checks) and
`test_the_public_style_lane_runs_one_fixed_command`.

---

## D-045. The fetch leaves nothing writing a mirror once it returns

- **Date.** 2026-10-03
- **Status.** Proposed. Accepted when the owner merges the pull request that carries it. Corrects D-035's fetch.
- **Tier / scope:** Quick · `scripts/fetch_private_packages.py` and every copy of the fetch job rendered from it
  (the eight lanes and `fetch-private-packages.yml`) · `scripts/tests/test_secretless_lanes.py`

**Context.** template-python-package pull request 58's lint and unit test fetch jobs failed at the pack step with
`tar: kdf-private/mirrors/kriegerdataforge-fmt.git/objects/pack: file changed as we read it`, and the job's cleanup
then killed an orphan git. That repo pinned kriegerdataforge-fmt at two refs, v1.1.0 in a stale `requirements.txt`
and v1.3.0 in `requirements-dev.in`. The fetch ran one `git fetch` per ref, so the second went into a mirror that
already held objects, and a fetch ends by starting git's automatic maintenance, a gc that detaches by default and
keeps writing `objects/pack` after the fetch returns. The pack step's tar read the folder while it changed. D-041's
wider default list reads the `.in` files beside their locks, which makes two refs of one repo more likely.

**Decision.** Every git call the fetch makes passes `-c gc.auto=0 -c gc.autoDetach=false -c maintenance.auto=false
-c maintenance.autoDetach=false`, so no maintenance starts and nothing that would start detaches. The pins of one repo
are fetched in one `git fetch`, which also passes `--no-auto-maintenance`. An extra repo that a file read inside it
also pins is still fetched twice, which is why the settings, and not the single fetch, are the guarantee. Every copy
of the fetch job was rendered again from the script. A test plans two tags of one repo and finds one fetch with
maintenance off, and a test finds every setting on the command line of a git call before its own arguments. Both fail
on the old script. Rehearsed in `python:3.14.7-slim` with git 2.47.3, a source of 4,560 loose objects, two tags, and a
global config with `gc.auto=1` and `gc.autoPackLimit=1` standing for a mirror past git's thresholds. The old script
left a detached gc running at the moment tar started in five rounds of five, and the new one in none.

**Consequences.** The pack step reads mirrors no process is writing. A caller whose fetch failed this way passes once
it runs again at this commit or later. The mirror's own config is unchanged, so the install job's git reads it as
before.

---

## D-046. A session commits STATUS.md straight to main of kriegerdataforge-context, and nothing else reaches main

- **Date.** 2026-10-03
- **Status.** Proposed. Accepted when the owner merges the pull request that carries it. Kit v1.14.0, reaching every
  repo with the next Distribute. Narrows the owner rule that only the owner pushes to `main` by one named exception.
- **Tier / scope:** Standard · `tools/claude-code/kdf-guard.js` and `guard-cases.json` · the new
  `scripts/tests/test_guard_status_push.py` · kit `docs/agent/AGENT_ROLES.md` rule 4 and its ruleset paragraph,
  `WORKFLOW.md`'s role summary and `CODE_REVIEW_PROCESS.md`'s role and guard tables · cicd's own copies, `AGENTS.md`
  and `tools/claude-code/README.md`

**Context.** The owner is building `kriegerdataforge-context`, a private repo beside the others that holds the
ecosystem's context for every session, its vision, its map of the repos, its ways of working, and a `STATUS.md` of the
live state of the work. The vision and the map change slowly and go through pull requests. The status changes every
session, and the owner decided on 2026-10-03, "I prefer having sessions commit STATUS.md straight to the context
repo's main because then where I go its up to date and I can read it from anywhere and its versioned with git". The
guard refuses every push to `main`, so it needs one exception, as narrow as the decision.

**Decision.** The guard lets a push to `main` through only when every one of these holds, and refuses it as before
otherwise.

- The call is a plain `git push origin main` and nothing else, one segment with no wrapper, assignment, redirect,
  nested shell, `cd` or `find -exec` around it, and no option but `-C <dir>` before the subcommand.
- The role is not reviewer. Reviewer git refuses every push before the exception is reached.
- The repo's fetch URL and push URL both name `Needless2Say/kriegerdataforge-context`, on github.com by https or ssh,
  or as a path on this machine, so a `pushurl` or an `insteadOf` that leads elsewhere refuses it. The URL may hold a
  credential, so the guard reads it and never prints it.
- No GIT_ variable that moves git, `GIT_DIR`, `GIT_WORK_TREE`, the object store or the configuration variables, is set.
- `main` is checked out.
- After a fetch of `main` into `origin/main`, every commit in `origin/main..main` changes `STATUS.md` alone. A merge
  commit, an empty commit, a commit that adds and a later one that removes another file, and more than 50 commits
  each refuse it.
- Any git error refuses it. The guard's git calls take no shell, time out after 20 seconds, prompt for nothing and
  print nothing.

**Proof.** `test_guard_status_push.py` builds a real clone of a bare repo whose path ends in
`Needless2Say/kriegerdataforge-context.git` for each case. The allowed push, the same from another folder with `-C`,
and a push with nothing new go through. Twenty four other pushes are refused, another file in a commit, a file added
then removed, another file alone, an empty commit, a merge, another repo, a lookalike owner, no remote, a push URL
elsewhere, `HEAD` on another branch, a detached `HEAD`, force, force with lease, a `HEAD` refspec, an explicit
refspec, another branch name, another remote name, a `cd` before it, a pipe after it, an `env` prefix, a git setting,
a nested shell, `find -execdir` and a `GIT_DIR`. The control runs each of them against a copy of the guard whose
exception lets every push through, and each is then allowed, so each refusal is the exception's doing. The guard's own
`contextRemote` is run on eight forms of the right URL and nine lookalikes, and `guard-cases.json` gains seven cases.

**Consequences.** A session updates `STATUS.md` with `git commit` on `main` and a plain `git push origin main` from the
context repo, after a `git pull --rebase` when another session pushed first. Every other change to the context repo,
the vision included, goes through a pull request. On GitHub, the context repo carries no ruleset that refuses a direct
push to `main`, since the exception would be moot, so rule 4 and the guard are its fence. The owner runs
`bash tools/claude-code/install.sh` from the cicd clone after the merge, since the installed guard is a copy.

**And every repo's AGENTS.md names the context repo.** The owner decided on 2026-10-03 that each repo's `AGENTS.md`
gains a line naming `kriegerdataforge-context/` as the ecosystem context, with the next kit release, which this one
is. Codex and the other tools read `AGENTS.md`, not a `CLAUDE.md` above the repo. The kit sync never wrote a repo's own
`AGENTS.md` before, so `distribute_kit.py` now inserts one paragraph, "**Ecosystem context.** Before anything else,
read `../kriegerdataforge-context/AGENTS.md`...", into the sync pull request it opens anyway, after the role pointer
blockquote at the top, or after the first heading where a page has none, or at the top of a page with no heading. It
writes the line only when the page lacks the path, so a second run writes nothing, keeps the page's CRLF or LF line
ends, and changes no other line. `check` reports a page without it as drift. The line names a path only, since this
repo is public, so the context repo holds an `AGENTS.md` of its own. cicd's own `AGENTS.md` carries the line by hand,
and a test holds it where the sync would put it. Those sync pull requests now change `AGENTS.md`, which the version
check did not exempt, so `scripts/common/check_version.py` lets `AGENTS.md` through on a `chore/kit-sync-*` branch
alone, and off that branch it still needs a bump. That changes a synced script, so `scripts/SCRIPTS_VERSION` is
1.5.1. Consumers' pull request CI runs cicd's own `check_version.py` from `main`, so the exemption holds from the merge,
before any scripts sync. `test_distribute_kit_agents.py` covers the line present, absent, after a pointer quote that
runs into a heading, with no role pointer, with no heading, a quote that ends the file, CRLF, a second run, check,
distribute, a re-run over a branch that has the line, the version check on three branches, and a control whose insert
returns the page unchanged, under which distribute writes nothing.

---

## D-047. A Distribute runs no CI where every change is already tested, and Dependabot raises alerts only

- **Date.** 2026-10-04
- **Status.** Proposed. Accepted when the owner merges the pull request that carries it. Takes effect for the next
  Distribute run from cicd's `main`, no repo needs a Distribute first.
- **Tier / scope:** Standard · `scripts/common/repo_sync.py` · `scripts/distribute_kit.py` ·
  `scripts/distribute_scripts.py` and `scripts_registry.json` · the new `scripts/distribute_all.py` ·
  `scripts/common/check_version.py` (SCRIPTS_VERSION 1.5.2) · the four `ops-distribute-*.yml` workflows and the new
  `ops-distribute-all.yml` with its issue form · the docs · the tests

**Context.** The owner is near the month's GitHub Actions limit. A kit Distribute opened a sync pull request in each
of 17 private repos, and each ran the repo's whole CI, measured on the kit v1.14.0 sync at 10 to 24 billed minutes a
repo (9 to 16 jobs, each billed at least a minute), about 250 to 300 minutes a Distribute, for files cicd had already
tested. After the merge only light push workflows run. Measuring further found a larger drain. Dependabot's version
update pull requests cannot install the private packages, fail, and run CI again on every rebase, an estimated 800
billed minutes a week in auth-ui, the hub, the SDK and kdf-fmt alone. Each finished Distribute also left its issue
open, 21 by 2026-10-04.

**Decision.** The owner chose, 2026-10-04, to skip CI for a sync of tested copies, to carry the kit and the scripts in
one pull request when both are due, to stop Dependabot's pull requests while keeping its alerts, and to have the
issues close themselves. A docs only fast path in every repo's `ci.yml` was deferred to each repo's next real change.

- **Skip CI, fail closed.** GitHub starts no push or pull_request workflow for a commit whose message holds
  `[skip ci]`, and for a pull request it reads the HEAD commit. `skip_ci_eligible` in `repo_sync.py` says yes only
  when something changed and every changed path is on an exact allowlist, never a directory. Every commit of an
  eligible sync carries the marker, so whichever is HEAD does, and the pull request body says CI was skipped, or names
  the files CI runs for.
- **The allowlists.** The kit's registry files, the AGENTS.md context line (D-046) and `.github/dependabot.yml`, so
  a kit sync always skips. For the scripts, a `files[]` entry opts in with `"pretested": true`, the three version
  scripts. The mutation engine stays off, cicd tests it but never against a repo's own tables. Every patch of a repo's
  own file (`Makefile`, `requirements-dev.in`, `kdf-fmt.toml`, `ruff.toml`, `pyproject.toml`) and every delete stays
  off, so a sync that patches runs the repo's CI as before.
- **One pull request for both.** `distribute_all.py`, the label `ops:distribute-all` and its issue form run the kit's
  and the scripts' items into one `chore/ecosystem-sync-kit-<kit>-scripts-<scripts>` branch per repo through the same
  owner-only gate. The skip rule judges the whole change set. The separate flows keep working.
- **The version check.** A `chore/ecosystem-sync-*` branch may carry what either sync may, and a `chore/kit-sync-*`
  branch may also carry `.github/dependabot.yml`. Consumer CI runs cicd's own copy, so the change is live on merge and
  needs no scripts Distribute.
- **Dependabot alerts only.** The kit sync sets `open-pull-requests-limit: 0` on every `updates:` entry of a repo's
  `.github/dependabot.yml`, inserting it where missing and replacing another value, keeping comments, order and line
  endings, and never creating the file. A limit of 0 stops version updates only. Security update pull requests are a
  repo or account setting the owner turns off, and alerts stay on. No CI job of any repo reads the file, and pushing
  it needs only `contents: write`, since it is not under `.github/workflows/`.
- **Issues close themselves.** Each Distribute workflow, kit, scripts, the combined one and the App secrets one, ends
  with a step that runs `always()` and closes the issue, completed when the job succeeded and not planned otherwise,
  with the `issues: write` the job already holds.

**Consequences.** A Distribute of the kit, or of version scripts alone, costs the cicd run that makes it, which runs
in this public repo, and no CI minute in the repos. Sync pull requests show no checks, so the owner merges them with
the bypass where a ruleset requires checks. A broken kit copy would surface at the repo's next ordinary pull request,
an accepted risk since the copies are tested here. The owner creates the `ops:distribute-all` label once. Pinned in
`test_distribute_skip_ci.py` (the allowlists, each eligible path, ten kinds of ineligible path, an empty change set,
the marker on every commit and the HEAD, the body, the kit sync, the combined flow, the version check on seven
branches, and controls under a rule that says yes to anything), `test_dependabot_limit.py` (present, absent, another
limit, nested `groups:` and `ignore:`, CRLF, a second run, no `updates:` list, items at column zero, a quoted or
empty limit, no final newline, never creating the file, and a control) and `test_ops_distribute_workflows.py` (the
close step's place and shell in all four workflows, three outcomes, a control, and the combined workflow's gate).

---

## D-048. Codex in the cloud on Codex's rebuilt cloud, with no token and no pull request

- **Date.** 2026-10-04
- **Status.** Proposed. Accepted when the owner merges the pull request that carries it. Kit v1.15.0, reaching every
  repo with the next Distribute. The kdf-sdk's S2 runs its Codex turns this way from the start.
- **Tier / scope:** Standard · `kit/common/docs/agent/CODE_REVIEW_PROCESS.md` sections 4, 10 and 11 · the cloud's
  git exception in `AGENT_ROLES.md` and `templates/review-brief.template.md` · `tools/codex-cloud/` ·
  `tools/claude-code/kdf-review.sh`'s collect messages · the docs · the tests

**Context.** D-039 put Codex in the cloud on trial for the kdf-sdk's S2, with a token of its own handed to a setup
script, and a report returned through a pull request the owner closed unmerged. On 2026-09-29 OpenAI rebuilt Codex's
cloud. The environment D-039 was written for is now "Codex Cloud (Legacy)", kept for Code Review and the GitHub and
Linear integrations and due to retire. A new environment is published from an Install script and a Start skill that
Codex drafts with the owner. Its secrets are network secrets, the process sees a placeholder and a proxy puts the real
value into an HTTPS request to a listed domain, so a token git sends inside Basic authentication is most likely never
put in. A task starts in `/workspace` from the published copy of `main`, on a branch named `work`, with no branch to
choose and no Create PR button. Setting up the kdf-sdk's environment on 2026-10-04 found more. Codex's own drafts
asked for the owner's package token, named a failing test as a known defect in the Start skill every task reads, and
kept their notes in `/workspace/.cloud-onboarding`. With the agent's internet off, git in a task cannot reach GitHub,
`CONNECT tunnel failed, response 403`. The Codex CLI's `codex cloud` commands, 0.160.0, list none of the new tasks.

**Decision.** The owner chose, 2026-10-04, an environment with no token, an agent that reaches `github.com` alone, and
a report pushed on a branch of Codex's own with no pull request.

- **No token.** `tools/codex-cloud/kdf-codex-install.sh` replaces `kdf-codex-setup.sh`. It installs the runtime
  lockfile, the development pins without any line from the owner's private repos, then the repo without its
  dependencies, and ends with `pip check`. kdf-fmt, the kdf-sdk's only private package, runs only the style lane,
  which a review read does not need. A repo whose runtime lockfile names a private package stops with exit 1, since
  its install would need a token. Python is the image's 3.14, or uv's under the workspace, which the published
  environment keeps, and a venv whose interpreter is gone is made again.
- **A neutral Start skill.** `kdf-codex-start-skill.md` says how to enter the venv and what the environment leaves out
  on purpose, and names no finding, so a reviewer meets what the onboarding saw on its own. Codex's drafts are
  replaced and its onboarding notes deleted before the environment is published.
- **`github.com` alone.** The agent's internet is on for custom domains, `github.com` and nothing else. Git then
  fetches and pushes through Codex's GitHub connection, which reaches the reviewed repo alone, while PyPI and every
  other site stay closed, and `main`'s ruleset refuses a direct push.
- **No pull request.** The one line tells Codex to fetch `review/<pfx>-<slice>`, make `review/<pfx>-<slice>-codex` at
  the pin, read and run the review, commit its report alone and push that branch. `--collect-branch` checks it exactly
  as before. The reviewer rules and the brief name that git as the cloud's only exception, and the launcher no longer
  tells anyone to close a pull request. The owner deletes both review branches when the review closes.

**Alternatives considered.**

- *D-039's token as a network secret.* Rejected. Git carries a token inside Basic authentication, where a placeholder
  is most likely never replaced, and holding no token is the more secure option.
- *Internet off, a git bundle the owner attaches and a report the owner pastes back.* Rejected by the owner, every
  Codex turn would need the owner at the machine.
- *A Legacy environment with Create PR.* Rejected. It is due to retire, and a pull request runs the repo's Merge Gate,
  about 10 to 20 billed minutes a Codex turn.
- *The orchestrator starting tasks with `codex cloud exec` and reading them with `codex cloud diff`.* Parked until the
  CLI lists the new cloud's tasks.

**Proof, 2026-10-04.** The install ran on the kdf-sdk at `d9a4602` in `python:3.14.7-slim`, 1938 tests passed and the
5 that failed needed only the image's missing git and make, and in a uv image without Python, from a fresh folder, a
broken venv and a second run. The owner's `kdf-sdk-review` environment was published and its smoke test ran the suite
as the draft had. A task with `github.com` allowed listed and fetched the kdf-sdk's branches, could not reach PyPI, and
pushed `codex-probe/push-test` at `b255faf`. No workflow ran for it. `--collect-branch` brought its file in from a fresh
clone and refused it with exit 3 against an older pin.

**Consequences.** Kit v1.15.0 carries the process, the reviewer rules and the brief template to every repo with the
next Distribute, which runs no CI there (D-047). Codex's commits carry the owner's name, so GitHub cannot tell them
from the owner's, and the collect check stays the fence. A Codex review in the cloud runs the tests but not the style
lane, `pip-audit` or the consumer check, which the orchestrator runs. A backend's review in the cloud needs a design
for its private runtime package first. Pinned in `test_codex_cloud_install.py` (a clean install without the private
line, uv when the image has no Python, a venv kept and one made again, a private runtime package, a missing
requirements file, each failing pip call, no secret in the script, a neutral Start skill) and
`test_claude_code_tools.py` (the process, the reviewer rules and the brief template, and a collect that names no pull
request). VERSION 0.2.129.

---

## D-049. The weekly ecosystem watch, and token expiry read from each provider

- **Date.** 2026-10-04
- **Status.** Proposed. Accepted when the owner merges the pull request that carries it. The watch starts when
  kriegerdataforge-context's caller is merged and the KDF GitHub App has its new read permissions, and the live
  expiry with the next Monday run of `check-secret-expiry.yml`.
- **Tier / scope:** Standard · the new `scripts/ecosystem_watch.py` and `.github/workflows/ecosystem-watch.yml` ·
  `scripts/rotate_secret.py` (`--live`) and `.github/workflows/check-secret-expiry.yml` · `scripts/secret_registry.json`
  (`check.live` on four tokens, kriegerdataforge-context added to the App secrets' targets) · the docs · the tests

**Context.** Since D-047, Dependabot raises alerts and opens no pull request, so nothing gathers the alerts of 18
repos in one place. The kdf-fmt pin that broke a Distribute on 2026-10-03 lagged its release with nothing to say so,
and the ubuntu-latest notice reached the owner only by a session reading a run's log. The expiry monitor of
`check-secret-expiry.yml` read hand typed dates from the registry, which went stale. Its issue of 2026-09-29 listed
four tokens as expired as long ago as 2026-07-30 while CI kept working on them, and it was closed, which is how a real
expiry would have passed unseen. The owner picked the watch from the backlog on 2026-10-04 and chose its four
checks, the KDF GitHub App as its reader, one rolling issue, and a private repo for its run, since a list of a private
repo's open vulnerabilities must never reach a public repo's issues or logs. The owner also plans an admin dashboard
over every repo, recorded in the context repo's backlog.

**Decision.**

- **The collector, in cicd.** `scripts/ecosystem_watch.py collect` reads, for cicd and every kit target, the open
  Dependabot alerts, each pin of a package built from one of the owner's repos (requirements files, `pyproject.toml`,
  `package.json`, the `kdf_fmt_ref` of `ci.yml`, and cicd's canonical kdf-fmt pin) against that repo's highest
  `vX.Y.Z` tag, a full commit pin matched to its tag, each kit target's `KIT_VERSION` and each vendored script's blob
  sha against cicd's (the mutation engine only where its entry vendors it, D-040), and the deprecation notices on the
  latest completed run of each active workflow, asked of that workflow, GitHub's dynamic workflows left out. Every
  page of every list is read, the alerts by GitHub's cursor. A repo, a call or an answer it cannot read is an error
  in the snapshot, never a crash, and a pin it cannot judge is a finding.
- **A snapshot first.** It writes JSON, schema `kdf-ecosystem-watch/1`, which `render` turns into an issue body, the
  news since the previous body and a state, open or clear. Each finding is remembered in the body as 10 hex of its
  key's sha1, at most 3000, so a body stays under GitHub's limit and news is what the last body did not carry. The
  same snapshot can feed the admin dashboard later.
- **Run from a private repo.** `.github/workflows/ecosystem-watch.yml` is reusable only, no event of this public repo
  starts it. It checks out cicd's `main` scripts, mints a read only App token (contents, vulnerability alerts, checks,
  actions), keeps the snapshot as a 30 day artifact, and keeps one issue labelled `ops:ecosystem-watch` in the caller
  with the caller's own token, a comment only for news, posted before the body that remembers it, closed when clear.
  The log carries counts alone.
  kriegerdataforge-context holds the caller and joins the App secrets' targets.
- **Live expiry.** `rotate_secret.py --mode check --live` reads each registry secret whose `check.live` says how,
  `github` from the `github-authentication-token-expiration` header of `GET /rate_limit`, `vercel-current` from
  `/v5/user/tokens/current`, and `vercel-named` from the master token's list of tokens by name. The secret goes to
  its own provider alone and only the date is printed. A rejected token needs rotation, a registry date that
  disagrees is drift that opens the issue (`REGISTRY_DRIFT:`), and a check that cannot answer falls back to the
  registry. The Monday workflow hands `CICD_PAT`, `GH_PACKAGES_PAT` and `VERCEL_MASTER_TOKEN` to that one step.

**Alternatives considered.**

- *Run the watch in cicd, which holds the repo list.* Rejected, cicd is public, so its issues and logs are, and
  alerts on private repos are a map of known weaknesses. Its code and tests live here, its run does not.
- *A fine grained PAT as the reader.* Rejected by the owner for the App, whose tokens last an hour and never expire.
- *A new issue every week.* Rejected by the owner for one rolling issue that emails only news.
- *Keep the hand typed dates and remind the owner to update them.* Rejected, they went stale twice.

**Review, 2026-10-04.** An independent review found no high defect and four medium ones, all fixed, each pinned by a
test that fails when the fix is undone. A source repo whose tags cannot be read now keeps the issue open as a blind
spot, where it had closed it as clear with every pin of it unjudged. Text from a run's annotation, a workflow's name
or an error is made inert, and only the marker that closes the body counts, so a run cannot hide the body, silence an
alert's news or mention a person. The reusable workflow's first step refuses a caller the API does not report
private. The expiry monitor fails closed when its check prints no verdict, and the live check reports any exception by
its type alone. Besides, tags are read past their first page, two Vercel tokens of one name give the earliest expiry,
a notice counts only from the runner's own annotations (path `.github`, measured on real runs, a linter's warning
carries its file's path), and a finding reopens the last closed issue rather than opening another. A separate GitHub
App with read permissions alone, whose key would then be the only one in the context repo, is left to the owner, who
kept the shared App for now.

**Second review, 2026-10-04.** A read only Codex review of the branch found no high defect and six medium ones, all
fixed, each with a test that fails when its fix is undone, 27 controls in all. Dependabot alerts are read past the
first page, by the cursor of GitHub's `Link` header, so a critical alert on page two is counted and remembered.
Notices come from each active workflow's own latest run, every annotated job and every page of its annotations,
where one list of the latest 50 runs let a busy CI hide another workflow's run. A source repo's release is read once
behind a lock, so two workers never read it twice and keep the success while a pin stays unjudged. A pin the watch
cannot judge, its source unreadable, with no plain `vX.Y.Z` tag, or an npm range it does not read, is a finding that
keeps the issue open. The news is posted before the body that remembers it, so a comment that fails is posted by the
next run, and a clear run rewrites the body before it closes, so a finding that comes back is news. A dead
connection, or an answer of a shape the watch does not know, is a blind spot of that call or repo, named by its
exception's type, never the end of the run.

**Proof.** A live read only run of the collector through the gh login on 2026-10-04 read 18 repos in 30 seconds with
nothing unreadable, every release tag, 32 kdf-fmt pins with one behind (template-python-package's compiled
`requirements.txt` at v1.1.0), 15 commit pins matched to v0.12.2 and v0.2.11, 35 open alerts in six repos, and two
notices, the ubuntu-latest move and the deprecated `app-id` input of `create-github-app-token` in cicd's own
workflows. That run's first version reported 13 false drifts for the mutation engine, which the per file `repos` of
the scripts registry now prevents and a test pins.

**Consequences.** The owner gives the KDF GitHub App read access to Dependabot alerts, Checks and Actions (Contents
it has), approves it on the installation, runs `ops:distribute-app-secrets` for the context repo, and merges the
context repo's caller, about a billed minute a week there. Switching cicd's workflows from `app-id` to `client-id`
is left for its own change. Pinned in `test_ecosystem_watch.py` (versions, pins, the collector on a fake GitHub, the
mutation engine's scope, notices, rendering, news, the size limits, the log), `test_ecosystem_watch_workflows.py`
(the triggers, the secrets, the token's scope and holder, the issue's token, the pins, the expiry monitor, and the
issue step's own shell run after run against a fake `gh`), the live
expiry tests in `test_rotate_secret.py`, and the App secrets' targets in `test_distribute_app_secrets.py`. VERSION
0.2.130.

**First run, 2026-10-05.** The first run by hand from the context repo passed every step, read all 18 repos with
nothing unreadable, and opened its issue with 41 findings, 35 alerts, one pin and five notices. Reading each
workflow's own latest run found three notices the dry run had missed, and all three came from runs four months old
whose code had since moved on (Terraform's CD of 2026-05-30, `distribute-gh-pat.yml` of 2026-06-29, and a hub
workflow that now lives on a feature branch alone). Only a new run clears such a notice, and for a deploy that is no
reason to run one, so a notice seen only on runs older than `NOTICE_DAYS` (60) is now listed with its run's date and
counts as no finding, while one a recent run carries still counts. The findings it raised are fixed here, every
`create-github-app-token` step passes `client-id`, which the action reads as the App's id or its client id alike
(`main.js`, `client-id || app-id`), so `KDF_APP_ID` stays and no secret changes, and `run-e2e/action.yml`, the last
v2.2.2 pin on Node.js 20, moves to v3.2.0. Its own `app-id` input keeps its name, so the six repos whose PROD Gate
calls it change nothing. The hub mints its own tokens and changes in its own pull request, and the npm alerts are
cleared in each repo's lockfile, all but `braces` (GHSA-vfj7-8cjw-p6xm), whose advisory has no fixed release. Pinned
by `test_every_app_token_step_is_on_one_pin_and_passes_a_client_id` and the old notice tests. VERSION 0.2.131.

## D-050. The ecosystem's context leaves this repo for kriegerdataforge-context, and the kit's settled code rules

- **Date.** 2026-10-05
- **Status.** Proposed. Accepted when the owner merges the pull request that carries it, after the context repo's
  pull request that receives the moved pages.
- **Tier / scope:** Standard · `docs/guides/` (four runbooks out), `docs/FOLLOW_UPS_MAKEFILE_PASS_2026-08-09.md` and
  `agents/` out · every reference to them · the kit's `skills.md` and `REPORTS_STANDARD.md` · kit v1.16.0

**Context.** The owner decided on 2026-10-05 that all of KDF's context lives in the private context repo, and that
this repo keeps its engine and the docs of that engine (rule 12, the reusable engine only). The owner's runbooks,
`MANUAL_SETUP.md`, `SECRET_ROTATION.md`, `PROJECTS_BOARDS.md` and `REPORTS_TRIAGE_OPS.md`, are procedures the owner
follows across every repo, and they named every secret and repo in a public repo. The same day an audit of the
supporting session's memory found rules that lived nowhere a second machine, Codex or a reviewer could read, and
the owner settled one of them, the module level variable rule, against the kit's wording.

**Decision.**

- **The runbooks move to `kriegerdataforge-context/ops/`**, the Makefile pass follow ups and the `agents/` skeleton
  to its `docs/engineering/`. Every link and path here names the new home as a path, since this repo is public,
  and a bare name such as `SECRET_ROTATION.md §8.3a` in a script, a registry or a workflow means that page. The
  expiry monitor's issue links the page on GitHub, which only the owner can open.
- **The agent kit stays here and keeps its copy in every repo**, since Codex in the cloud and a reviewer see only
  the one repo. The context repo holds what is true about KDF, the kit holds how to work.
- **`skills.md` gains the owner's module level variable rule** with its one exception, a bare boot audit call in
  an app's entry module, which replaces "no module level `get_*_settings()`". It also gains three traps that lived
  only in memory, a raised `HTTPException` drops a handler's headers, a partial update refuses a supplied field
  with a field validator and `validate_default = False`, and `next dev` writes a block into `AGENTS.md`.
- **Two claims of an approval gate are made accurate.** An Environment loads its secrets and pauses only where it
  configures a reviewer.

**Alternatives considered.**

- *Move the kit's source to the context repo and Distribute from there.* Rejected by the owner, it would change the
  engine for no reader's gain, and the public repos would still receive public copies.
- *Keep the runbooks here.* Rejected, they are the owner's procedures, not the engine's documentation.

**Consequences.** Kit v1.16.0 waits for the owner's next Distribute. A public reader of this repo no longer sees the
runbooks, and the owner reads them in the context repo on either machine. Earlier entries of this log keep the
`docs/guides/` paths they were written with, since the log is append only, and this entry is where the move is
recorded. VERSION 0.2.132.

## D-051. The owner's private runtime packages track main, and the watch judges a pin of main

- **Date.** 2026-10-05
- **Status.** Proposed. Accepted when the owner merges the pull request that carries it.
- **Tier / scope:** Standard · `scripts/ecosystem_watch.py` and its tests · `scripts/fetch_private_packages.py`, its
  copies in the reusable Python lanes and its tests · the kit's `skills.md`, `REPORTS_STANDARD.md` and contributor
  onboarding template · kit v1.17.0

**Context.** The owner asked on 2026-10-05 that a consumer's `requirements.in` name `kdf_sdk` and `kdf_reports`
without a version, so that `make compile-requirements` takes the latest release, where each consumer had pinned a
tag and bumped it by hand. In these repos every pull request that changes code bumps `VERSION` by exactly one and
its merge is released, and only the kit and script syncs land on `main` between releases, which change no package
code (checked on 2026-10-05, every commit past `v0.12.2`, `v0.2.11` and `v1.3.0` was a sync). So `main` is the
latest release. The watch called such a pin "not a version tag", and a lockfile compiled from it holds a sync
commit past the tag, which it called behind every week.

**Decision.**

- **A consumer's `requirements.in` names the owner's runtime packages at `@main`.** Its `requirements.txt` still
  locks the commit, so a build stays reproducible, and `make compile-requirements` moves it to the newest.
- **The watch judges a pin of `main` as current**, and a pinned commit that is no tag as current when GitHub's
  compare finds the latest tag in it, ahead or identical. One compare a commit a run, cached, and a compare that
  cannot be read leaves the commit behind, as before.
- **kdf-fmt keeps its canonical tag pin.** `make setup` installs it from `requirements-dev.in` with no lock, CI
  pins the same tag in `kdf_fmt_ref`, and the scripts sync refuses a repo whose pin differs, so a moving formatter
  would split local style from CI's.
- **The kit's three pages that told a consumer to pin a tag say `main`**, kit v1.17.0.
- **D-035's fetch leaves a `.in` branch to its lock** (the owner's choice, 2026-10-05). A ref read out of a
  requirement file stays a tag or a full commit id, with one exception. A branch written only in `.in` files is let
  through when the lock compiled from each, the `.txt` file of the same name beside it, pins the same repo by a
  full commit id. The fetch takes that commit and never the branch, so CI still fetches only commits that cannot
  move, and a branch with no such lock pin is refused as before. Every lane installs the lock, pip-audit included. A
  lane that installed a `.in` file, directly or through an include of a file it installs, would ask the mirror for a
  branch it does not hold and fail closed in its install job. A requirement file's name holds no colon, so no
  caller's file passes for a mirror's `repo:path`. The five consumers' first runs found the gap, the fetch refused
  `@main` in a job no local run exercises.

**Alternatives considered.**

- *Keep a tag in `requirements.in` and have `make compile-requirements` write the newest release tag into it
  before locking.* Exact releases and no change to the watch or the fetch, but a new script in the compile step of
  every consumer. Not taken, the owner chose `main`, and when the fetch refused it, the lock's commit over a tag.
- *Fetch the branch itself.* Rejected, the job that holds the token would fetch a ref that can move between the
  fetch and the install, the very thing D-035 refuses.
- *Float kdf-fmt too.* Not taken, for the reason above.

**Trade-offs.** A merge whose Release run failed leaves code on `main` that no tag names, and a compile in that
window locks it. A failed Release run is already the owner's to fix. The watch makes one more GitHub call for each
pinned commit past the latest tag. D-035's rule gains one exception, bounded by the lock beside the file.

**Consequences.** Kit v1.17.0 waits for the owner's next Distribute. The five consumers change their
`requirements.in` in pull requests of their own, and each compiles its lock when the owner chooses. Their CI passes
once this merges and each runs again, since a run reuses the cicd commit it first resolved. VERSION 0.2.133.

## D-052. One tool asks Codex, read only, in a folder of tracked files

- **Date.** 2026-10-05
- **Status.** Proposed. Accepted when the owner merges the pull request that carries it.
- **Tier / scope:** Standard · `tools/claude-code/kdf-ask-codex.sh`, its README section and
  `scripts/tests/test_kdf_ask_codex.py` · not synced, it runs from each machine's clone of this repo

**Context.** Since 2026-10-05 a session may ask Codex to review its change before the one push, or for a second
opinion, and every change of that day that went to Codex came back with real findings, the watch's compare and the
fetch fix of D-051 among them. Each session typed the verified invocation by hand from the context repo's ways of
working, a long command of flags, a fresh worktree checked first with `git status --ignored --short`, and a brief
that wrote the read only rules, the writing conventions and the repo's settled decisions again. A flag left out, or
a folder holding a file git ignores, is a mistake no one sees, and a secret file Codex reads goes to OpenAI with the
rest of what it read.

**Decision.**

- **`kdf-ask-codex.sh` is the one way a session asks Codex.** The session's brief holds its question alone. The tool
  sets it in the standard frame, read only, files in the folder alone, PowerShell for commands, the writing
  conventions, the owner's settled decisions from the context repo's `context/SETTLED.md` when that clone sits beside
  this one, and real problems only.
- **Codex's folder holds tracked files alone.** Repo mode makes a detached worktree of the commit, removed when the
  run ends, locked or not, and when git will not remove a worktree it cannot read, that worktree's registration goes
  by hand, never another's. It refuses a commit that tracks a symbolic link, and measures a change from its merge
  base with `--base`, as `git diff <base>...HEAD` does. Files mode copies a folder into a throwaway repo and checks
  the copy, refusing a repo inside it, a symbolic link, a file named like a secret file in any case and a file
  holding a token's shape. The brief is read once, into a copy held to the same checks, and the frame is built from
  it. Either way the folder must hold nothing git ignores or does not track before Codex starts, and git's location
  variables, `GIT_DIR` among them, are unset, so none points the tool or Codex at another repo.
- **The flags are the ones verified on 2026-10-05.** The user's config, MCP servers, plugins, apps, web search,
  memories and other agents off, a read only sandbox, nothing kept after the run, and the frame on stdin.
- **The tool checks Codex afterward.** It fails when `git status` shows a change, when the folder's HEAD moved, when
  git cannot read the folder, when Codex failed or wrote no answer, and when its JSON events hold no completed turn
  or a line that is no event. It warns when the events show anything but commands, reasoning, a plan and answers.
- **The answer is archived outside every repo**, in the workspace's `temp/codex`, under a name no other run has,
  beside the frame and the events, under a header with what was read, the model, the effort, the time and the tokens.
  When the archive cannot be written the answer is printed before the run fails.
- **A session in the reviewer role never runs it.** A review campaign's Codex reads stay with `kdf-review.sh`.

**Alternatives considered.**

- *Keep the invocation in the ways of working.* Rejected, every session retyped it, and the checks around it were
  each session's to remember.
- *Let Codex read the session's own clone.* Rejected, a clone holds every file git ignores, `.env.local` and build
  output among them, and the session's uncommitted work moves while Codex reads.
- *Scan a repo's tracked files for a token's shape too.* Not taken, sixteen tracked files across four repos hold a
  key's or a token's shape on purpose, test fixtures, examples, docs and a secret scan's own config (counted on
  2026-10-05), so the scan would refuse those repos whole.

**Trade-offs.** Codex's sandbox on Windows stops writes and the network, not reads, so the frame's rule to read only
inside the folder is what keeps Codex from a file outside it. Codex in a container with the folder alone mounted
would close that, and is not built. Repo mode sends what the commit tracks, so a secret committed by mistake reaches
Codex before the secret scan in CI finds it. The guard keeps a session from reading a secret file, the usual way such
a mistake starts. A worktree holds committed work only, so a session commits before it asks. The token scan knows
the common shapes, not every one, so a files mode folder holds the session's own patches and nothing copied from a
secret store. The settled decisions add about two thousand tokens to every run as they stand, and `--no-settled`
leaves them out.

**Consequences.** The tool's first run reviewed its own change and found ten problems, a symbolic link and the brief
getting past the secret checks, a commit leaving `git status` clean, a locked worktree left behind and two runs in
one second sharing an answer among them. Its second run, on those fixes, found four more, the brief read again after
its check, a fallback `git worktree prune` that could drop another session's worktree, a worktree both locked and
broken left registered, and events that showed nothing still passing. All fourteen were fixed before the pull request
opened, each with a test that fails when its fix is taken out. The context repo's ways of working name the tool in
place of the invocation. A machine has the tool once its clone of this repo is pulled, with nothing to install.
VERSION 0.2.134.
