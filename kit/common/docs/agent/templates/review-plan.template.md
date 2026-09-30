# The {scope} review, slice by slice, then the whole scope. The plan

> **How to use.** Copy this to `{PFX}_REVIEW_PLAN.md` at the root of the review folder of the lead repo,
> `docs/reviews/{YYYY-MM-DD}-{scope}/`, beside its `README.md`, and fill it from the repos'
> `AGENTS.md`, their code and their tests, and delete this box and every hint in braces. The process it plans is
> [`../CODE_REVIEW_PROCESS.md`](../CODE_REVIEW_PROCESS.md), so the plan does not restate the cycle or the rules, it
> holds what is particular to this scope. A spot review has no plan, its brief is the plan. At feature scale keep
> sections 1, 2, 4, 6, 10 and 11 and the appendix, and drop the rest. Across repos, one plan in the lead repo, the
> one that owns the contract, and a seam slice for each contract between the repos. The owner approves it before
> slice 1 starts. Section 2 is measured, never read or remembered. Keep the progress table current, it is the state a
> fresh session reads first.

> **Status.** {Draft, or Approved by the owner {date} with the decisions of section {n} answered. The scale, feature,
> repo, multi repo or ecosystem. Which slice is next. Anything uncommitted in the tree.}

## Progress

The orchestrator marks a row when its step starts, naming the branch and pull request, and again when it closes.

| Step | State |
| --- | --- |
| {S1. Slice name} | Not started |
| {S2. Slice name} | Not started |
| Phase B. The whole repo | Not started |
| {Phase C. Adoption, shared libraries only} | Not started |

## 1. The brief

{The owner's words, quoted, what they want from this review and what the repo is for. Then the two questions every
slice asks. Is it production ready, correct, secure, typed, tested so that a wrong change fails a test, documented as
it behaves, and cheap to call. And, for a shared repo, is it the common code it should be.}

Three phases, in order. **Phase A** reviews, fixes and extends the repo one slice at a time. **Phase B** reviews the
whole repo as one thing. {**Phase C** moves each consumer onto what the review added.}

## 2. Where the repo stands, {date}

Measured, not read.

| Fact | Value |
| --- | --- |
| Tip | {`main` at sha, tag, tree clean or not, who pins this commit} |
| Source | {files and lines by language} |
| Tests | {files, functions, cases, seconds} |
| Coverage | {lines and branches, how it was measured} |
| Gates on a pull request | {each gate, and whether it is green locally} |
| Mutation testing | {none, or the runner and the tables} |
| Consumer check | {none, or how consumers meet a change} |
| Releases | {what cuts a release, how consumers pin it} |
| Ruleset on `main` | {the rules, the required checks, who bypasses} |
| Decisions | {the ADR range} |
| Open register rows | {which rows this review takes} |
| Markers | {TODO, FIXME, suppressions, security comments, counts} |

**Defects already known.** Each reproduced by a measurement or a test. These are starting points for step 1, not the
whole of it.

- {The defect, where, and how it was reproduced.}

## 3. The repo in one page

{What it is, who uses it, and a table of its packages or areas with files, lines and role.}

## 4. How the repo is cut for review

A slice is a feature, the files that implement it, the tests that pin it, the docs that describe it and the
constants it owns. Each slice is reviewed in full once. A file two slices read is owned by the earlier one and read as
reference by the later. The order puts the foundation first, then the trust path from the outside in, so each later
slice reviews against fixed ground. {Across repos, name each slice's repo, and add a seam slice, `X1` and on, for each
contract between them, both ends read together, its files in the lead repo.}

### {S1. Slice name}, about {n} lines of source

| Files |
| --- |
| {source files} |
| Tests, {test files, and the tests of mixed files the slice takes out} |
| Docs, {docs the slice's cites hold against the code} |

{Repeat for each slice.}

### Phase B, whole repo

Everything above read together, plus what no slice owns. **No file is left out.** Appendix A maps every tracked file
to the slice that reviews it, or to the source it is synced from. Step 0 of Phase B diffs `git ls-files` against the
appendix, and a file that appeared since is assigned before the phase starts.

## 5. The cycle and the rules

The cycle is [`CODE_REVIEW_PROCESS.md`](../agent/CODE_REVIEW_PROCESS.md) section 4 and the rules are its section 5. This
repo adds {the deviations and the repo's own rules, or "nothing"}.

## 6. What each slice looks for

Starting questions from the surveys. A question becomes a finding only when a probe proves it.

### {S1. Slice name}

- {The question, specific.}

## 7. Phase B, the whole repo and its seams

- **The public surface as a whole.**
- **The seams**, with each neighbour the repo depends on or serves.
- **Docs.** Every doc read against the code.
- **Every tracked file** accounted for against Appendix A.

## 8. {What the consumers write for themselves, shared repos only}

{The survey of each consumer, what it uses and what it writes instead, and what is copied, largest first, with the
lines and where each lands. Measured again after adoption so the lines removed are a number.}

## 9. {Phase C, adoption, shared repos only}

{The order the consumers move in, one pull request per repository, the provider of identity last. Each pull request
bumps the pin, replaces the consumer's copy, deletes it and its tests where the shared repo's tests now hold the rule,
and passes the consumer's own release gate.}

## 10. Decisions for the owner

Each with a recommendation. The owner answers in this section and the date, and nothing starts before that.

1. **{Decision.}** {The options, the recommendation and why.}

## 11. Deliverables and where they live

Everything the review writes is archived in its folder, `docs/reviews/{YYYY-MM-DD}-{scope}/`, laid out as
[`CODE_REVIEW_PROCESS.md`](../agent/CODE_REVIEW_PROCESS.md) section 3 says.

| Deliverable | Where |
| --- | --- |
| The index | `README.md` in the review folder |
| This plan | `{PFX}_REVIEW_PLAN.md` in the review folder |
| Each slice's record | `<slice folder>/{PFX}_REVIEW_<slice>_ADJUDICATION.md`, one folder per slice, `s1-{name}` and on, then `phase-b` |
| Briefs and reports | `<slice folder>/step-2-review/{PFX}_REVIEW_<slice>_{PROMPT,REPORT,CODEX_REPORT}.md` |
| Sol dispatches and answers | `<slice folder>/step-4-sol/round-<n>/{PFX}_REVIEW_<slice>_SOL_R<n>_D<m>_{PROMPT,ANSWER}.md` |
| Final briefs and reports | `<slice folder>/step-5-final/{PFX}_REVIEW_<slice>_FINAL_{PROMPT,REPORT,CODEX_REPORT}.md` |
| Decisions | `docs/CHANGELOG_AND_DECISION_LOG.md`, from D-{next} |
| Deferred items | `docs/security/DEFERRED_ITEMS.md` |
| Progress | The Progress table at the top of this plan |

## 12. How the sessions run here

The runbook is [`CODE_REVIEW_PROCESS.md`](../agent/CODE_REVIEW_PROCESS.md) section 11. Here, in particular, {the folder the
orchestrator starts in, the models the owner picked for the orchestrator and the reviewers, the repo's own commands
the brief lists and the environment they run in, where Codex runs, and anything a fresh session needs that the
runbook does not say}.

## Appendix A. Every tracked file and the slice that reviews it

{Generated from `git ls-files` on {date}, {n} files, every one with exactly one owner. A file under a slice is
reviewed in full there. A synced file is checked equal to its source and reviewed there.}

| Owner | Files |
| --- | --- |
| {S1. Slice name, n} | {`path`, `path`} |
| Phase B, the whole repo, {n} | {`path`} |
| Synced, {source}, {n} | {`path`} |
