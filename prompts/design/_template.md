# Design Prompt Template — kriegerdataforge-cicd

**Role:** You are a CI/CD pipeline designer for the KriegerDataForge shared workflow library.
Design decisions here define the calling contract for consumer repos. Prioritize stable,
composable interfaces that work for all consumers without requiring repo-specific forks.

**Deployment model constraints:**
- All deploys are `workflow_dispatch` only — do NOT design auto-deploy triggers for CD workflows
- Every deployment job must use `environment:` to activate a GitHub Environment gate
- Consumer repos call with `secrets: inherit` — design secret names to match what's in GitHub Environment secrets
- Environments: `development` (owner + collaborators), `production` (owner only), `infrastructure` (owner only), all restricted to `main` branch

**Implemented workflows (existing public API — do not break):**
- `cd-nextjs-vercel.yml`, `cd-python-vercel.yml`, `cd-terraform.yml`, `issue-create-repo.yml`

---

## Design Task

**Name:** <!-- e.g., "Reusable Next.js build and test workflow" -->
**Size:** <!-- 🟢 S | 🟡 M | 🟠 L -->
**Summary:** <!-- One sentence description -->
**Consumer(s) in scope:** <!-- fitness-app-frontend | tiffanys-space | kriegerdataforge | arthurs-portfolio | kriegerdataforge-terraform | all -->

---

## Context

<!-- What problem is this solving? Which consumer repos need this? What variation exists across consumers? -->

---

## Deliverables

- [ ] Workflow purpose and consumer use cases
- [ ] `workflow_call` interface design:
  - Trigger events (`workflow_call`, `workflow_dispatch`)
  - Inputs (name, type, required, default) — default to `required: false`
  - Secrets (name, required, description)
  - Outputs (name, value source)
- [ ] Job structure and dependency graph
- [ ] Example calling syntax for each consumer repo
- [ ] Variation strategy — how inputs handle differences between consumers (e.g., different Node versions, different deploy targets)
- [ ] Backward compatibility notes
- [ ] Deployment model compliance: `workflow_dispatch` trigger only for CD; `environment:` on all deploy jobs
- [ ] Environment gate specification: which environment name, who approves, branch restriction
