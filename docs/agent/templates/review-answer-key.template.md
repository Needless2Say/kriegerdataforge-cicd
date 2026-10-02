# The {campaign} review, {slice {S1}, {slice name}, or the spot review of {scope}}. Answer key

> **How to use.** The orchestrator copies this to `{PFX}_REVIEW_{slice}_ANSWER_KEY.md` at the root of the slice's
> folder, beside the adjudication log, at step 6 when the slice closes, and at spot scale to `{PFX}_REVIEW_ANSWER_KEY.md`
> at the root of the review folder when the review closes. It is written once, from the finished adjudication log and
> from git, and it restates the log's verdicts as one table, so a later reader, or a benchmark that scores another
> model's report on this slice, needs nothing else. It adds no verdict of its own. Every row cites the log row it
> restates, and a log row corrected later is corrected here in the same commit. The process is
> [`../CODE_REVIEW_PROCESS.md`](../CODE_REVIEW_PROCESS.md) sections 3, 8 and 14. Name a secret's variable, never its
> value. Delete this box and every hint in braces when you fill a section.

## 1. The commits each reader read

Every reader of the slice and the commit it read, since a report is only ever scored against the defects that were in
the tree it saw. The pins come from the briefs and the reports' headers, each Sol round's commit from the branch and
commit its dispatch files name.

| Reader | Step | Commit read | State commit | Model, as its report or the run names it | Its report or answers |
| --- | --- | --- | --- | --- | --- |
| {Orchestrator} | {Step 1} | {`main` at sha, version} | | {model and effort} | {the log's section 1} |
| {Fresh Claude reviewer} | {Step 2} | {pin sha} | {state sha} | {model and effort} | {link to the report} |
| {Codex} | {Step 2} | {pin sha} | {state sha} | {model and effort} | {link to the Codex report} |
| {Sol} | {Round 1} | {the commit its dispatches name} | | {model} | {link to `step-4-sol/round-1/`} |
| {Fresh Claude reviewer, Codex} | {Step 5 final} | {pin sha} | {state sha} | {models} | {links to both final reports} |
| {Fresh Claude reviewer, Codex} | {Second read n} | {pin sha} | {state sha} | {models} | {links} |
| Merged | Step 6 | {merge commit, pull request #n, version} | | | |

## 2. The step 2 brief and what the reviewers had

{The brief's path, the one line that started each reviewer, and whether the brief in the archive is the one at the
pin, word for word. When a later commit edited it, say so, since a benchmark feeds another model the brief as it stood
at the pin. Then what the step 2 reviewers had beyond the repo, the sibling checkouts and the commits they were at, a
running stack and how it was started, and how long each review took.}

## 3. The findings

One row per finding of every source, the orchestrator's own, both step 2 reviews, each Sol round, the final reviews and
the second reads, real or not, plus every question for the owner that was acted on. Severity and Blocks as adjudicated.
**At the step 2 pin** says whether the defect was in the tree the step 2 reviewers read, yes, no or unsure, and **How
decided** says how that was settled, a read of the file at the pin, a probe, or the commit that brought the code in.
**Needs** says what a reviewer had to have to find it, the repo alone, the sibling repos, or a running stack.
**Source** uses the words `kdf-retro.js` places in the cycle, `Orchestrator, step 1`, `Orchestrator, after step 2`,
`Step 2 Claude`, `Step 2 Codex`, `Sol R<n> D<m>`, `Second read <n>`, `Final Claude` and `Final Codex`, so a finding the
orchestrator made after the pin counts as an escape. The tool prints how it read each source, and one it cannot place
prints as unplaced.

Sorted by At the step 2 pin (yes, unsure, no, declined) and within each by severity, most severe first.

| Id | Source | Reviewer model | Sev | Blocks | Verdict | Where at the pin | Present from | Fixed in | At the step 2 pin | How decided | Needs | The defect | Log row |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| {PFX}-{slice}-1 | {Step 2, Claude} | {model} | {M} | {no} | {Agreed} | `{path:line}` | {before the review, or the sha that brought it in} | {sha} | {yes} | {read the file at the pin} | {the repo alone} | {One sentence, what goes wrong and for whom.} | {section 6} |

{When several rows share one root that was simpler at the pin, say so under the table, so a reviewer that names the
root is credited once and not for every row that grew from it.}

## 4. Declined, and measured false

What a reviewer might raise that the slice settled as not a defect, with the measurement or the reason. A later
reviewer that raises one of these with no new evidence is repeating it, not finding something. Include the declined
half of a finding agreed in part, and the brief's own settled list when a reviewer might mistake one of its items for
a defect.

| What a reviewer might say | Id | The measurement or the reason | Log row |
| --- | --- | --- | --- |
| {The claim, in plain words} | {id} | {What was measured, or the decision and its ADR} | {section n} |

## 5. Counts

| Findings with an id | P | M | L | E | All |
| --- | --- | --- | --- | --- | --- |
| At the step 2 pin | | | | | |
| Of those, Blocks | | | | | |
| Caught by the step 2 Claude review | | | | | |
| Caught by the step 2 Codex review | | | | | |
| Caught by either | | | | | |
| Found later, by Sol, the final reviews or a second read | | | | | |

{One line that reconciles with the log, the finding ids it carries, how many were at the step 2 pin, how many came in
after it, and how many were declined or measured false.}
