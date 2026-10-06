# {YYYY-MM-DD} {scope} review. {What was reviewed, in one line}

> **How to use.** The orchestrator copies this to `README.md` at the root of the review folder,
> `docs/reviews/{YYYY-MM-DD}-{scope}/`, on the day the review opens, fills every `{...}`, and deletes this box
> and every hint in braces. It is the index a person reads first, so keep it short and current. The orchestrator
> updates it whenever a step closes, rewrites its Now block at every step, and adds the review's line to the top of
> `docs/reviews/README.md`, the archive's front door, the day the folder is created. The layout it describes is
> [`../CODE_REVIEW_PROCESS.md`](../CODE_REVIEW_PROCESS.md) section 3. Link every file with a path relative to this
> folder, and name a secret's variable, never its value.

| | |
| --- | --- |
| Scale | {Spot, feature, repo, multi repo or ecosystem} |
| Repo | {This repo. Across repos, the lead repo's folder and every other repo's folder of the same name} |
| Opened | {YYYY-MM-DD, the day the owner asked for the review, the date in this folder's name} |
| Closed | {YYYY-MM-DD, or open} |
| Status | {Where it stands in one line, the next step and who takes it} |
| Plan | {[`{PFX}_REVIEW_PLAN.md`]({PFX}_REVIEW_PLAN.md), its progress table is the timeline. At spot scale none, the brief is the plan} |

## Now

{Where the review stands, rewritten at each step outside a pin's freeze and read first after a compaction or a
takeover, before the plan's progress table and the open slice's adjudication log. Process state alone, never a finding
or a judgment of the code, since the reviewers read the pinned tree. The launches a pin will start are named here in
the state commit before the pin, and from the pin until both of its reports are in nothing here changes.}

- Slice {S1}, step {n}, pin {the commit its brief names, its sha once it exists}. Next, {the next action}.
- Launches, {each launch this pin starts, the reviewer, the planned command and the report's path, and how it is
  checked, a Claude run by its report and its `.usage.json`, a Codex run by its report in the folder or on its collect
  branch}, or none.
- Pending, {outside a freeze, a Codex run, a Sol dispatch or a pull request started and not yet checked, its target,
  the output expected and how to check it}, or none.
- Waiting on the owner, {what}, or nothing.
- Do not, {what this review settled about its own process, not to redo or ask again}, or nothing.

## The question

{The owner's words, quoted, what the review is for. In a public repo, the question in words fit for the public, and
the owner's own words kept in the ecosystem's private context.}

## What is where

{One row per slice folder, or at spot scale per step folder, in the order the review ran.}

| Folder | What it holds |
| --- | --- |
| [`s1-{name}/`](s1-{name}/) | {Slice S1, what it covers. Its adjudication log is the slice's record, its answer key, written when the slice closed, restates the log as one table for scoring any reviewer's report, and its retrospective measures how the slice went and what the owner changed after it} |
| [`step-2-review/`](step-2-review/) | {At spot scale, the brief and both reports, read at pin {sha}} |
| [`{PFX}_REVIEW_ANSWER_KEY.md`]({PFX}_REVIEW_ANSWER_KEY.md) | {At spot scale, the answer key, written when the review closed} |
| [`{PFX}_REVIEW_RETRO.md`]({PFX}_REVIEW_RETRO.md) | {At spot scale, the retrospective, written after the answer key, and from the feature scale up the campaign's own, `{PFX}_REVIEW_CAMPAIGN_RETRO.md`} |

## Timeline

{At spot scale, one row per step. From the feature scale up, delete this section, the plan's progress table is the
timeline.}

| Date | Step | What happened | Files |
| --- | --- | --- | --- |
| {YYYY-MM-DD} | {Step 2} | {Claude and Codex read pin {sha}} | {Links to the brief and both reports} |

## Pull requests

| Pull request | Slice | Merged |
| --- | --- | --- |
| {#n} | {S1} | {YYYY-MM-DD, or open} |

## Sol pages

{The Claude Artifact page of each slice's Sol rounds, the page the owner copies from, with its URL. Every dispatch and
every answer is also kept word for word in the slice's `step-4-sol` folder. Delete this section when no Sol round
runs.}

## Outcome

{When the review closes. The findings by source, the orchestrator's own, Claude, Codex and Sol, how many were fixed,
declined or deferred, the register rows opened, the decisions recorded, and the date the owner called it done.}
