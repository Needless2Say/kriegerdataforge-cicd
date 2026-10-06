# {YYYY-MM-DD} {The bug, in one line}

> **How to use.** Copy this to `REPORT.md` in `docs/bugs/{YYYY-MM-DD}-{slug}/` the day a bug is taken up that is more
> than a Quick fix, with `LOG.md` beside it from [`work-log.template.md`](work-log.template.md), fill every `{...}`, and
> delete this box and every hint in braces. A Quick fix needs neither, its pull request is its record. Name a secret's
> variable, never its value, cite a user's report by its id, never its text, and leave out anything sensitive, which
> never goes into any repo. A public repo's bug report, and its log, are kept in the ecosystem's private context until
> the fix merges, never in the public repo. Read the staged diff before each commit and before the first push.

| | |
| --- | --- |
| Found | {YYYY-MM-DD, and by what, a test, a review's row, the owner, a user} |
| Status | {OPEN, FIXED in {the pull request's full link}, or WON'T FIX and why} |
| Severity | {H, M or L, and what it breaks} |

## What happens

{The symptom as seen, the environment, LOCAL, DEV or PROD, and how often.}

## How to reproduce it

{The smallest steps, and the failing test where one exists.}

## Why it happens

{The root cause, with the file and the line, and how it was confirmed.}

## The fix

{What changes, and why that closes the whole class and not one instance. The test that failed before and passes
after.}

## What else it touches

{Other callers, repos or data the bug or the fix reaches, and anything deferred, with where it went.}
