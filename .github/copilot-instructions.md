# Copilot Instructions — KriegerDataForge CI/CD

> **Repository:** kriegerdataforge-cicd
> **Purpose:** Shared reusable GitHub Actions workflow library for the KriegerDataForge ecosystem
> **Stack:** GitHub Actions · Composite Actions · Shell scripts · Docker

## What This Repo Is

This is the **single source of truth for all shared CI/CD logic** across the KriegerDataForge
ecosystem. Consumer repos call workflows here rather than maintaining their own copies:

```yaml
uses: Needless2Say/kriegerdataforge-cicd/.github/workflows/<workflow>.yml@main
```

**Consumer repos:** `fitness-app-frontend`, `tiffanys-space`, `kriegerdataforge`,
`arthurs-portfolio`, `kriegerdataforge-terraform`.

**Workflow categories:**
- Linting and code quality (ESLint, Ruff, mypy, actionlint, tflint)
- Testing (Jest, pytest, Terratest)
- Security scanning (CodeQL, Trivy, Checkov)
- Building and Docker image builds
- Deployment (Vercel preview + production, Docker Hub push)
- Infrastructure validation (Terraform plan/apply)

## Required Reading Before Any Task

- `CLAUDE.md` — full context, critical rules, and command reference
- `docs/` — workflow catalog and consumer integration guides (when available)

## Critical Rules

1. Never commit secrets — use `${{ secrets.NAME }}` exclusively.
2. Pin all third-party action versions to a commit SHA — never `@main` or `@latest`.
3. Every reusable workflow must have `on: workflow_call:` as its trigger.
4. Every change here is a **potential breaking change** for all consumer repos.
5. Set minimum required permissions using the `permissions:` block on every workflow.
6. Never use `pull_request_target` with an untrusted code checkout.
7. Adding a `required: true` input is a breaking change — use `required: false` + `default:` or coordinate first.

## Before Submitting a PR

- [ ] `make lint` passes (actionlint)
- [ ] Backward compatibility verified or all consumers updated
- [ ] Required secrets documented for consuming repo maintainers
- [ ] Action versions pinned to SHA or tag

## Prompts

AI prompts for development tasks are in `prompts/`:

- `prompts/dev/` — implement or modify reusable workflows
- `prompts/architect/` — cross-repo CI/CD architecture design
- `prompts/code_review/` — workflow security and compatibility review
- `prompts/tester/` — validate workflows work correctly for all consumers
- `prompts/docs/` — document workflows for consumer repo developers
