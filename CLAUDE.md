# kriegerdataforge-cicd — Agent Quick-Start

## App Vision & Purpose

**Centralized shared GitHub Actions workflow library** for the KriegerDataForge ecosystem.
All other KriegerDataForge repos call workflows from this repo rather than maintaining
their own CI/CD logic. This is the single source of truth for all deployment pipelines.

Consumer repos reference workflows here with:
```yaml
uses: Needless2Say/kriegerdataforge-cicd/.github/workflows/<workflow>.yml@main
```

## Implemented Workflows

| File | Purpose | Called by |
|---|---|---|
| `cd-nextjs-vercel.yml` | Deploy Next.js app to Vercel | `fitness-app-frontend`, `tiffanys-space`, `arthurs-portfolio` |
| `cd-python-vercel.yml` | Deploy FastAPI backend to Vercel + optional Alembic migrations | `kriegerdataforge` |
| `cd-terraform.yml` | `terraform plan` + `terraform apply` | `kriegerdataforge-terraform` |
| `issue-create-repo.yml` | Auto-provision new repos from templates on issue label | triggered internally |

See `docs/WORKFLOWS.md` for the full catalog: calling syntax, inputs, secrets, and examples.

## Deployment Model

**All deploys are manual** — triggered via `workflow_dispatch` in the GitHub Actions UI.
There are **no automatic deploys on push**. Vercel git auto-deploy is disabled in Terraform.

**Environment gate flow:**
1. Developer triggers CD workflow manually
2. GitHub pauses — sends approval notification to required reviewers
3. Reviewer approves in GitHub UI
4. Environment secrets are loaded and the deploy runs

**Approval model:**

| Environment | Reviewers | Branch restriction |
|---|---|---|
| `development` | Owner + designated collaborators | `main` only |
| `production` | Owner only | `main` only |
| `infrastructure` | Owner only | `main` only |

**Credential isolation:** `VERCEL_TOKEN`, `DB_DATABASE_URL`, and all deploy credentials
live only in GitHub Environment secrets. Collaborators cannot access them and cannot
deploy locally.

## Local Development

Local dev uses Docker — no Vercel credentials needed:
```bash
make docker-up   # in the consumer repo
```
There is no path to deploy locally. The Vercel CLI has no token outside GitHub Environments.

## Tech Stack

- GitHub Actions (YAML workflows, `workflow_call` triggers)
- Shell scripts
- Vercel CLI (`npx vercel --prod --yes`)
- Terraform `~1.9` + hashicorp/setup-terraform

## Read Before You Code

- `docs/WORKFLOWS.md` — full workflow catalog: inputs, secrets, calling syntax, consumer table
- `docs/MANUAL_SETUP.md` — environment setup, secrets configuration, PAT setup

## Critical Rules

1. Never commit secrets — use `${{ secrets.NAME }}` exclusively.
2. Pin all third-party action versions to a specific tag (e.g. `@v6`) — never `@main` or `@latest`.
3. All deployment workflows must use `environment:` to activate the GitHub Environment gate.
4. Treat every change to an existing workflow as a **breaking change candidate** — all consumer repos call these.
5. Set minimum required permissions using `permissions:` on every workflow.
6. Never use `pull_request_target` with an untrusted code checkout.
7. Adding a `required: true` input is a breaking change — use `required: false` + `default:` or coordinate with all consumers.
8. `secrets: inherit` is the standard pattern for passing environment secrets from caller to reusable workflow.

## Commands

```bash
make lint       # actionlint — validate all workflow YAML
make check-all  # run all local checks
```

## Prompts

AI prompts for development tasks are in `prompts/`:

- `prompts/dev/` — implement new or modify existing reusable workflows
- `prompts/architect/` — cross-repo CI/CD architecture design; also general KDF ecosystem architect prompts
- `prompts/code_review/` — review for correctness, security, and backward compatibility
- `prompts/tester/` — validate workflows behave correctly for all consumers; universal test creator
- `prompts/docs/` — document workflows for consumer repo developers
- `prompts/prompt_generators/` — blank meta-prompt template + filled-in generator requests

## AI Agents (Brainstorm / Skeleton)

`agents/` contains a skeleton for future AI-driven agent workflows — not yet implemented.
See `agents/README.md` for the vision and planned structure.

- `agents/workflows/_ai-agent-template.yml` — skeleton GitHub Actions workflow for AI agents
- `agents/context/_agent-context-template.md` — template for per-agent context docs
