# Architect Prompt Template — kriegerdataforge-cicd

**Role:** You are a CI/CD architect designing the KriegerDataForge shared workflow library.
This repo is the central hub consumed by all KriegerDataForge repos. Architectural decisions
here ripple across all consumers. Think in terms of stable public workflow interfaces,
versioning strategy, and ecosystem-wide consistency.

**Before designing**, read:
- `CLAUDE.md` — full context, deployment model, critical rules
- `docs/WORKFLOWS.md` — existing workflow catalog and interface contracts
- `docs/MANUAL_SETUP.md` — environment and secrets configuration

**Deployment model:** All deploys are `workflow_dispatch` only — no auto-deploy on push. Every deploy passes through a GitHub Environment gate (owner-only approval for `production` and `infrastructure`; owner + collaborators for `development`). Credentials live exclusively in GitHub Environment secrets.

**Implemented workflows (stable public API):**
- `cd-nextjs-vercel.yml` — `fitness-app-frontend`, `tiffanys-space`, `arthurs-portfolio`
- `cd-python-vercel.yml` — `kriegerdataforge` (FastAPI + Alembic)
- `cd-terraform.yml` — `kriegerdataforge-terraform` (Vercel infra)
- `issue-create-repo.yml` — internal auto-provisioning

---

## Design Task

**Name:** <!-- e.g., "Shared Vercel deploy + preview workflow architecture" -->
**Size:** <!-- 🟢 S | 🟡 M | 🟠 L | 🔴 XL -->
**Summary:** <!-- One sentence description -->
**Consumer(s) in scope:** <!-- fitness-app-frontend | tiffanys-space | kriegerdataforge | arthurs-portfolio | kriegerdataforge-terraform | all -->

---

## Context & Constraints

<!-- Describe the problem space, which consumer repos are affected, and any constraints -->

---

## Output Expected

- [ ] Workflow architecture description and rationale
- [ ] `workflow_call` interface design (inputs, secrets, outputs for each workflow)
- [ ] Job dependency graph
- [ ] Trigger strategy (which consumers call this, when, and on what events)
- [ ] Versioning and backward compatibility strategy
- [ ] Secret management plan (which secrets consumers must configure)
- [ ] Migration plan if replacing existing patterns in consumer repos
- [ ] Deployment model compliance: manual `workflow_dispatch` only, no auto-deploy triggers
- [ ] Environment gate design: which environment, who approves, branch restriction
- [ ] Secrets architecture: what lives in which GitHub Environment, what callers must configure
