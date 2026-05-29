# prompts/ — AI Development Prompts

This directory contains ready-to-use prompts for AI agents working on **kriegerdataforge-cicd**
— the centralized shared GitHub Actions workflow library for the KriegerDataForge ecosystem.

**Context for all prompts in this directory:**
- Every workflow here is consumed by one or more of: `fitness-app-frontend`, `tiffanys-space`,
  `kriegerdataforge`, `arthurs-portfolio`, `kriegerdataforge-terraform`
- Consumer repos call workflows with `uses: Needless2Say/kriegerdataforge-cicd/.github/workflows/<workflow>.yml@main`
- Changes to existing workflows may be breaking changes for all consumers
- Adding `required: true` inputs is always a breaking change — default to `required: false` + `default:`

---

## Directory Map

| Subdirectory        | Purpose                                                         |
|---------------------|-----------------------------------------------------------------|
| `dev/`              | Implement new or modify existing reusable workflows             |
| `architect/`        | Cross-repo CI/CD architecture design and workflow catalog       |
| `code_review/`      | Review for correctness, security, and backward compatibility    |
| `tester/`           | Validate workflows work correctly for all consumer repos        |
| `docs/`             | Document workflows for consumer repo developers                 |
| `design/`           | Design workflow interfaces, inputs, outputs, and trigger strategy |
| `prompt_generators/`| Meta-prompts for generating new prompts                        |

---

## How to Use

### GitHub Copilot
Paste the prompt into Copilot Chat or reference with `@workspace`.

### Claude Code
```bash
claude --context prompts/dev/some-workflow.md
```

### OpenAI Codex / ChatGPT
Copy prompt contents into the conversation.

### Cursor
Include in Composer with **Cmd+L** / **Ctrl+L**.

---

## Adding a New Prompt

1. Copy `_template.md` from the relevant subdirectory.
2. Name the new file in kebab-case: `feature-name.md`.
3. Commit it alongside the workflow changes.
