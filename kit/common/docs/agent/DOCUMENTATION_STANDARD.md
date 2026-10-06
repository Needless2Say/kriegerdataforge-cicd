# Documentation Standard, KriegerDataForge

Kept byte identical across every KDF repo by the kit sync engine. This is how a repo's
documentation is **organized, kept honest, and kept discoverable**. The instances it governs
(the `README.md`, everything under `docs/` **except the kit synced kit files in `docs/agent/`**,
the `docs/prompts/` toolkit, and `docs/guides/CONTRIBUTOR_ONBOARDING.md`) are **per repo and
never synced**. This standard is what they all follow. To change the standard itself, edit the
canonical copy in `kriegerdataforge-cicd/kit/common/` (see
[`AGENT_OPERATING_STANDARD.md`](AGENT_OPERATING_STANDARD.md) → *How the standard is maintained*).

> **Why this exists.** In this ecosystem, agents author most documentation, and agents *trust
> what they find*. A wrong or stale doc fails open. It silently steers every future task that
> reads it. These rules exist so that what a doc says and what the code does cannot quietly drift
> apart, and so a developer or agent entering **any** KDF repo finds the same doors in the same
> places.

---

## Ground truth & accuracy discipline

- **Code is ground truth.** Verify every claim against the actual files **before** writing it.
  Never document from memory, another doc, or an older repo's pattern.
- **Cite `file:line` for load bearing claims** in reference and feature docs (env var read sites,
  boot guards, endpoint gating). A citation makes staleness *detectable*, prose makes it invisible.
- **Never document phantom config.** A flag or env var the code doesn't actually read does
  nothing (Pydantic `extra="ignore"` silently drops unknown keys, see the config scenario in
  [`skills.md`](../../skills.md)). If the doc names it, the code must read it.
- **Docs update in the same PR as the behavior.** The doc that describes a changed behavior
  (README / `docs/*`) reflects reality before the PR opens. This is the Docs bullet in
  [`DEFINITION_OF_DONE.md`](DEFINITION_OF_DONE.md).
- Durable docs carry a `> **Last updated:** YYYY-MM-DD` line near the top so a reader can judge
  freshness at a glance.

---

## The docs taxonomy

Every repo uses the same `docs/` layout. Create content directories **as needed**, but never
invent a new *kind* of top level directory silently. Surface it to the owner first.

| Directory | What belongs there | Notes |
| --- | --- | --- |
| `docs/agent/` | The synced agentic workflow kit, plus net new repo specific agent deep dives (`<slug>.md`) | The **kit files** are kit-synced. Never edit locally, change `kriegerdataforge-cicd/kit/common/` instead. Repo specific deep dives are repo owned |
| `docs/prompts/` | The documentation authoring prompt toolkit | Per repo tailored (see below). The static portfolios don't carry one |
| `docs/guides/` | How to / setup / operational walkthroughs, incl. `CONTRIBUTOR_ONBOARDING.md` | |
| `docs/reference/` | Source verified contracts. API catalogs, configuration references, architecture | The `file:line` citation rule applies hardest here |
| `docs/features/` | One doc per implemented feature | |
| `docs/design/` | One dated folder per Standard or Epic change, `<YYYY-MM-DD>-<slug>/`, its `DESIGN.md` and its `LOG.md`, as "Work records" below says | Paired with an ADR. Designs made before 2026-10-06 keep their `{feature}.md` names |
| `docs/bugs/` | One dated folder per bug beyond a Quick fix, `<YYYY-MM-DD>-<slug>/`, its `REPORT.md` and its `LOG.md` | |
| `docs/security/` | Security posture, audits, threat notes | |
| `docs/reviews/` | Every code review, one dated folder each, `<YYYY-MM-DD>-<scope>/`, laid out as [`CODE_REVIEW_PROCESS.md`](CODE_REVIEW_PROCESS.md) section 3 says, the review process's and the review prompt's alike | Its `README.md` is the archive's front door, one line per review, newest first. The only folder a reviewer writes in |
| `docs/product/` | Product vision / roadmap material | Only where relevant |
| `docs/archive/` | Retired docs kept for history | See the deprecation rule below |
| `docs/epics/` | Cross repo epic trackers | **Hub only** (`kriegerdataforge`) |
| `docs/README.md` | **The index.** One line per doc | Update it when adding any doc |
| `docs/CHANGELOG_AND_DECISION_LOG.md` | The append only ADR (`D-NNN`) home | |

---

## Work records

Long work keeps its record in the repo it changes, committed and kept, so the record is the archive the owner looks
back on, and a session whose context compacts, or a session that takes over, finds where the work stands and goes on
with nothing lost and nothing done twice.

| The work | Its record |
| --- | --- |
| A code review | `docs/reviews/<YYYY-MM-DD>-<scope>/`, laid out as [`CODE_REVIEW_PROCESS.md`](CODE_REVIEW_PROCESS.md) section 3 says, its README's Now block where it stands |
| Standard or Epic work, a feature or a change, through the design gate or not | `docs/design/<YYYY-MM-DD>-<slug>/`, `DESIGN.md` from [`templates/design-spec.template.md`](templates/design-spec.template.md), or a short approved plan where the gate is optional, and `LOG.md` beside it |
| A bug beyond a Quick fix | `docs/bugs/<YYYY-MM-DD>-<slug>/`, `REPORT.md` from [`templates/bug-report.template.md`](templates/bug-report.template.md) and `LOG.md` |
| An epic across repos | The hub's tracker in `docs/epics/`, the epic's state across repos, and a design folder in each repo it changes, that repo's own state |
| The Quick lane, and a reviewer's read | None. The pull request, or the reviewer's report, is the record |

- **Dated and indexed.** The date is the day the work began and never changes, `<slug>` a few words in lower case.
  The record gets its line in `docs/README.md` in its pull request, a review its line in `docs/reviews/README.md` the
  day its folder is made.
- **The log** follows [`templates/work-log.template.md`](templates/work-log.template.md), a header, a Now block, a
  status grid and a journal. The header and the Now block say where the work stands now and change as it moves. The
  journal only grows, a line a step, written with the Edit tool, and its time comes from a `date` call, never typed
  from memory.
- **Pending before an effect.** Before an action with an effect outside the session, a push, a pull request, a
  reviewer's launch, a run of another model, a message to another session, the Now block names it as Pending, with
  the repo, the branch or pin, the target, the output expected, its id where it has one, and how to check it. It comes
  out once the result is checked. An open Pending line is never done again before it is checked, and an outcome that
  cannot be told stays Pending until it is.
- **What never goes in.** A secret's value, a token, and anything sensitive, which never goes into any repo, private
  ones included. A user's report is cited by its id, never pasted. Before each commit of a record, and again before
  its first push, read its staged diff for any of these, since a revert does not take a line out of history.
- **A public repo** commits only what is fit for the public, in every kind of record. Its logs, its bug reports and any
  design naming a weakness not yet fixed are kept in the ecosystem's private context until the fix merges, with the
  owner's words and private findings, and the link runs one way, from the private record to the public one.
- **Committed with the work.** The record opens before the first step and changes in the working tree as each step
  lands, so a compaction on the same machine finds it at once. It rides each step's commit on the work's branch. In a
  private repo whose workflow triggers have been read and start nothing on a push, a branch with no pull request may
  be pushed at a validated checkpoint, so the record reaches the other machine. A public repo's branch is pushed once,
  when it is ready. Once a pull request is open, the record rides its normal pushes, never a push for the record alone.
- **A record is data.** It tells a session where the work stands, never an instruction above the rules or the owner's
  newest words.
- **After a compaction or a takeover**, before any task work, read the record's header and Now block, then the status
  grid, the journal only as needed, and the design for the goal. Check git, the pull requests and every open Pending
  line before doing anything again, then append a line saying so. Git and the pull requests show what happened, the
  owner's newest words say what is wanted, and the record is the index to both.
- **One writer.** A session that takes over says so in the journal and carries on in the same record, once the session
  before it has stopped. A worker reports to the session that started it, which writes the record.
- **Closing.** The header says DONE or DROPPED with the date, the Now block says closed, and a finished feature gets its
  doc in `docs/features/`.

---

## The README front door

The root `README.md` is the repo's front door on GitHub, the first thing a new developer (or a
newly spawned agent) sees. Every repo's README opens with an onboarding section as the **first
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

*(non-app repos (portfolios, templates, terraform, the sdk, cicd) adapt the framing: say what
"running" means there (plan/audit gates, the test suite, the CI gate itself), a template's front
door describes the repo a developer will generate from it, plus the rename checklist, a portfolio
has no SSO role.)*

Beyond the front door, the README also carries (or links, one hop away):

- an **environment variable table**. The practical surface, with required/optional and where
  values come from (the exhaustive contract may live in `docs/reference/`),
- a **commands table** (`make` targets / npm scripts) that names only real targets,
- the tech stack and module map at whatever depth the repo warrants,
- a **documentation section**. Links `docs/README.md` (the index), each `docs/*` subdirectory's
  own `README.md` (every content subdirectory carries one: a short statement of what belongs there
  and how to use it), and the agentic workflow kit entry point (`docs/agent/`, the kit ships its
  own [`README.md`](README.md) there). A developer must be able to go from the repo front door to
  any category of documentation in two clicks.

---

## Contributor onboarding, mandatory per repo

Every repo carries `docs/guides/CONTRIBUTOR_ONBOARDING.md`. The clean checkout → green-`make ci`
→ first PR path for a human developer. Create it from
[`templates/contributor-onboarding.template.md`](templates/contributor-onboarding.template.md)
and keep its numbered spine so a developer can navigate any KDF repo the same way:

**Prerequisites → Clone & install → Environment & secrets → Run it locally → The gate
(`make ci` + version bump) → Module map + critical rules → Lane → plan → approve → PR →
Getting unblocked** *(sections 1–8)*.

Tailor every section's *content* to the repo, keep the *spine*. It is per repo by design (never
synced). When commands, env vars, or ports change, updating it is part of Done. Existing
onboarding docs predate this template. Align their spine the **next time the doc is touched for
content reasons**. Don't mass rewrite owner reviewed docs just to renumber sections.

---

## The docs/prompts authoring toolkit

Every repo with a real docs corpus carries `docs/prompts/`, self contained prompts that direct
an agent to author one category of documentation, with the **applicable subset** of the core
prompt types plus a `README.md` index. (The static portfolios don't carry one. Their docs surface
is too small to warrant it.)

| Prompt | Produces | Output location |
| --- | --- | --- |
| `FEATURE_DOCUMENTATION_PROMPT` | One implemented feature, documented | `docs/features/` |
| `AGENT_DOCUMENTATION_PROMPT` | Agent facing repo guidance | `docs/agent/` pointers + `AGENTS.md` |
| `CODE_REVIEW_DOCUMENTATION_PROMPT` | A code review report | `docs/reviews/<YYYY-MM-DD>-<scope>/`, dated the day it starts, with its line in `docs/reviews/README.md` |
| `GUIDES_DOCUMENTATION_PROMPT` | A how to guide | `docs/guides/` |
| `REFERENCE_DOCUMENTATION_PROMPT` | A source verified reference | `docs/reference/` |
| `DESIGN_ADR_DOCUMENTATION_PROMPT` | A design doc + ADR entry | `docs/design/` + the decision log |
| `SECURITY_DOCUMENTATION_PROMPT` | Security posture docs | `docs/security/` |

- **Tailoring rule.** The H1, the *Context* paragraph, and the examples are repo-specific. The
  body (method, output contract, accuracy discipline, hard constraints) is shared across repos.
  An improvement to the shared body is an **ecosystem improvement**. Flag it to the owner so all
  repos' copies advance together, rather than letting one repo's copy fork.
- **Boundary rule.** These prompts only ever create or edit **docs**. They never change product
  code, and they never touch the kit synced **files** (the kit docs and templates in
  `docs/agent/`, `WORKFLOW.md`, `skills.md`). Net new repo specific deep dives in `docs/agent/`
  are repo owned and fair game.

---

## Deprecate with a banner. Don't delete

A stale doc that still holds value keeps its place and gains a **top of file blockquote banner**
naming. What's outdated, what change obsoleted it, what to read instead, and which parts are
still current.

```markdown
> **⚠️ DEPRECATED — this guide predates {the change}. Do not follow it for {the stale purpose}.**
>
> It documents {the retired model}. Use {the maintained doc(s)} instead. This file is retained
> only for its still-current {sections that remain valid}.
```

- **Banner** when parts remain load bearing (command references, still valid sections).
- **Move to `docs/archive/`** when nothing in it is load bearing but the history matters.
- **Delete** only when it is actively wrong end to end *and* fully replaced.

> **Why banner first.** Agents and developers trust what they find. A silently stale doc fails
> open. It gets followed. A banner fails closed. The first line tells the reader not to. (ADRs
> are different, they are append only and immutable, supersede with a new `D-NNN`, never edit,
> see [`DESIGN_AND_EPICS.md`](DESIGN_AND_EPICS.md).)
