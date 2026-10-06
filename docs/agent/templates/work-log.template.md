# {The item}, the log

> **How to use.** Copy this to `LOG.md` beside the design or the bug report it tracks, in
> `docs/design/{YYYY-MM-DD}-{slug}/` or `docs/bugs/{YYYY-MM-DD}-{slug}/`, the day the work begins, fill every `{...}`,
> and delete this box and every hint in braces. The log is how a session whose context compacts, or a session that
> takes over, finds where the work stands, so it is written as each step lands and before each action with an effect
> outside the session, never at the end. The header and the Now block change as the work moves, and the journal only
> grows, written with the Edit tool, each line's time taken from a `date` call, never typed from memory. The owner's
> words go in word for word, except anything sensitive, which never goes into any repo, and the line says what was
> left out. A public repo's log is kept in the ecosystem's private context, not here. Name a secret's variable, never
> its value, cite a user's report by its id, read the staged diff before each commit, and read every outgoing commit's
> patch before a push. A review keeps no log of this shape, its README's Now block and its adjudication logs are its
> record.
> The rules are [`../DOCUMENTATION_STANDARD.md`](../DOCUMENTATION_STANDARD.md), "Work records".

- **Status.** {OPEN, WAITING ON THE OWNER, DONE or DROPPED}, {YYYY-MM-DD}.
- **Tracks.** [{DESIGN.md or REPORT.md}]({DESIGN.md or REPORT.md}), ADR {D-NNN, or none yet}, branch `{name}`, pull
  requests {full links, or none yet}.
- **After a compaction or a takeover.** Read this header and Now, then the status grid, then check git, the pull
  requests and every open Pending line before doing anything again, then append "Compacted at {time}, the log was
  current or behind by {what}, the summary named it or did not". Git and the pull requests show what happened, and the
  owner's newest words say what is wanted, even when they came after the last line here.

## Now

- Step {n}, {what}. Next, {the next action and the files it needs}.
- Pending, {an action started and not yet checked, its repo, branch or pin, target, the output expected, its id where
  it has one, and how to check it}, or none. An open Pending line is never done again before it is checked, and an
  outcome that cannot be told stays Pending until it is.
- Running, {a job and where its output lands}, or none.
- Waiting on the owner, {what}, or nothing.
- Do not, {what this item settled, not to redo or ask again}, or nothing.

## Status grid

| # | Step | Repo and pull request | Status |
| --- | --- | --- | --- |
| 1 | {The step} | {The repo and the pull request's full link} | {Done, in progress or pending} |

## Journal

- {YYYY-MM-DD HH:MM} {What landed, a decision and why, what failed, where an answer is, a commit.}
- {YYYY-MM-DD HH:MM} The owner, "{their words}".
