# [Agent Name] — Context Document

**Agent:** [agent-name]-agent
**Workflow:** `.github/workflows/[agent-name]-agent.yml`
**Status:** TODO / Draft
**Last updated:** [YYYY-MM-DD]

---

## What This Agent Does

[1-3 sentences describing what the agent does, what it produces, and when it runs.]

---

## Trigger

| Event | Condition | Scope |
|---|---|---|
| [e.g., pull_request] | [e.g., opened or synchronize] | [e.g., all consumer repos] |

---

## Inputs

| Input | Type | Required | Description |
|---|---|---|---|
| [input_name] | string / number / boolean | yes / no | [What this input is used for] |

---

## Outputs / Artifacts

| Output | Format | Description |
|---|---|---|
| [output_name] | [JSON / string / file] | [What the agent produces] |

---

## Agent Prompt

The system prompt loaded into the AI for this agent's task. This should be the canonical
source — keep it in sync with the workflow's actual prompt string.

```
[Paste the system prompt here, or reference a file in prompts/ that this agent uses]
```

---

## Repo / Codebase Context

Context the agent needs to understand the repository it's working in:

**Repo:** [owner/repo]
**Language(s):** [e.g., Python 3.12, TypeScript 5.9]
**Framework(s):** [e.g., FastAPI, Next.js]
**Key directories:**
- `[path/]` — [what it contains]
- `[path/]` — [what it contains]

**Coding standards ref:** `[path/to/CODING_STANDARDS.md]`
**Architecture ref:** `[path/to/ARCHITECTURE.md]`

---

## What the Agent Should NOT Do

Explicit constraints to prevent unintended behavior:

- [ ] Do NOT modify source files — only comment/report
- [ ] Do NOT approve or merge PRs
- [ ] Do NOT expose secrets or internal paths in output
- [ ] [Add agent-specific constraints]

---

## Cost / Rate Limit Notes

| Metric | Estimate |
|---|---|
| Avg tokens per run | [___] |
| Runs per day (est.) | [___] |
| Estimated cost / day | $[___] |

[Note any rate limiting or spend controls implemented in the workflow.]

---

## Testing This Agent

How to test the agent in a non-production context before wiring into consumer repos:

```bash
# TODO: Add manual test instructions
# e.g., trigger workflow_dispatch from GitHub UI
# e.g., run the agent script locally with test inputs
```

---

## Open Questions / TODOs

- [ ] [Unresolved design decision or implementation detail]
- [ ] [Another open question]
