# prompts/ — AI Development Prompts

This directory contains ready-to-use prompts for AI agents working on **kriegerdataforge-cicd**
— the centralized shared GitHub Actions workflow library for the KriegerDataForge ecosystem.

**Implemented workflows (as of current state):**

| Workflow | Purpose | Consumers |
|---|---|---|
| `cd-nextjs-vercel.yml` | Deploy Next.js → Vercel | `fitness-app-frontend`, `tiffanys-space`, `arthurs-portfolio` |
| `cd-python-vercel.yml` | Deploy FastAPI → Vercel + Alembic migrations | `kriegerdataforge` |
| `cd-terraform.yml` | `terraform plan` + `apply` for Vercel infra | `kriegerdataforge-terraform` |
| `issue-create-repo.yml` | Auto-provision repos from issue templates | internal |

**Deployment model context for all prompts:**
- All deploys are manual (`workflow_dispatch` only) — no auto-deploy on push
- Every deploy passes through a GitHub Environment gate (pauses for required reviewer approval)
- `production` environment: owner-only approval, `main` branch only
- `development` environment: owner + collaborators can approve, `main` branch only
- `infrastructure` environment (terraform): owner-only, `main` only
- `VERCEL_TOKEN`, `DB_DATABASE_URL`, and all credentials live only in GitHub Environment secrets
- `secrets: inherit` is the standard caller pattern in consumer repos
- Changes to existing workflows may be breaking changes for all 5 consumer repos

Full reference: `docs/WORKFLOWS.md` (calling syntax, inputs, secrets) and `docs/MANUAL_SETUP.md`.

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
