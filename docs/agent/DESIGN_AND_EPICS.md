# Design Gate & Epic Playbook — KriegerDataForge

Kept byte-identical across every KDF repo by the kit-sync engine. This is the deep-dive behind the **Epic lane**
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

- **Repos & their visions** — which repos are affected, and in what order? **For each, open its
  `AGENTS.md` and read its Vision & purpose and Critical rules *before* designing — not just the
  repo you started in. Your design must serve every touched repo's vision and break none of its
  rules.** If two repos' visions or rules pull in different directions, surface it to the owner.
- **Prior decisions** — scan `kriegerdataforge/docs/epics/` for an in-flight epic that overlaps your
  blast radius, and each touched repo's `docs/CHANGELOG_AND_DECISION_LOG.md` for ADRs you must
  respect or explicitly supersede. Coordinate with what exists; don't design in a vacuum.
- **Contracts** — which API endpoints / OpenAPI schemas / SDK surfaces change?
- **Data** — which tables/migrations? Is the migration backward-compatible (expand/contract)?
- **Identity** — does it touch `KDFUser`, JWT claims, scopes, or the per-client OIDC audience? Does it
  need to *display other users* (a leaderboard, social, mentions)? That can't be a per-app user table —
  it needs the **hub's read-only public-profile endpoint** (see the contract-ownership map), an
  auth-adjacent change that leads the sequence and carries a design note.
- **Config / secrets** — new env vars or secrets? (Then Terraform + the secrets inventory move too.)
- **User surfaces** — which screens/flows; what's the flag and the rollout?
- **Unknowns & assumptions** — list them explicitly; resolve the load-bearing ones with the owner.

> Use **parallel sub-agents** here (if your tool supports them): fan out read-only explorers across
> the affected repos/modules and synthesize one blast-radius map — each explorer **capturing its
> repo's vision + critical rules, not only its code structure**. No sub-agents? Read serially —
> but never skip the per-repo vision reads.

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
[`templates/adr-entry.template.md`](templates/adr-entry.template.md): the next id (continue the
repo's existing scheme if its log already uses one — e.g. `ADR-NNN` — otherwise `D-NNN`), context,
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

**Define each contract in the repo that owns it, then regenerate/extend its consumers.** There are
two contract types with two different owners — don't conflate them:

- **Auth / identity** (the JWT, `KDFUser`, claims, scopes, per-client audience) is owned by
  **`kriegerdataforge-sdk`**. Touch an SDK slice **only** when *this* contract changes — then it
  lands before the backends that depend on it.
- **A per-app API** is owned by **that app's own backend**; its frontend consumes it through an
  **OpenAPI-generated client**. The SDK is **not** in this path.

Typical ordering for a per-app feature (no auth-contract change):

```text
1. Backend: schema + migration (expand) + endpoint, behind a flag   (fitness-app-backend)
2. Contract: regenerate the typed client from the backend's OpenAPI
   (fitness-app-backend: make openapi  →  fitness-app-frontend: make generate-client)
3. Consumer/frontend: build on the generated client, behind the flag (fitness-app-frontend)
4. Infra: env vars / secrets / flags wired                          (kriegerdataforge-terraform)
5. Enable the flag; end-to-end verify; contract (cleanup) migration
```

The generated client is **read-only — never hand-edit it; regenerate.** Never build a consumer
against a contract that doesn't exist yet: backend + contract land first.

### 3.3 Feature flags — shipping dark in KDF

Every slice ships behind a flag, **off by default**, so `main` stays releasable. KDF's default is a
**simple, owned flag — no framework**:

- **A backend feature** is gated by a default-off boolean in the owning backend's settings — a Pydantic
  `Settings` field (e.g. `FEATURE_<NAME>_ENABLED: bool = False`), the same pattern `fitness-app-backend`
  already uses for its `reports` config. The endpoint short-circuits (404 / empty) while off.
- **A frontend-only feature** is a default-off `NEXT_PUBLIC_<NAME>_ENABLED`, read through the repo's
  **`serverEnv` / `publicEnv` schema** — never bare `process.env` (build-inlining drops runtime values).
- **A backend flag the frontend must observe** is *not* hand-read (the generated client is read-only):
  the backend exposes a small `GET /config/flags`-style endpoint, the frontend consumes it through the
  **regenerated client** and gates on it. The epic tracker's `Flag:` field is the owning backend's flag
  name; the frontend keys off the same name.
- **Enabling** flips the value in infra (`kriegerdataforge-terraform`) as the **last** slice — an
  owner-merged change, never an agent one.

That covers ship-dark for almost every epic. **Richer rollout — per-user / percentage / cohort, remote
kill-switches, A/B — is out of scope for this convention.** If a slice seems to need it, **stop and
surface it to the owner as a design decision** before building — don't hand-roll per-user flag logic.

### 3.4 Create the epic tracker (in the hub)

For any multi-repo epic, create **one** coordinating tracker in the ecosystem hub:
`kriegerdataforge/docs/epics/<name>.md` (template:
[`templates/epic-tracker.template.md`](templates/epic-tracker.template.md)). It holds the
blast-radius map, the slice list with a **status grid** (slice → repo → PR → state), the PR
ordering, the flag name, and links to the design doc + ADRs. Every slice PR in every repo links
back to this tracker; the tracker is updated as each slice lands. It is the single source of
truth for "where is this epic."

### 3.5 Execute & integrate

Run each slice through the Standard lane (plan → `make ci` → PR → green CI). Keep the tracker
current. When all slices are merged: the **agent** verifies on the local/preview stack with the flag
forced on (some repos — e.g. `kriegerdataforge-auth-ui` — aren't in the local compose; verify those
against a preview deploy) and does a final review (consider **`/code-review ultra`** on the integrated
result). The **owner** merges the infra slice that enables the production flag and authorizes the
production cross-repo check. Record the outcome in the decision log and mark the epic complete.

> **Parallelism:** independent slices in different repos can be built concurrently (separate
> sub-agents / git worktrees). Slices with a contract dependency must respect the order above.

---

## 4. Clarification heuristic — when to ask vs. proceed

**Always ask first** (strategic/ambiguous): target users & problem, success criteria, priority,
must-have vs nice-to-have, anything architectural/destructive/irreversible, anything touching
auth/identity/money, where a new cross-repo contract should live, **a conflict between two touched
repos' visions or critical rules** (never resolve it silently — the owner decides).

**Proceed without asking** (and note it): standard error wording, established UI/code patterns,
implementation details that don't affect behavior or contracts, formatting, obvious naming.

**Log every load-bearing assumption** in the plan/design and surface it — never bury an
assumption that, if wrong, invalidates the work.

---

## 5. Parallelism & adversarial review (tool-agnostic)

Large or cross-cutting work benefits from fan-out and a refutation pass. The **requirements** below
hold for any agent; the **mechanisms** are optional and depend on your tooling.

- **Discovery fan-out** — map the blast radius with read-only explorers, each covering one
  repo/subsystem and **reading its `AGENTS.md` vision + critical rules**, then synthesize one map.
  No sub-agents in your tool? Read the repos serially — don't skip the vision reads.
- **Parallel slices** — independent slices (no shared-contract dependency) may be built
  concurrently if your tool supports isolated worktrees; otherwise build them in sequence.
- **Adversarial review (required on security-sensitive or architectural work)** — before handback,
  do a pass whose only job is to *refute* the change: find the bug, the missing authz, the broken
  contract, the violated repo rule. If your tool supports it, `/code-review ultra` or parallel
  reviewer sub-agents are the heavyweight version; **otherwise do this refutation pass yourself,
  manually.** The review is mandatory; the slash command is not.

Match the fan-out to the task: a one-repo feature rarely needs it; an ecosystem epic almost always
does.
