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

## D-004 — Feature-flag convention: a simple owned flag now, a flag service as a design-gated escalation

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
- **Escalation (scalability):** per-user / percentage / cohort rollout, remote kill-switches, or A/B belong
  to a **dedicated feature-flag service**, adopted via its **own design gate** — not invented mid-slice.

**Alternatives considered.**

- *Build a flag service now* — deferred: it's a multi-week epic with its own infra, authz, and audit
  surface; bundling it into a docs-hardening change would violate the standard's own design-before-code rule.
- *Leave flags undefined / design-gate every time* — rejected: no consistency; every epic re-litigates the basics.

**Trade-offs.** The simple flag has no per-user/percentage targeting — accepted for now; the convention
names the exact escalation trigger so a service is adopted **deliberately**, requirements known, not prematurely.

**Consequences.** Roadmap: **"evaluate / stand up a feature-flag service"** is a design-gated epic to scope
when the first slice needs cohort/%/kill-switch rollout. Until then, `GET /config/flags`-style endpoints are
the sanctioned cross-layer mechanism, and "off by default in `main`" is enforced by the owning backend's setting.

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
