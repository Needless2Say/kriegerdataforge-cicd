# The {campaign} review, slice {S1}, {slice name}. The fresh review's report

> **How to use.** A reviewer copies this to the report path its brief names, `docs/security/{PFX}_REVIEW_{slice}_REPORT.md`
> for Claude or `..._CODEX_REPORT.md` for Codex, fills every section, and deletes this box. Under 250 lines. It is
> the only file a reviewer writes. The rules are [`../CODE_REVIEW_PROCESS.md`](../CODE_REVIEW_PROCESS.md) sections 5, 6
> and 8. Name a secret's variable and never its value.

## 1. Header

- **Tip read.** {sha}, {branch}.
- **The tree.** {clean, or uncommitted with `git status --porcelain` counts.}
- **Baseline reproduced.** {lint, type check, tests, the counts.} {A red baseline goes here first.}
- **Time spent.** {hours.}
- **Reviewer.** {model and effort.}

## 2. Verdict

{One paragraph. Is the slice fit to close, and what would change that answer.}

## 3. Findings

Severity is P, M, L or E as the process defines them. Blocks is yes for a P, or an M that reaches an account, a token,
a credential, a privilege or someone else's data. Most severe first.

| Id | Sev | Blocks | `file:line` | What | Proof, probe or read | Fix I would make |
| --- | --- | --- | --- | --- | --- | --- |
| {PFX}-{slice}-1 | {P} | {yes} | `{path:line}` | {what happens, in one or two sentences} | {the command or test that reproduces it, or the line quoted} | {the change} |

## 4. Checked and fine

{What you probed that held, one line each with how. This is what keeps the adjudication and the Sol rounds from
spending findings on it.}

## 5. Could not settle

{What you tried, and what would settle it. A finding you could not reproduce belongs here and not in section 3.}

## 6. Questions for the owner

{Decisions a review cannot take. One line each, with your recommendation.}
