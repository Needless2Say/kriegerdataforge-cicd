# The {campaign} review, {slice {S1}, {slice name}, or the spot review of {scope}}. The fresh review's report

> **How to use.** A reviewer copies this to the report path its brief names, `docs/security/{PFX}_REVIEW_{slice}_REPORT.md`
> for Claude or `..._CODEX_REPORT.md` for Codex, and at spot scale `docs/security/{PFX}_REVIEW_REPORT.md`, fills every
> section, and deletes this box. Under 250 lines. It is the file a reviewer writes, with any scratch note beside it
> under `docs/security`, both new files. The rules are
> [`../CODE_REVIEW_PROCESS.md`](../CODE_REVIEW_PROCESS.md) sections 5, 6 and 8. Name a secret's variable and never its
> value.

## 1. Header

- **Pin read.** {sha}, as `git rev-parse HEAD` printed it, on branch {branch}. {If it differs from the brief's pin,
  say so first, and stop.}
- **Read first.** {The files you read before the code, in the order you read them, from `AGENTS.md` to the brief's
  reading list. The launcher warns when this line or the pin is missing.}
- **Baseline reproduced.** {lint, type check, tests, the counts.} {A red baseline goes here first.}
- **Time spent.** {hours.}
- **Reviewer.** {model and effort.}

## 2. Verdict

{One paragraph. Is the slice fit to close, and what would change that answer.}

## 3. Findings

Severity is P, M, L or E as the process defines them. Blocks is yes for a P, or an M that reaches an account, a token,
a credential, a privilege or someone else's data. Most severe first. Ids are `{PFX}-{slice}-1` from Claude and
`{PFX}-{slice}-C1` from Codex, `{PFX}-{slice}-FIN-1` and `-FIN-C1` in a final review, and `{PFX}-1` and `{PFX}-C1` at
spot scale.

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
