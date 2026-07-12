# The KriegerDataForge AI Agent Operating Standard

> The kit-sync engine keeps this doc **byte-identical** across every KriegerDataForge (KDF) repo. This is the human-readable
> *why* and *how it all fits* behind the operational files. Read it once to understand the standard;
> use [`../../WORKFLOW.md`](../../WORKFLOW.md) day to day. If anything here and an operational file
> ever disagree, the operational file wins and this doc is the bug — fix it in the canonical source
> (`kriegerdataforge-cicd/kit/common/`).

## Who this is for

- **The owner**, prompting an AI model to build something — small or ecosystem-spanning.
- **Other developers**, reviewing agent-authored PRs and needing to know the bar they're held to.
- **The agents themselves** (Claude, Cursor, Copilot, Gemini, GPT — any tool), as the orientation
  layer above the step-by-step workflow.

## The standard in one breath

One canonical guide per repo (`AGENTS.md`), one shared workflow (`WORKFLOW.md`), **three lanes
chosen by scale**, *design-before-code* for anything big or novel, large work shipped as **many
small feature-flagged PRs** (never one mega-PR), every touched repo's **vision honored**, and **the
owner merges** — always.

---

## The five principles

1. **Match ceremony to scale.** A typo is not a system; a system is not a typo. The lane you pick
   should fit the work — and when unsure, *size up one lane, not down* (under-sizing is the most
   expensive mistake).
2. **Vision first — every repo you touch.** Before designing, read the **Vision & purpose** and
   **Critical rules** in the `AGENTS.md` of *every* repo in the blast radius, not just the one you
   started in. A change that's locally sensible can still violate another product's vision. If two
   repos' visions conflict, surface it to the owner — never resolve it silently.
3. **Aim high, then ship it safely.** Reach for the *best* solution the vision deserves, not the
   smallest patch that closes the ticket. Be **unrestricted in what you propose**; be **disciplined
   in how you land it**. The gates constrain *how you ship*, never *how big you think*. A better
   idea than the task asked for goes in the **plan as a proposal** — never silently into the diff.
4. **Design before code; big work is many small flag-gated PRs.** Anything complex, novel, or
   cross-repo goes through the **design gate** (design doc + ADR, owner-approved) and is then
   executed as a sequence of independently-shippable vertical slices, each behind a feature flag, so
   `main` stays releasable the whole time.
5. **Fail closed; the owner merges.** The server is authoritative, least privilege is the default,
   secrets never touch git or logs — and no agent ever merges its own work. CI green is *necessary*,
   not *sufficient*; the [Definition of Done](DEFINITION_OF_DONE.md) is the real bar.

---

## How an agent enters a repo (works for any tool)

Every repo carries the same entry contract. Whatever tool opens the repo, the reading order is:

1. **The tool's pointer file** — `CLAUDE.md`, `.cursorrules`, or `.github/copilot-instructions.md`.
   Each is thin and routes to `AGENTS.md`.
2. **`AGENTS.md`** — the canonical guide: this repo's **Vision & purpose**, tech stack, module map,
   **Critical rules**, **Required reading**, and commands. *Read it first.*
3. **`AGENTS.md` → Required reading** — the README and the `docs/` that explain architecture and
   conventions. Read these before writing code.
4. **[`WORKFLOW.md`](../../WORKFLOW.md)** — pick a lane and follow the loop.
5. **[`skills.md`](../../skills.md)** — before any security-relevant work, follow the matching
   scenario. This is non-optional for auth/OIDC/tokens, BFF/proxy/CSP/cookies, backend authz,
   secrets/config, Terraform/infra, CI/CD, or dependency changes.

If you don't understand the product's purpose or how your task serves it, **stop and ask** before
writing code.

---

## The three lanes (choose by scale)

| Lane | Use when | Shape |
| --- | --- | --- |
| **Quick** | ≤ ~1 file, no API-contract / schema / security change — a typo, copy, comment, log line, or a bug-fix with one obviously-correct outcome (if the intended behavior is itself a judgment call, size up to Standard) | implement → `make ci` → PR |
| **Standard** | A feature or fix contained in **one** repo | plan (sized to the change) → approve → implement → `make ci` → PR → CI green → handback |
| **Epic** | Complex/novel design, **or** anything spanning **more than one repo** | the Epic track: discovery → design + ADR → decompose → contract-first → hub tracker → slices → integrate |

The full step-by-step lives in [`WORKFLOW.md`](../../WORKFLOW.md); the design gate and Epic playbook
in [`DESIGN_AND_EPICS.md`](DESIGN_AND_EPICS.md). **When unsure, size up.**

---

## The lifecycle by scale — worked examples

### A. Small — a one-line fix (Quick lane)

> *"The dashboard logs `userId` in camelCase; our convention is `user_id`. Fix it."*

One file, no behavior/contract/schema/security surface, one obviously-correct outcome → **Quick**.
The agent edits the line, runs `make ci` to green, bumps the version, opens a branch + PR saying
*what* and *why*, confirms GitHub CI is green, and hands back. No formal plan. The moment it stops
being a one-file no-behavior change, it switches to Standard.

### B. Medium — a one-repo feature (Standard lane)

> *"Add a 'last active' timestamp to the user settings page in the fitness app frontend."*

Contained in `fitness-app-frontend`, no new cross-repo contract → **Standard**. The agent **orients**
(reads `AGENTS.md` vision + the relevant `docs/`), writes a **plan sized to the change** and shares
it (a small in-pattern change needs only a 2–3 line plan; anything behavior/contract/schema/auth
waits for explicit approval), **implements** exactly the approved plan, gets **`make ci` green**,
bumps the version, opens a PR against the [Definition of Done](DEFINITION_OF_DONE.md), waits for
**GitHub CI green**, and hands the PR to the owner to merge.

### C. Extreme — a system across several repos (Epic lane)

> *"Build a gamification system that touches everything in the fitness app — points, streaks,
> badges, a leaderboard — across the backend, the shared SDK if needed, the frontend, and infra."*

This spans repos → **Epic**. It runs as **one planned arc, executed as many small PRs** — never a
mega-PR:

1. **Discovery — map the blast radius *and read every touched repo's vision.*** The agent enumerates
   the repos (`fitness-app-backend`, `fitness-app-frontend`, maybe `kriegerdataforge-terraform`,
   and — *only if the auth contract changes* — `kriegerdataforge-sdk`), the contracts, the tables,
   the env vars, and the user surfaces. **Crucially**, it opens each repo's `AGENTS.md` and reads its
   **Vision & purpose** and **Critical rules first**. That's what catches, for example, that a
   gamification `points` table in the fitness DB must use a **plain `user_id` column from the verified
   JWT — never a cross-DB foreign key to `kdf_users`** (the identity-decoupling rule), and that the
   frontend's generated API client is **read-only**. It also catches that the **leaderboard** must
   render *other* users' names/avatars — data the tenant DB can't own — so it needs the **hub's
   read-only public-profile lookup** (contract map, row 4), an auth-adjacent contract that leads the
   sequence and carries a design note. It also scans `kriegerdataforge/docs/epics/` for an overlapping
   epic and the touched repos' decision logs for ADRs to respect.
2. **Design + ADR — approved before any code.** The agent writes a design doc
   ([`templates/design-spec.template.md`](templates/design-spec.template.md)) — including the
   **per-repo vision table** (each repo, its vision, its rules, how the design honors them) — and
   records the decision as an ADR (`D-NNN`) in the repo's `docs/CHANGELOG_AND_DECISION_LOG.md`. **The
   owner approves the design before a line of code is written.**
3. **Decompose into flag-gated vertical slices.** Each slice is a thin end-to-end path, independently
   shippable and reviewable, shipped **dark behind a feature flag** (off by default) so `main` stays
   releasable throughout.
4. **Sequence contract-first.** The contract is defined in the repo that **owns** it, then its
   consumers regenerate. For gamification that's `fitness-app-backend` (schema + endpoint) →
   regenerate the typed client (`make openapi` → frontend `make generate-client`) →
   `fitness-app-frontend` builds on it → infra wires the flag. The agent creates **one epic tracker**
   in the hub (`kriegerdataforge/docs/epics/gamification.md`,
   [`templates/epic-tracker.template.md`](templates/epic-tracker.template.md)) as the single source
   of truth; every slice PR in every repo links back to it.
5. **Execute slices** — each runs through the Standard lane as its own PR in its own repo, with the
   tracker's status grid updated as each lands.
6. **Integrate & verify** — enable the flag, run an end-to-end check across the repos, do an
   adversarial review, record the outcome in the decision log, and close the epic.

### D. Reference epic — the authentication / OIDC system

The ecosystem's auth system is the canonical example of this pattern done for real: the **hub**
(`kriegerdataforge`) is the OIDC/identity provider; the **SDK** (`kriegerdataforge-sdk`) carries the
stateless RS256 JWT-verification contract every tenant backend depends on; each app's **BFF/proxy**
brokers the OIDC flow; and changes ripple **contract-first** (hub issues → SDK verifies → apps
consume) behind backward-compatible transitions. Auth/OIDC/token work *always* carries a protocol
design note and follows the matching [`skills.md`](../../skills.md) scenario, because a regression in
the hub or SDK breaks **every** downstream product at once. When in doubt on anything auth-shaped,
treat it as an Epic with a design gate.

---

## Who owns which contract (the map)

Getting this right is what keeps cross-repo work coherent. **Define each contract in the repo that
owns it, then regenerate/extend its consumers:**

| Contract | Owned by | Consumed how |
| --- | --- | --- |
| **Identity / auth** — the JWT, `KDFUser`, claims, scopes, per-client audience | `kriegerdataforge-sdk` (verification) + the **hub** (issuance) | every tenant backend verifies via the SDK; touch the SDK slice **only** when this contract changes |
| **A per-app API** — endpoints + request/response schemas | that **app's own backend** | its frontend consumes a **read-only OpenAPI-generated client** (`make openapi` → `make generate-client`); the SDK is **not** in this path |
| **The user/identity store** | the **hub** (`kdf_users`) | tenant app DBs reference identity by a **plain `user_id` column from the verified JWT — no cross-DB FK**, no per-app user table |
| **Other users' public profile** — display name / avatar for leaderboards, social, mentions | the **hub** (`kriegerdataforge`) | tenant backends resolve arbitrary `user_id`s via a **hub-owned read-only batch endpoint** (e.g. `GET /users/public?ids=…`) returning display fields only — **never** a per-app user table or cross-DB FK. It's a hub contract change, so it leads the contract-first sequence and carries a design note |

The single most common cross-repo mistake is treating the SDK as the carrier for a *per-app* API
contract. It isn't — the SDK is auth-only.

---

## The artifacts (what each file is)

| File | What it is | When you touch it |
| --- | --- | --- |
| `AGENTS.md` | Per-repo canonical guide: vision, stack, rules, required reading | Read first, every task; it's per-repo and never synced |
| [`WORKFLOW.md`](../../WORKFLOW.md) | The shared three-lane loop | Every task |
| [`DESIGN_AND_EPICS.md`](DESIGN_AND_EPICS.md) | Design gate + cross-repo Epic playbook + clarification heuristic | Anything complex/novel/cross-repo |
| [`DEFINITION_OF_DONE.md`](DEFINITION_OF_DONE.md) | The real bar, scaled by change type | Before opening any PR |
| [`skills.md`](../../skills.md) | Scenario-indexed security playbook | Before any security-relevant work |
| [`DOCUMENTATION_STANDARD.md`](DOCUMENTATION_STANDARD.md) | How repo docs are organized, kept honest, and kept discoverable | Any documentation work |
| [`templates/`](templates/) | Copy-paste design-spec, ADR, epic-tracker, and contributor-onboarding templates | When the design gate, an Epic, or a new repo's onboarding applies |
| `docs/guides/CONTRIBUTOR_ONBOARDING.md` | Per-repo human setup path (from the kit template) | Per-repo and never synced; update when commands/env change |
| `docs/prompts/` | Per-repo documentation-authoring toolkit (tailored; the static portfolios don't carry one) | When authoring docs; per-repo and never synced |
| `kriegerdataforge/docs/epics/<name>.md` | One coordinating tracker per cross-repo epic (in the hub) | Any multi-repo Epic |
| `docs/CHANGELOG_AND_DECISION_LOG.md` | Append-only ADR (`D-NNN`) home, per repo | Architectural decisions |

---

## How the standard is maintained (the kit + engine)

This whole standard — `WORKFLOW.md`, `DESIGN_AND_EPICS.md`, `DEFINITION_OF_DONE.md`,
`DOCUMENTATION_STANDARD.md`, the templates, `skills.md`, and this doc — is the **agentic-workflow kit**. Its single source of truth is
`kriegerdataforge-cicd/kit/common/`. A registry-driven sync engine (`scripts/distribute_kit.py`,
driven by `scripts/kit_registry.json`) propagates the kit to every repo as **owner-reviewed PRs**
(never auto-merged), a weekly job alarms on drift, and new repos are seeded from the four
`kriegerdataforge-template-*` repos. To change the standard: edit the canonical copy in
`kit/common/`, bump **both** `kit/KIT_VERSION` and the vendored marker
`kit/common/docs/agent/KIT_VERSION` (the engine refuses to run if they disagree), and run the
**Distribute** workflow. **Never hand-edit a
synced kit file in a downstream repo** — your change will be reported as drift and overwritten;
change the source instead.

---

## How to prompt an agent well (for the owner & developers)

The standard does a lot, but a good prompt makes it sing:

- **State the goal and the *why*, not just the change.** "Add streaks because retention is the
  Q3 priority" lets the agent design toward the vision; "add a streaks column" doesn't.
- **Name the scale or let it size up.** If you know it spans repos, say so. If you're unsure, the
  agent will size up to an Epic and show you a plan — that's the safe default.
- **Name the repos you know are involved** — but trust the discovery step to find the rest and read
  their visions.
- **Expect a plan before code** on anything non-trivial. Review the plan: that's where you steer the
  ambition and catch a wrong direction cheaply. Approving the plan is the highest-leverage thing you
  do.
- **You merge.** Every PR comes back to you green; nothing self-merges. Review against the
  [Definition of Done](DEFINITION_OF_DONE.md).
- **"No restrictions" means on ambition, not on safety.** Tell the agent to aim high; it will still
  fail closed, keep secrets out of git, and pause on anything architectural, destructive, or
  auth-shaped.

---

## Glossary

- **Blast radius** — every repo, contract, table, env var, and user surface a change touches; mapped
  in Discovery before designing.
- **Vertical slice** — a thin end-to-end piece of a feature that is independently shippable and
  reviewable; the unit of work in an Epic.
- **Contract-first** — define the API/data contract in the repo that owns it *before* building any
  consumer of it.
- **Flag-gated / ship dark** — merged behind a feature flag that's off by default, so `main` stays
  releasable until the feature is enabled last.
- **Expand / contract migration** — a backward-compatible schema change: add the new shape (expand),
  migrate, then remove the old shape (contract) — `main` works against both at every step.
- **`KDFUser`** — the verified identity principal the SDK returns from a valid JWT; `user.user_id`
  (int), never `user.id`.
- **Hub** — `kriegerdataforge`, the ecosystem's OIDC/identity platform and the home of `kdf_users`
  and the epic trackers.
- **Tenant app** — a product built on the platform (fitness, tiffanys, …); its DB references identity
  by a plain `user_id` column, never a cross-DB FK.
- **BFF / proxy** — the backend-for-frontend layer in a Next.js app that brokers the OIDC flow and
  keeps server-only secrets server-only.
- **The kit** — the byte-identical agentic-workflow markdown synced across all repos from
  `kriegerdataforge-cicd/kit/common/`.
- **Epic tracker** — the single coordinating doc for a cross-repo epic, in `kriegerdataforge/docs/epics/`.
- **ADR (`D-NNN`)** — an append-only Architecture Decision Record in a repo's
  `docs/CHANGELOG_AND_DECISION_LOG.md`.
