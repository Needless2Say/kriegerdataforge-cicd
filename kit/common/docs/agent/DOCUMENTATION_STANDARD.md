# Documentation Standard — KriegerDataForge

Kept byte-identical across every KDF repo by the kit-sync engine. This is how a repo's
documentation is **organized, kept honest, and kept discoverable**. The instances it governs —
the `README.md`, everything under `docs/` **except the kit-synced kit files in `docs/agent/`**,
the `docs/prompts/` toolkit, and `docs/guides/CONTRIBUTOR_ONBOARDING.md` — are **per-repo and
never synced**; this standard is what they all follow. To change the standard itself, edit the
canonical copy in `kriegerdataforge-cicd/kit/common/` (see
[`AGENT_OPERATING_STANDARD.md`](AGENT_OPERATING_STANDARD.md) → *How the standard is maintained*).

> **Why this exists:** in this ecosystem, agents author most documentation — and agents *trust
> what they find*. A wrong or stale doc fails open: it silently steers every future task that
> reads it. These rules exist so that what a doc says and what the code does cannot quietly drift
> apart, and so a developer or agent entering **any** KDF repo finds the same doors in the same
> places.

---

## Ground truth & accuracy discipline

- **Code is ground truth.** Verify every claim against the actual files **before** writing it —
  never document from memory, another doc, or an older repo's pattern.
- **Cite `file:line` for load-bearing claims** in reference and feature docs (env-var read-sites,
  boot guards, endpoint gating). A citation makes staleness *detectable*; prose makes it invisible.
- **Never document phantom config.** A flag or env var the code doesn't actually read does
  nothing (Pydantic `extra="ignore"` silently drops unknown keys — see the config scenario in
  [`skills.md`](../../skills.md)). If the doc names it, the code must read it.
- **Docs update in the same PR as the behavior.** The doc that describes a changed behavior
  (README / `docs/*`) reflects reality before the PR opens — this is the Docs bullet in
  [`DEFINITION_OF_DONE.md`](DEFINITION_OF_DONE.md).
- Durable docs carry a `> **Last updated:** YYYY-MM-DD` line near the top so a reader can judge
  freshness at a glance.

---

## The docs taxonomy

Every repo uses the same `docs/` layout. Create content directories **as needed** — but never
invent a new *kind* of top-level directory silently; surface it to the owner first.

| Directory | What belongs there | Notes |
| --- | --- | --- |
| `docs/agent/` | The synced agentic-workflow kit, plus net-new repo-specific agent deep-dives (`<slug>.md`) | The **kit files** are kit-synced — never edit locally; change `kriegerdataforge-cicd/kit/common/` instead. Repo-specific deep-dives are repo-owned |
| `docs/prompts/` | The documentation-authoring prompt toolkit | Per-repo tailored (see below); the static portfolios don't carry one |
| `docs/guides/` | How-to / setup / operational walkthroughs, incl. `CONTRIBUTOR_ONBOARDING.md` | |
| `docs/reference/` | Source-verified contracts: API catalogs, configuration references, architecture | The `file:line` citation rule applies hardest here |
| `docs/features/` | One doc per implemented feature | |
| `docs/design/` | Design specs from the design gate (`{feature}.md`) | Paired with an ADR |
| `docs/security/` | Security posture, audits, threat notes | |
| `docs/code_review/` | Code-review reports (from the review prompt) | Created as needed where the repo keeps them |
| `docs/product/` | Product vision / roadmap material | Only where relevant |
| `docs/archive/` | Retired docs kept for history | See the deprecation rule below |
| `docs/epics/` | Cross-repo epic trackers | **Hub only** (`kriegerdataforge`) |
| `docs/README.md` | **The index** — one line per doc | Update it when adding any doc |
| `docs/CHANGELOG_AND_DECISION_LOG.md` | The append-only ADR (`D-NNN`) home | |

---

## The README front door

The root `README.md` is the repo's front door on GitHub — the first thing a new developer (or a
newly-spawned agent) sees. Every repo's README opens with an onboarding section as the **first
H2**, so entering any KDF repo starts the same way:

```markdown
## New here? Start with onboarding

{One paragraph: what this repo is AND its role in the KDF ecosystem — for app repos, its
SSO-client relationship to the hub: auth is delegated, tokens are verified not issued, and
where its OIDC client_id/issuer values come from.}

- **To run it locally → {the repo's local-run guide or one-command path}.**
- **To contribute changes → [`docs/guides/CONTRIBUTOR_ONBOARDING.md`](docs/guides/CONTRIBUTOR_ONBOARDING.md)**
  (branch → `make ci` green → PR → owner merges).
```

*(non-app repos — portfolios, templates, terraform, the sdk, cicd — adapt the framing: say what
"running" means there (plan/audit gates, the test suite, the CI gate itself); a template's front
door describes the repo a developer will generate from it, plus the rename checklist; a portfolio
has no SSO role.)*

Beyond the front door, the README also carries (or links, one hop away):

- an **environment-variable table** — the practical surface, with required/optional and where
  values come from (the exhaustive contract may live in `docs/reference/`),
- a **commands table** (`make` targets / npm scripts) that names only real targets,
- the tech stack and module map at whatever depth the repo warrants,
- a **documentation section** — links `docs/README.md` (the index), each `docs/*` subdirectory's
  own `README.md` (every content subdirectory carries one: a short statement of what belongs there
  and how to use it), and the agentic-workflow kit entry point (`docs/agent/` — the kit ships its
  own [`README.md`](README.md) there). A developer must be able to go from the repo front door to
  any category of documentation in two clicks.

---

## Contributor onboarding — mandatory per repo

Every repo carries `docs/guides/CONTRIBUTOR_ONBOARDING.md`: the clean-checkout → green-`make ci`
→ first-PR path for a human developer. Create it from
[`templates/contributor-onboarding.template.md`](templates/contributor-onboarding.template.md)
and keep its numbered spine so a developer can navigate any KDF repo the same way:

**Prerequisites → Clone & install → Environment & secrets → Run it locally → The gate
(`make ci` + version bump) → Module map + critical rules → Lane → plan → approve → PR →
Getting unblocked** *(sections 1–8)*.

Tailor every section's *content* to the repo; keep the *spine*. It is per-repo by design (never
synced) — when commands, env vars, or ports change, updating it is part of Done. Existing
onboarding docs predate this template — align their spine the **next time the doc is touched for
content reasons**; don't mass-rewrite owner-reviewed docs just to renumber sections.

---

## The docs/prompts authoring toolkit

Every repo with a real docs corpus carries `docs/prompts/` — self-contained prompts that direct
an agent to author one category of documentation — with the **applicable subset** of the core
prompt types plus a `README.md` index. (The static portfolios don't carry one; their docs surface
is too small to warrant it.)

| Prompt | Produces | Output location |
| --- | --- | --- |
| `FEATURE_DOCUMENTATION_PROMPT` | One implemented feature, documented | `docs/features/` |
| `AGENT_DOCUMENTATION_PROMPT` | Agent-facing repo guidance | `docs/agent/` pointers + `AGENTS.md` |
| `CODE_REVIEW_DOCUMENTATION_PROMPT` | A code-review report | `docs/code_review/` |
| `GUIDES_DOCUMENTATION_PROMPT` | A how-to guide | `docs/guides/` |
| `REFERENCE_DOCUMENTATION_PROMPT` | A source-verified reference | `docs/reference/` |
| `DESIGN_ADR_DOCUMENTATION_PROMPT` | A design doc + ADR entry | `docs/design/` + the decision log |
| `SECURITY_DOCUMENTATION_PROMPT` | Security posture docs | `docs/security/` |

- **Tailoring rule:** the H1, the *Context* paragraph, and the examples are repo-specific; the
  body (method, output contract, accuracy discipline, hard constraints) is shared across repos.
  An improvement to the shared body is an **ecosystem improvement** — flag it to the owner so all
  repos' copies advance together, rather than letting one repo's copy fork.
- **Boundary rule:** these prompts only ever create or edit **docs**. They never change product
  code, and they never touch the kit-synced **files** (the kit docs and templates in
  `docs/agent/`, `WORKFLOW.md`, `skills.md`) — net-new repo-specific deep-dives in `docs/agent/`
  are repo-owned and fair game.

---

## Deprecate with a banner — don't delete

A stale doc that still holds value keeps its place and gains a **top-of-file blockquote banner**
naming: what's outdated, what change obsoleted it, what to read instead, and which parts are
still current.

```markdown
> **⚠️ DEPRECATED — this guide predates {the change}. Do not follow it for {the stale purpose}.**
>
> It documents {the retired model}. Use {the maintained doc(s)} instead. This file is retained
> only for its still-current {sections that remain valid}.
```

- **Banner** when parts remain load-bearing (command references, still-valid sections).
- **Move to `docs/archive/`** when nothing in it is load-bearing but the history matters.
- **Delete** only when it is actively wrong end-to-end *and* fully replaced.

> **Why banner-first:** agents and developers trust what they find. A silently-stale doc fails
> open — it gets followed. A banner fails closed: the first line tells the reader not to. (ADRs
> are different: they are append-only and immutable — supersede with a new `D-NNN`, never edit;
> see [`DESIGN_AND_EPICS.md`](DESIGN_AND_EPICS.md).)
