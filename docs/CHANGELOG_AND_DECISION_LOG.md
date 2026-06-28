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
