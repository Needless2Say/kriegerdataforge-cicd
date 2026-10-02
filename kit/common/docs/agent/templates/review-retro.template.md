# The {campaign} review, {slice {S1}, {slice name}, the spot review of {scope}, or the whole campaign}. Retrospective

> **How to use.** The orchestrator copies this to `{PFX}_REVIEW_{slice}_RETRO.md` at the root of the slice's folder,
> beside the answer key, at step 6 once the answer key is written, and at spot scale to `{PFX}_REVIEW_RETRO.md` at the
> root of the review folder. When the whole review closes, the campaign's own retrospective is
> `{PFX}_REVIEW_CAMPAIGN_RETRO.md` at the root of the review folder, and its section 1 sums the slices' tables. The
> numbers come from the tool and are pasted as it printed them, never retyped or rounded. The rest is the
> orchestrator's analysis, short and with its evidence. Section 6 is filled only after the owner answers. The process
> is [`../CODE_REVIEW_PROCESS.md`](../CODE_REVIEW_PROCESS.md) section 14. Name a secret's variable, never its value.
> Under 150 lines. Delete this box and every hint in braces when you fill a section.

## 1. The numbers

{Run `node <cicd>/tools/claude-code/kdf-retro.js <slice folder>` and paste its whole output here, the findings by
source, the escapes line, the reports and the Sol rounds. If a report's minutes or tokens print as unknown, say once
below the tables which reports did not state them, since a later retrospective cannot measure what this one could not.}

## 2. Escapes

The escapes are the agreed findings that were in the tree the step 2 reviewers read and that a later step found. They
are the first number this retrospective answers to, since each one is a defect the step 2 reviews had in front of
them and missed.

| Id | Found by | Should have been found at | Why it was not | What would have caught it |
| --- | --- | --- | --- | --- |
| {PFX}-{slice}-D1-R1-2 | {Sol round 1} | {Step 2} | {The brief's look for list did not name the class, or the file was read past, or it needed a running stack} | {A look for line, a probe, a sibling in the brief's reading list} |

{When there are none, say so in one line and say what the slice did that may explain it.}

## 3. Friction

What cost the owner's time, the review's time or tokens, or confused the owner, with the evidence, a log section, a
message, a time stamp, a rerun.

| What happened | Cost | Evidence | Once, or seen before |
| --- | --- | --- | --- |
| {A step waited on the owner for a day, a launcher refused a run, a bundle could not be found} | {hours, a rerun, tokens} | {where it is recorded} | {once, or the retrospectives that saw it before} |

## 4. The experiments of earlier retrospectives

Every change an earlier retrospective proposed and the owner approved is an experiment. Read each against this slice.

| Change | Approved in | The number it should move | What it did here | Keep, revert, or watch |
| --- | --- | --- | --- | --- |
| {D-NNN, a look for line on secret handling} | {S1's retrospective} | {escapes of that class} | {two before, none here} | {keep} |

{Before the first retrospective of a campaign, list the changes the kit made since the last review that this one is
the first to run under, from the ledger.}

## 5. Proposals

A few at a time, so their effect can be told apart, each with the number it should move. Accuracy comes first, the
escape rate, then the owner's time and waiting, then tokens, and no proposal saves tokens at the cost of catches. A
thing seen once is noted in section 3 and proposed only when its cost is clear.

| # | Problem | Change | The number it should move | Cost | Where it lands |
| --- | --- | --- | --- | --- | --- |
| 1 | {Two escapes of one class} | {A look for line in the brief template} | {escapes of that class, to none} | {one line} | {the kit, the tooling, this review's next brief, a repo} |

## 6. The owner's decisions

{Filled after the owner answers the list in the chat, never before. One line per proposal, yes or no, the owner's
words where they gave a reason, the pull request that made each approved change, and its line in the bench repo's
ledger.}

| # | Decision | Owner's words | Pull request | Ledger |
| --- | --- | --- | --- | --- |
| 1 | {yes} | {"..."} | {#n} | {the ledger line's date and change} |
