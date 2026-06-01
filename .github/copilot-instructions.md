# Copilot Instructions — KriegerDataForge CI/CD

> **Repository:** kriegerdataforge-cicd
> **Purpose:** Shared reusable GitHub Actions workflow library — all KriegerDataForge deployment logic lives here
> **Stack:** GitHub Actions · Vercel CLI · Terraform · Shell scripts

## Implemented Workflows

| File | Purpose | Called by |
|---|---|---|
| `cd-nextjs-vercel.yml` | Deploy Next.js → Vercel | `fitness-app-frontend`, `tiffanys-space`, `arthurs-portfolio` |
| `cd-python-vercel.yml` | Deploy FastAPI → Vercel + optional Alembic migrations | `kriegerdataforge`, `fitness-app-backend`, `tiffanys-closet-backend` |
| `cd-terraform.yml` | `terraform plan` + `apply` for Vercel infra | `kriegerdataforge-terraform` |
| `issue-create-repo.yml` | Auto-provision repos from issue template | internal |

Full calling syntax, inputs, and secrets reference: `docs/WORKFLOWS.md`.

## Deployment Model

- **All deploys are manual** — `workflow_dispatch` only, no auto-deploy on push
- **Every deploy passes through a GitHub Environment gate** — pauses for required reviewer approval before secrets are loaded
- `VERCEL_TOKEN`, `DB_DATABASE_URL`, and all credentials live only in GitHub Environment secrets
- Collaborators cannot deploy locally — there is no token outside GitHub Environments
- Local dev uses `make docker-up` with no cloud credentials

## Environment Gates

| Environment | Approved by | Branch |
|---|---|---|
| `dev` | Owner + collaborators | `main` only |
| `prod` | Owner only | `main` only |
| `infra` | Owner only | `main` only |

> **Naming:** environments are `dev`/`prod`/`infra` — NEVER `development`/`production`/`infrastructure`.

## Required Reading Before Any Task

- `CLAUDE.md` — full context, deployment model, critical rules
- `docs/WORKFLOWS.md` — workflow catalog with calling syntax and secrets reference
- `docs/MANUAL_SETUP.md` — environment setup and PAT configuration

## Critical Rules

1. Never commit secrets — use `${{ secrets.NAME }}` exclusively.
2. Pin all actions to a tag (e.g. `@v6`) — never `@main` or `@latest`.
3. Every deployment workflow must use `environment:` to activate the GitHub Environment gate.
4. Every change to an existing workflow is a **potential breaking change** for all consumer repos.
5. Set minimum `permissions:` on every workflow.
6. `secrets: inherit` is the standard caller pattern for passing environment secrets.
7. Adding `required: true` to an existing input is a breaking change — use `required: false` + `default:`.

## Before Submitting a PR

- [ ] `make lint` passes (actionlint)
- [ ] All existing `inputs:` / `outputs:` / `secrets:` interfaces unchanged, or all consumers updated
- [ ] New secrets documented in `docs/WORKFLOWS.md` and consumer repo maintainers notified
- [ ] Action versions pinned to tag or SHA

## Prompts

AI prompts for development tasks are in `prompts/`:

- `prompts/dev/` — implement or modify reusable workflows
- `prompts/architect/` — cross-repo CI/CD architecture
- `prompts/code_review/` — security and backward compatibility review
- `prompts/tester/` — validate workflows for all consumers
- `prompts/docs/` — document workflows for consumer developers
