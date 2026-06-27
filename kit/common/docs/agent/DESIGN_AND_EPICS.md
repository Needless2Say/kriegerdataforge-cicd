# Design Gate & Epic Playbook — KriegerDataForge

Vendored byte-identical across every KDF repo. This is the deep-dive behind the **Epic lane**
in [`../../WORKFLOW.md`](../../WORKFLOW.md). Use it whenever the work is **complex/novel** (a
new subsystem, an auth system, a non-trivial architecture) **or spans more than one repo**.

The golden rule: **design is approved before code; big work ships as many small flag-gated
PRs, never one mega-PR.**

---

## 1. When the design gate is required

| Situation | Design gate? |
| --- | --- |
| Typo / copy / comment / log line / isolated bug-fix | No (Quick lane) |
| A feature within existing patterns, one repo | A plan is enough; design gate optional |
| A **new** pattern, subsystem, or data model | **Yes** |
| Anything touching **auth / OIDC / tokens / sessions** | **Yes** + a protocol design note |
| Anything that **changes an API contract or DB schema** other code depends on | **Yes** |
| Anything that **spans more than one repo** | **Yes** (full Epic track) |

When in doubt, write the design doc — it's cheaper than rebuilding.

---

## 2. The design gate (Discovery → Design → Approval)

### 2.1 Discovery — map the blast radius

Before designing, enumerate everything the change touches, so nothing is discovered mid-build:

- **Repos** — which of the 15 are affected, and in what order?
- **Contracts** — which API endpoints / OpenAPI schemas / SDK surfaces change?
- **Data** — which tables/migrations? Is the migration backward-compatible (expand/contract)?
- **Identity** — does it touch `KDFUser`, JWT claims, scopes, or the per-client OIDC audience?
- **Config / secrets** — new env vars or secrets? (Then Terraform + the secrets inventory move too.)
- **User surfaces** — which screens/flows; what's the flag and the rollout?
- **Unknowns & assumptions** — list them explicitly; resolve the load-bearing ones with the owner.

> Use **parallel sub-agents** here: fan out read-only explorers across the affected repos/modules
> and synthesize one blast-radius map, rather than reading everything serially.

### 2.2 Design doc

Write the design using
[`templates/design-spec.template.md`](templates/design-spec.template.md) — the same 10-section
spec the app repos already use (overview, user stories, MoSCoW requirements, UX, technical
design, data, success metrics, risks, open questions, future). Keep it as long as the decision
is hard and no longer. Store it at `docs/design/<feature>.md` (or inside the epic tracker for
cross-repo work).

### 2.3 ADR — record the decision

Capture the *decision* (not the whole design) as an **Architecture Decision Record** appended to
the repo's decision log `docs/CHANGELOG_AND_DECISION_LOG.md` (create it if your repo doesn't have
one yet — that is the canonical ADR home) using
[`templates/adr-entry.template.md`](templates/adr-entry.template.md): next `D-NNN` id, context,
the decision, alternatives considered, trade-offs, and consequences. ADRs are append-only and
immutable; supersede with a new one rather than editing.

### 2.4 Approval

**The owner approves the design + ADR before implementation begins.** No code until then. For
OIDC/auth-protocol changes, the design note must spell out the token/claim/flow impact and how it
stays backward-compatible during the transition.

---

## 3. The Epic track (cross-repo or large single-repo work)

### 3.1 Decompose into vertical slices

Break the feature into the **smallest independently-shippable, independently-reviewable** slices.
Each slice is one Standard-lane PR. Prefer **vertical** slices (a thin end-to-end path) over
horizontal layers, so each slice delivers and verifies something real. Every slice ships **behind
a feature flag** (off by default) so `main` stays releasable throughout.

### 3.2 Sequence contract-first

Order slices by dependency, contract first:

```text
1. Backend: schema + migration (expand) + endpoint, behind a flag   (fitness-app-backend)
2. SDK/client: regenerate or extend the shared contract             (kriegerdataforge-sdk)
3. Consumer/frontend: build on the new contract, behind the flag    (fitness-app-frontend)
4. Infra: env vars / secrets / flags wired                          (kriegerdataforge-terraform)
5. Enable the flag; end-to-end verify; contract (cleanup) migration
```

Never build a consumer against a contract that doesn't exist yet. Backend + contract land first.

### 3.3 Create the epic tracker (in the hub)

For any multi-repo epic, create **one** coordinating tracker in the ecosystem hub:
`kriegerdataforge/docs/epics/<name>.md` (template:
[`templates/epic-tracker.template.md`](templates/epic-tracker.template.md)). It holds the
blast-radius map, the slice list with a **status grid** (slice → repo → PR → state), the PR
ordering, the flag name, and links to the design doc + ADRs. Every slice PR in every repo links
back to this tracker; the tracker is updated as each slice lands. It is the single source of
truth for "where is this epic."

### 3.4 Execute & integrate

Run each slice through the Standard lane (plan → `make ci` → PR → green CI). Keep the tracker
current. When all slices are merged: enable the flag, run the cross-repo end-to-end check, do a
final review (consider **`/code-review ultra`** on the integrated result), record the outcome in
the decision log, and mark the epic complete.

> **Parallelism:** independent slices in different repos can be built concurrently (separate
> sub-agents / git worktrees). Slices with a contract dependency must respect the order above.

---

## 4. Clarification heuristic — when to ask vs. proceed

**Always ask first** (strategic/ambiguous): target users & problem, success criteria, priority,
must-have vs nice-to-have, anything architectural/destructive/irreversible, anything touching
auth/identity/money, where a new cross-repo contract should live.

**Proceed without asking** (and note it): standard error wording, established UI/code patterns,
implementation details that don't affect behavior or contracts, formatting, obvious naming.

**Log every load-bearing assumption** in the plan/design and surface it — never bury an
assumption that, if wrong, invalidates the work.

---

## 5. Using parallel sub-agents (for Claude Code / agentic tools)

Large or cross-cutting work benefits from fan-out — use it deliberately, not by default:

- **Discovery fan-out** — multiple read-only explorers, each mapping one repo/subsystem, then one
  synthesis into the blast-radius map.
- **Parallel slices** — independent slices built concurrently (isolated worktrees) once the
  contract they share exists.
- **Adversarial review** — before handback on security-sensitive or architectural work, a
  reviewer pass whose job is to *refute* the change (find the bug, the missing authz, the broken
  contract). `/code-review ultra` is the heavyweight version for an integrated epic.

Match the fan-out to the task: a one-repo feature rarely needs it; an ecosystem epic almost
always does.
