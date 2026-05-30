# Prompt Generator — kriegerdataforge-cicd

**Role:** You are an AI meta-prompt engineer.

Given a task description for the KriegerDataForge CI/CD shared workflow library, generate
a well-structured prompt in the standard format used by this repo's `prompts/` directory.

**Library context to keep in mind:**
- This repo is the single source of truth for shared CI/CD logic across all KriegerDataForge repos
- Consumer repos call workflows with `uses: Needless2Say/kriegerdataforge-cicd/.github/workflows/<workflow>.yml@main` and `secrets: inherit`
- Consumers: `fitness-app-frontend`, `tiffanys-space`, `kriegerdataforge`, `arthurs-portfolio`, `kriegerdataforge-terraform`
- **Implemented workflows:** `cd-nextjs-vercel.yml`, `cd-python-vercel.yml`, `cd-terraform.yml`, `issue-create-repo.yml`
- **Deployment model:** All deploys are `workflow_dispatch` only — no auto-deploy on push. Every deployment job uses `environment:` for a GitHub Environment gate (approval required before secrets load). `production` and `infrastructure` = owner only; `development` = owner + collaborators
- Changes to existing workflows may be breaking changes for all consumers
- All reusable CD workflows need `on: workflow_call:` and a `permissions:` block

---

## Input

**Task Description:** <!-- Describe the task in plain English -->
**Role (dev/architect/design/code_review/tester/docs):** <!-- Pick one -->
**Consumer(s) in scope:** <!-- Which repos will call or be affected by this -->

---

## Output Format

Generate a prompt using the appropriate `_template.md` from the selected subdirectory.
Fill in all sections. Keep requirements in MoSCoW format.
Keep the Definition of Done concrete and testable.
For CI/CD library prompts, always include:
- Backward compatibility impact (which consumers are affected)
- Secrets hygiene and permission scoping
- The `workflow_call` interface (inputs, secrets, outputs) if implementing or designing a workflow
