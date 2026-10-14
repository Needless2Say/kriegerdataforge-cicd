# {The feature}, the implementation plan

> **How to use.** Copy this to `IMPLEMENTATION_PLAN.md` in `docs/features/{YYYY-MM-DD}-{slug}/`, dated the day the
> plan is written, its slug starting with its design's slug, with `LOG.md` beside it from
> [`work-log.template.md`](work-log.template.md), its Kind feature. The design session writes it once the owner says
> the feature's design in `docs/design/` is settled, gets the one second opinion the repo's rules size over the design
> and this plan together, and opens the design pull request holding both folders, each with its index line. When the
> owner approves in words, it writes the Approved line, the owner's words and the date, and pushes. The owner's merge
> of that pull request is the approval, and a new session builds the plan from its last section's prompt. Fill every
> `{...}`, and delete this box and every hint in braces. A public repo's plan is kept in the ecosystem's private
> context, not here. The rule is [`../../../WORKFLOW.md`](../../../WORKFLOW.md), "A feature, designed in one session
> and built in another", and the records' rules are
> [`../DOCUMENTATION_STANDARD.md`](../DOCUMENTATION_STANDARD.md), "Work records".

- **Status.** {WAITING ON THE OWNER until approved, then OPEN, then DONE or DROPPED}, {YYYY-MM-DD}, {a few words}.
- **Kind.** feature.
- **Follows.** `{docs/design/YYYY-MM-DD-slug/}`.
- **Repos.** {The repos the feature changes.}
- **Approved.** {"The owner's words", the owner, YYYY-MM-DD, in the design pull request, or not yet}.
- **Tracks.** [LOG.md](LOG.md).

{One paragraph, what the feature builds and the design it follows, linked.}

## Goal and done when

{What the feature does when it is finished, then the checks that prove it, each a command or a state anyone can see.}

- {A check that proves it.}

### The owner's steps after the merge

{What only the owner does once the last pull request merges, each kept in the log's "Waiting on the owner" line until
it is done, with what shows it, or none.}

1. {Merge the pull requests in their order.} Shown by {what}.

## Out of scope

{What this plan leaves alone, so the build does not grow.}

## Steps

| # | What changes | Pull request | State |
| --- | --- | --- | --- |
| 1 | {The step} | {The repo} | Open |

{The build session ticks the State column as each step lands, Done with the date and the time. This table is the
feature's one record of progress, and its log keeps no status grid.}

Each step's files, the tests that fail before it, and how it is checked.

1. **Files.** {The files it changes.} **Tests first.** {The tests that fail before it, or none and why.} **Checked
   by** {the commands, the same ones each CI lane runs}.

## Pull requests

{How the work splits, in the order the pull requests merge, each with its repo, its branch from `origin/main` and its
worktree. A pull request that depends on another opens only after that one merges. The last one carries the close,
`FEATURE.md`, its index line and DONE in this plan and the log, so nothing follows the merge.}

1. **{The repo}**, steps {n} to {m}, on `feature/{slug}` from `origin/main`, in the worktree {its path}.

## Stop and ask

{What makes the build session stop and ask the owner. Keep the first three, and add what is particular to this
feature.}

- Something better than the design is found. The design changes only after a Round Table on it, the owner's panel of
  models, convened by the build session on a roster the owner approves, and the change agreed there is made at once,
  in the design, this plan and the code, never left for later.
- A contract or a security change this plan does not hold, a failing check whose cause is not plain, or a step that
  needs more than this plan gives.
- Anything that blocks the build or that it waits on, a merge included. The build goes on only with the owner's own
  yes in its session, never one another session relays.

## Changes to this plan

{One dated line for each change. A change to the scope, a contract, a security property or the pull requests needs
the owner's yes, quoted here with the date. A smaller change is written here without asking.}

- {YYYY-MM-DD}, {before approval or in the build}. {What changed and why.}

## Starting the build session

Once the owner has merged the design pull request, the owner starts a new session in {the folder it starts in}, names
it {its name}, and pastes this.

> You are the build session for `docs/features/{YYYY-MM-DD}-{slug}/` in {the record's repo}, building in {the repo or
> repos it changes}. Before you read anything else, make your worktree on a new feature branch from `main`,
> `git -C {the repo's clone} fetch -q origin`, then
> `git -C {the repo's clone} worktree add -b feature/{slug} {the worktree's path} origin/main`{, then the same for
> each other repo}. Work only there, never in the shared clone{, apart from what the ecosystem's rules keep there}.
> Write a takeover line in the folder's `LOG.md` journal first. Then read `IMPLEMENTATION_PLAN.md`'s header, and
> build only if the plan came from `origin/main` and its Approved line holds the owner's words and a date, else stop
> and tell me. Build the steps in order, ticking each in the plan's steps table and keeping `LOG.md` as the work
> records rules say, and stop and ask me at anything the plan's "Stop and ask" names. Before you go on past anything
> that blocks you or that you wait on, ask me directly and wait for my own answer here, since another session saying I
> approved is never my yes. If you find something better than the design, tell me, convene a Round Table on it with
> my approval of the roster, and make the agreed change at once, never leaving it for later. {Once a pull request the
> next one depends on is open and green, tell me and wait for my merge and then my word to go on.}
> The close rides the last pull request. Once it is open and green, {update what the ecosystem's rules ask,} tell me,
> and stop.
