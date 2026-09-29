# The {campaign} review, slice {S1}, {slice name}. Adjudication log

> **How to use.** The orchestrator copies this to `docs/security/{PFX}_REVIEW_{slice}_ADJUDICATION.md` when step 0 of
> the slice starts, and appends a section as each source arrives. One row per finding from every source, with the
> verdict, the fix, the test and the mutant. Never delete a row, a wrong verdict is corrected by a new row that says
> so. The process is [`../CODE_REVIEW_PROCESS.md`](../CODE_REVIEW_PROCESS.md), sections 4, 6 and 8. Delete this box
> and every hint in braces when you fill a section.

> **Status.** {Steps done, with dates and the commit or pull request that carries each. Next step.}

## 0. Baseline, step 0

| Fact | Before {S1} | After step 1 |
| --- | --- | --- |
| Tip | {`main` at sha, version, tree clean or not} | {the same tip, files changed, files new, committed or not} |
| Tests | {suites, cases, all pass} | {the same measure} |
| Lint and type check | {counts} | {counts} |
| `make ci`, or the repo's gate | {green or red, lanes} | {the same} |
| Mutation tests | {mutants and how many killed} | {the same} |
| Live stack | {how it was started} | {the same} |

## 1. Step 1 findings, the orchestrator's review

Severity as the process defines it, P, M, L or E. Blocks yes is a P, or an M that reaches an account, a token, a
credential, a privilege or someone else's data. Every fix is pinned by a test that fails without it and a mutant that
turns that test red, except where the row says otherwise.

| Id | Sev | Blocks | Finding | Evidence | Fix | Test | Mutant |
| --- | --- | --- | --- | --- | --- | --- | --- |
| {S1-1} | {M} | {no} | **{The defect, in bold, one sentence.}** {Why it matters.} | {the probe or the line} | {the change} | {the test} | {the mutant id} |

## 2. Checked and fine, probed rather than read

{What was probed against the running code and held, one line each with how. This section feeds the brief's settled
list, so write each entry so a stranger can tell what is settled.}

## 3. Decisions taken in this slice

{Each decision with its ADR number and a clause of reason.}

## 4. What changed

{Files and counts, the tests and mutants added, docs updated. A table is fine.}

## 5. Left open, and where it goes

| Item | Where it went | Why |
| --- | --- | --- |
| {the deferred finding} | {register row, ADR, or a later slice} | {the reason it waits} |

## 6. The fresh Claude review's findings, `{PFX}-{slice}-n`, adjudicated {date}

{The report, its file, the tip it read, how many findings, how many Blocks, how many reproduced, how many fixed, how
many declined.}

| Id | Sev | Verdict | Reproduced | Fix | Test | Mutant |
| --- | --- | --- | --- | --- | --- | --- |
| {PFX}-{slice}-1 | {M} | **Agreed.** {a clause} | {the command and what it printed} | {the change} | {the test} | {the mutant} |

## 7. The Codex review's findings, `{PFX}-{slice}-Cn`, adjudicated {date}

{The same table, one row per Codex finding. A finding both reviewers made is one row that names both ids.}

## 8. Step 4, the Sol dispatches

{The Artifact page URL, the tip it names, the number of dispatches and what each covers, and which rounds the slice
runs.}

## 9. Sol round 1, adjudicated {date}

### Dispatch 1, {area}

| Id | Sev | Verdict | Reproduced | Fix | Test | Mutant |
| --- | --- | --- | --- | --- | --- | --- |
| {PFX}-{slice}-D1-R1-1 | {E} | **Measured false.** {the measurement} | {the command} | none | none | none |

{Repeat for each dispatch, then one section per further round.}

## 10. The final reviews, adjudicated {date}

{Claude's `{PFX}-{slice}-FIN-n` and Codex's `{PFX}-{slice}-FIN-Cn`, the same table. A Blocks finding names its narrow
second read and the result.}

## 11. Closing

{Every gate green, the mutation table all killed, the consumer check green where it applies, the pull request and
its checks, and the date the owner merged it.}

The verdict on every finding is one of **Agreed**, **Agreed in part** with what was and was not taken, **Declined**
with the measurement that shows why, **Measured false**, or **Deferred** with the register row it became.
