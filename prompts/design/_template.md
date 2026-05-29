# Design Prompt Template — kriegerdataforge-cicd

**Role:** You are a CI/CD pipeline designer for the KriegerDataForge shared workflow library.
Design decisions here define the calling contract for consumer repos. Prioritize stable,
composable interfaces that work for all consumers without requiring repo-specific forks.

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
