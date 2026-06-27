# Standard Workflow — KriegerDataForge

Vendored **byte-identical** across every KriegerDataForge repo. The loop is the same
everywhere; the repo-specific detail (vision, stack, commands, required reading) lives in
[`AGENTS.md`](./AGENTS.md). Read `AGENTS.md` first, then follow this.

> **The one rule that matters most:** match the ceremony to the work. Don't over-process a
> typo; don't under-plan a system. Everything below is about doing that well.

---

## Step 0 — Pick your lane

| Lane | Use when | Shape |
| --- | --- | --- |
| **Quick** | ≤ ~1 file, **no** behavior / API-contract / schema / security change (typo, copy, comment, log line, isolated bug-fix) | implement → `make ci` → PR |
| **Standard** | A feature or fix contained in **one** repo | the 6-step loop below |
| **Epic** | Complex or novel design (e.g. *designing an auth system*) **or** anything that spans **more than one repo** (e.g. *gamification across fitness-fe + fitness-be + sdk*) | the **Epic track** below |

**When unsure, size up one lane, not down.** If a Quick change turns out to touch behavior
or a contract, stop and restart as Standard. If a Standard feature turns out to need a new
schema in another repo, stop and restart as an Epic. Mis-sizing down is the most common and
most expensive mistake.

---

## Quick lane

Implement → `make ci` **green** → bump version → branch → PR (say *what* and *why*) →
confirm GitHub CI green → hand back. No formal plan needed. The moment it stops being a
1-file no-behavior change, switch to Standard.

---

## Standard lane — the core loop

### 1. Orient

Read [`AGENTS.md`](./AGENTS.md) — its **Vision & purpose** tells you what this product is and
the goal the owner is striving for; its **Required reading** points you at the README and the
docs that explain the architecture and conventions. Read those before writing code. For
security-relevant work, read [`skills.md`](./skills.md) and follow the matching scenario.
**If you don't understand the purpose or how your task fits the goal, stop and ask.**

### 2. Plan — and get it approved

Produce a specific plan: what changes, which files, why, how you'll verify it, and the
assumptions you're making. **Share it and wait for the owner's approval before implementing.**
Pause and ask first for anything architectural, destructive, behavior-changing, or touching
OIDC/auth protocol — those need explicit sign-off (and OIDC/token changes get a short design
note first; see [`docs/agent/DESIGN_AND_EPICS.md`](docs/agent/DESIGN_AND_EPICS.md)). Use the
[`prompts/`](./prompts) scaffolds (`architect/`, `design/`, `dev/`) to structure the plan. When
the design is non-trivial, **the plan IS a design doc** — go through the design gate (Step 2 of
the Epic track) even if the work stays in one repo.

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
`bump-major`); some repos need a follow-up sync (the auth service: `make vercel-compact`) —
`AGENTS.md` calls these out. Stage files **explicitly**; never `git add -A`. Confirm your change
meets [`docs/agent/DEFINITION_OF_DONE.md`](docs/agent/DEFINITION_OF_DONE.md) for its change type.

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
   user surface the change touches. Surface unknowns and assumptions explicitly. Use parallel
   sub-agents to read across the affected areas in one pass.
2. **Design & ADR** — write a **design doc** (template:
   [`docs/agent/templates/design-spec.template.md`](docs/agent/templates/design-spec.template.md))
   and record the decision as an **ADR** (`D-NNN` in `docs/CHANGELOG_AND_DECISION_LOG.md` —
   create that file if your repo doesn't have one yet).
   **The owner approves the design before any code is written.**
3. **Decompose** — break the work into **flag-gated vertical slices**, each independently
   shippable and reviewable. Ship dark behind a feature flag; enable last.
4. **Sequence — contract-first** — order slices by dependency: define the API/data **contract
   first** (backend schema → regenerate/extend the SDK/client → consumer/frontend). Create the
   **epic tracker** in the hub: `kriegerdataforge/docs/epics/<name>.md` (template:
   [`docs/agent/templates/epic-tracker.template.md`](docs/agent/templates/epic-tracker.template.md)).
5. **Execute slices** — run **each slice through the Standard lane** as its own PR in its own
   repo, linked back to the epic tracker. Update the tracker's status grid as each slice lands.
6. **Integrate & verify** — enable the flag, run an end-to-end check across repos, do a final
   review (consider **`/code-review ultra`**), update the decision log, and close the epic.

---

## Always — non-negotiables

- **Plan-approval gate** for Standard and Epic; **design+ADR gate** before complex/architectural
  builds. Don't skip them.
- **Pause and ask** before anything architectural, destructive, behavior-changing, or
  OIDC/auth-protocol-related — an OK in one place doesn't extend to the next.
- **Secrets never touch git or logs** — real values only in gitignored files; the owner rotates.
- **Local `make ci` green before push;** **GitHub CI green before handback;** **owner merges, never you.**
- **Definition of Done** ([`docs/agent/DEFINITION_OF_DONE.md`](docs/agent/DEFINITION_OF_DONE.md))
  scales with the change: tests by type, docs + decision-log entry for architectural changes,
  migration + rollback for data changes, the relevant [`skills.md`](./skills.md) scenario for
  security-relevant changes.
