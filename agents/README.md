# agents/ — AI-Driven CI/CD Agents

**Status: Brainstorm / Skeleton** — This directory is a placeholder for future AI-driven
automation work. The structure is intentional; the implementation is not. Revisit this after
the core KriegerDataForge infrastructure refactor is complete.

---

## Vision

The goal is to extend `kriegerdataforge-cicd` beyond static GitHub Actions workflows into
**AI-driven agents** that can reason, take action, and automate developer tasks across the
entire KriegerDataForge ecosystem.

Examples of what these agents could eventually do:

| Agent | Trigger | What it does |
|---|---|---|
| `pr-review-agent` | PR opened / updated | Posts inline code review comments using Claude |
| `doc-update-agent` | Merge to main | Detects new/changed code and generates or updates docs |
| `deploy-advisor-agent` | Manual trigger | Checks readiness signals and advises on deploy safety |
| `issue-triage-agent` | Issue created | Categorizes, labels, and routes new GitHub issues |
| `changelog-agent` | Release tag created | Drafts CHANGELOG entry from commit history |
| `test-gen-agent` | PR opened | Identifies untested code and generates test stubs |

---

## Planned Directory Structure

```
agents/
  README.md                          ← This file
  workflows/
    _ai-agent-template.yml           ← Skeleton GitHub Actions workflow for AI agents
    pr-review-agent.yml              ← TODO: AI code review on PR events
    doc-update-agent.yml             ← TODO: Auto doc generation on merge
    deploy-advisor-agent.yml         ← TODO: Deploy readiness check
  context/
    _agent-context-template.md       ← Template for writing per-agent context docs
    ecosystem-context.md             ← TODO: Shared KDF ecosystem context for all agents
  definitions/
    _agent-definition-template.md    ← TODO: Formal agent spec format
```

---

## How AI Agents Fit Into This Repo

`kriegerdataforge-cicd` is already the single source of truth for all CI/CD workflows.
AI agent workflows will live here as reusable `workflow_call` workflows, just like the
existing deploy workflows.

Consumer repos will call them the same way:

```yaml
jobs:
  review:
    uses: Needless2Say/kriegerdataforge-cicd/.github/workflows/pr-review-agent.yml@main
    with:
      pr_number: ${{ github.event.pull_request.number }}
    secrets: inherit
```

All AI API keys (`ANTHROPIC_API_KEY`, etc.) live exclusively in GitHub Environment secrets,
following the same credential isolation model as the deploy workflows.

---

## Key Design Decisions (to make when building)

- [ ] **Which AI API?** Claude (Anthropic) is the preference given existing tooling, but
      this should be formalized as a documented decision.
- [ ] **Agent invocation pattern:** Inline curl in YAML vs. dedicated script in `scripts/`
      vs. a Python agent runner.
- [ ] **Output format:** GitHub PR comments, issues, commit messages, or all of the above?
- [ ] **Rate limits and cost controls:** How do we prevent runaway API spend on busy PRs?
- [ ] **Authentication scope:** Should agents have write access to repos, or just comment?

---

## Getting Started (when ready to implement)

1. Copy `workflows/_ai-agent-template.yml` and rename it for the specific agent.
2. Copy `context/_agent-context-template.md` and write the agent's context doc.
3. Add `ANTHROPIC_API_KEY` to the appropriate GitHub Environment secrets.
4. Wire the workflow into consumer repos as a `workflow_call` caller.
5. Test in a branch PR before merging to `main`.

---

## Related Resources

- `docs/WORKFLOWS.md` — Full catalog of existing reusable workflows
- `CLAUDE.md` — Repo overview and critical rules for AI agents working in this repo
