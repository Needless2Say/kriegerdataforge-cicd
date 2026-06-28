# Standard Workflow — KriegerDataForge

The canonical source is `kriegerdataforge-cicd/kit/common/`; the kit-sync engine keeps this file
**byte-identical** across every KriegerDataForge repo (drift is flagged weekly and re-synced). The
loop is the same everywhere; the repo-specific detail (vision, stack, commands, required reading)
lives in [`AGENTS.md`](./AGENTS.md). Read `AGENTS.md` first, then follow this.

New here, or want the *why* behind these rules? Read
[`docs/agent/AGENT_OPERATING_STANDARD.md`](docs/agent/AGENT_OPERATING_STANDARD.md) once — the whole
standard explained end to end, with worked examples from a one-line fix to an ecosystem-spanning epic.

> **The one rule that matters most:** match the ceremony to the work. Don't over-process a
> typo; don't under-plan a system. Everything below is about doing that well.
>
> **Aim high, then ship it safely.** Reach for the *best* solution the product's vision
> deserves — not the smallest patch that closes the ticket. Be **unrestricted in what you
> propose**; be **disciplined in how you land it** (approved plan, fail-closed, least privilege,
> owner merges). The gates below constrain *how you ship*, never *how big you think*. When you
> see a design better than the task asked for, put it in the plan **as a proposal** — don't
> shrink it, and don't smuggle it silently into the diff.

---

## Step 0 — Pick your lane

| Lane | Use when | Shape |
| --- | --- | --- |
| **Quick** | ≤ ~1 file, **no** API-contract / schema / security change — a typo, copy, comment, log line, or a bug-fix with **one obviously-correct outcome**. If the *intended behavior* is itself a judgment call, size up to Standard. | implement → `make ci` → PR |
| **Standard** | A feature or fix contained in **one** repo | the 6-step loop below |
| **Epic** | Complex or novel design (e.g. *designing an auth system*) **or** anything that spans **more than one repo** (e.g. *gamification across fitness-fe + fitness-be + sdk*) | the **Epic track** below |

**When unsure, size up one lane, not down.** If a Quick change turns out to touch behavior
or a contract, stop and restart as Standard. If a Standard feature turns out to need a new
schema in another repo, stop and restart as an Epic. Mis-sizing down is the most common and
most expensive mistake.

---

## Quick lane

Implement → `make ci` **green** (plus any repo-mandatory post-build sync — `AGENTS.md` calls these
out, e.g. `make vercel-compact` after an `api/` change) → bump version → branch → PR (say *what* and
*why*) → confirm GitHub CI green → hand back. No formal plan needed. The moment it stops being a
1-file no-behavior change, switch to Standard.

---

## Standard lane — the core loop

### 1. Orient

Read [`AGENTS.md`](./AGENTS.md) — its **Vision & purpose** tells you what this product is and
the goal the owner is striving for; its **Required reading** points you at the README and the
docs that explain the architecture and conventions. Read those before writing code. For
security-relevant work, read [`skills.md`](./skills.md) and follow the matching scenario.
**If you don't understand the purpose or how your task fits the goal, stop and ask.**

### 2. Plan — sized to the change

Produce a specific plan: what changes, which files, why, how you'll verify it, and the
assumptions you're making. **Calibrate the approval to the work:**

- **Architectural, destructive, behavior-changing, schema/contract-touching, or OIDC/auth-protocol
  work** → share the plan and **wait for the owner's explicit approval before implementing**
  (OIDC/token changes get a short design note first; see
  [`docs/agent/DESIGN_AND_EPICS.md`](docs/agent/DESIGN_AND_EPICS.md)).
- **A small, in-pattern change with no behavior / contract / schema / security surface** → a 2–3
  line plan is enough: share it, note any assumptions, and you may proceed.

When the design is non-trivial, **the plan IS a design doc** — go through the design gate (Step 2
of the Epic track) even if the work stays in one repo.

### 3. Implement

Build exactly the approved plan. Match the surrounding code's conventions, naming, and
structure. Keep it scoped — note adjacent work for the owner, don't silently expand. The
**server is authoritative**: recompute security/$-relevant values, never trust client input.

### 4. Verify locally — `make ci` must pass

Run the full local gate and make it **green before you push**:

```bash
make ci
```

`make help` lists targets; a few repos use a stricter gate (e.g. `make ci-strict`) — check the
Makefile. Then bump the version with the repo's script (`make bump-patch` / `bump-minor` /
`bump-major`) — **pick the level by impact:** no behavior/contract change → patch; a
backward-compatible feature or additive contract → minor; a breaking API/schema/contract change →
major. (The CI version check only verifies the version is consistent across files and strictly ahead
of `main` — it does **not** police your level choice; that judgment is yours.) Some repos need a
follow-up sync (the auth service: `make vercel-compact`) — `AGENTS.md` calls these out. Stage files
**explicitly**; never `git add -A`. Confirm your change meets
[`docs/agent/DEFINITION_OF_DONE.md`](docs/agent/DEFINITION_OF_DONE.md) for its change type.

### 5. Branch, commit, PR, push

Feature branch off `main` (never commit to `main`): `{type}/{short-description}`. Conventional
Commit messages. **Self-review your own diff first** — read it as a reviewer would. Open a PR
against `main` with what changed and how you verified it, filling in the PR template. **Never
put secrets in code, commits, or logs.**

### 6. Wait for GitHub CI — then hand back

```bash
gh pr checks <pr-number> --watch
```

If anything is red, fix locally (back to Step 4) and push again. When every check is green,
report the PR link + green status to the owner. **The owner merges — never self-merge.**

---

## Epic lane — complex design, or spans more than one repo

Do **not** open a single mega-PR. An Epic is planned once, then executed as a series of small
Standard-lane PRs. Full detail: [`docs/agent/DESIGN_AND_EPICS.md`](docs/agent/DESIGN_AND_EPICS.md).

1. **Discovery** — map the **blast radius**: every repo, module, contract, table, env var, and
   user surface the change touches. **For every repo in that blast radius, open its `AGENTS.md`
   and read its Vision & purpose and Critical rules *before* you design — not just the repo you
   started in. Your design must honor each touched repo's vision and break none of its rules; if
   two repos' visions or rules conflict, surface it to the owner instead of choosing for them.**
   Scan the hub's `kriegerdataforge/docs/epics/` for an in-flight epic that overlaps yours, and
   the touched repos' `docs/CHANGELOG_AND_DECISION_LOG.md` for ADRs you must respect or supersede.
   Surface unknowns and assumptions explicitly. Use parallel sub-agents (if your tool supports
   them) to read across the affected areas in one pass — capturing each repo's vision and rules,
   not just its code.
2. **Design & ADR** — write a **design doc** (template:
   [`docs/agent/templates/design-spec.template.md`](docs/agent/templates/design-spec.template.md))
   and record the decision as an **ADR** (`D-NNN` in `docs/CHANGELOG_AND_DECISION_LOG.md` —
   create that file if your repo doesn't have one yet).
   **The owner approves the design before any code is written.**
3. **Decompose** — break the work into **flag-gated vertical slices**, each independently
   shippable and reviewable. Ship dark behind a feature flag; enable last.
4. **Sequence — contract-first** — order slices by dependency: **define each contract in the repo
   that owns it, then regenerate/extend its consumers.** Identity/JWT lives in
   `kriegerdataforge-sdk`; a *per-app* API contract lives in **that app's own backend** and reaches
   its frontend through an OpenAPI-generated client (e.g. `fitness-app-backend: make openapi` →
   `fitness-app-frontend: make generate-client`) — the SDK is **not** in that path unless the
   auth/JWT contract itself changes. Never build a consumer against a contract that doesn't exist
   yet. Create the **epic tracker** in the hub: `kriegerdataforge/docs/epics/<name>.md` (template:
   [`docs/agent/templates/epic-tracker.template.md`](docs/agent/templates/epic-tracker.template.md)).
5. **Execute slices** — run **each slice through the Standard lane** as its own PR in its own
   repo, linked back to the epic tracker. Update the tracker's status grid as each slice lands.
6. **Integrate & verify** — the **agent** verifies each slice on the local/preview stack with the
   flag forced on (some repos, e.g. `kriegerdataforge-auth-ui`, aren't in the local compose — verify
   those against a preview deploy or standalone) and does a final review (consider
   **`/code-review ultra`**). The **owner** merges the infra/flag-wiring slice that enables the
   production flag and authorizes the production cross-repo check; then update the decision log and
   close the epic.

---

## Always — non-negotiables

- **Plan-approval gate** before anything behavior-, contract-, schema-, security-, or auth-touching
  (and for every Epic); **design+ADR gate** before complex/architectural builds. A small in-pattern
  change *with no behavior/contract/schema/security surface* needs only a shared 2–3 line plan. Don't
  skip the gate where it applies.
- **Honor the vision of every repo you touch** — read each touched repo's `AGENTS.md` before
  designing; surface conflicting visions to the owner, never resolve them silently.
- **Pause and ask** before anything architectural, destructive, behavior-changing, or
  OIDC/auth-protocol-related — an OK in one place doesn't extend to the next.
- **Secrets never touch git or logs** — real values only in gitignored files; the owner rotates.
- **Local `make ci` green before push;** **GitHub CI green before handback;** **owner merges, never you.**
- **Definition of Done** ([`docs/agent/DEFINITION_OF_DONE.md`](docs/agent/DEFINITION_OF_DONE.md))
  scales with the change: tests by type, docs + decision-log entry for architectural changes,
  migration + rollback for data changes, the relevant [`skills.md`](./skills.md) scenario for
  security-relevant changes.
