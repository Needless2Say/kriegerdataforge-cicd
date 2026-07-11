# Documentation-authoring prompts

Specialized prompts for generating documentation in **kriegerdataforge-cicd**. Feed one to
an AI (or follow it yourself) to produce a specific kind of doc, one at a time. Each prompt is
self-contained, tailored to this repo, and tells you to verify against the real code.

| Prompt | Produces | Output location |
|---|---|---|
| [`FEATURE_DOCUMENTATION_PROMPT.md`](FEATURE_DOCUMENTATION_PROMPT.md) | Document one implemented feature end to end | `docs/features/` |
| [`AGENT_DOCUMENTATION_PROMPT.md`](AGENT_DOCUMENTATION_PROMPT.md) | keep the repo's agent-facing docs accurate + author agent deep-dives | `docs/agent/ + AGENTS.md` |
| [`CODE_REVIEW_DOCUMENTATION_PROMPT.md`](CODE_REVIEW_DOCUMENTATION_PROMPT.md) | author a per-repo review playbook, or capture a review's findings in the repo's format | `docs/code_review/` |
| [`GUIDES_DOCUMENTATION_PROMPT.md`](GUIDES_DOCUMENTATION_PROMPT.md) | write how-to / operational runbooks | `docs/guides/` |
| [`REFERENCE_DOCUMENTATION_PROMPT.md`](REFERENCE_DOCUMENTATION_PROMPT.md) | write interface/config reference (endpoints / API / env / data model / contracts / policies) | `docs/reference/` |
| [`DESIGN_ADR_DOCUMENTATION_PROMPT.md`](DESIGN_ADR_DOCUMENTATION_PROMPT.md) | author a design doc + D-NNN ADR for a proposed change (a proposal, not code) | `docs/design/ + decision log` |

> These prompts only ever create/edit docs. They never change product code, and they respect
> the kit-sync boundary (`docs/agent/*`, `WORKFLOW.md`, `skills.md` are centrally managed).
