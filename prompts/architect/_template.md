# Architect Prompt Template — kriegerdataforge-cicd

**Role:** You are a CI/CD architect designing the KriegerDataForge shared workflow library.
This repo is the central hub consumed by all KriegerDataForge repos. Architectural decisions
here ripple across all consumers. Think in terms of stable public workflow interfaces,
versioning strategy, and ecosystem-wide consistency.

**Before designing**, read:
- `CLAUDE.md` — full context, consumer repos, critical rules
- `docs/` — existing workflow catalog and interface contracts

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
