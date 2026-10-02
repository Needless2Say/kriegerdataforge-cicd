# {YYYY-MM-DD} {scope} review. {What was reviewed, in one line}

> **How to use.** The orchestrator copies this to `README.md` at the root of the review folder,
> `docs/reviews/{YYYY-MM-DD}-{scope}/`, on the day the review opens, fills every `{...}`, and deletes this box
> and every hint in braces. It is the index a person reads first, so keep it short and current. The orchestrator
> updates it whenever a step closes, and adds the review's line to the top of `docs/reviews/README.md`, the archive's
> front door, the day the folder is created. The layout it describes is
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

## The question

{The owner's words, quoted, what the review is for.}

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
