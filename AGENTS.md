# kriegerdataforge-cicd — Agent Quick-Start

## App Vision & Purpose

**Centralized shared GitHub Actions workflow library** for the KriegerDataForge ecosystem.
All other KriegerDataForge repos call workflows from this repo rather than maintaining
their own CI/CD logic. This is the single source of truth for shared pipelines, deployment
scripts, security scans, and build automation.

Consumer repos reference workflows here with:
```yaml
uses: Needless2Say/kriegerdataforge-cicd/.github/workflows/<workflow>.yml@main
```

**Consumer repos:**
- `fitness-app-frontend` — Next.js frontend (Vercel deploy)
- `tiffanys-space` — Next.js e-commerce frontend (Vercel deploy)
- `kriegerdataforge` — FastAPI backend (Vercel serverless + Docker)
- `arthurs-portfolio` — Next.js portfolio (Vercel deploy)
- `kriegerdataforge-terraform` — Infrastructure as code (Terraform + Vercel provider)

**Categories of shared workflows this repo owns:**
- Linting and code quality (ESLint, Ruff, mypy, actionlint, tflint)
- Testing (Jest, pytest, Terratest)
- Security scanning (CodeQL, Trivy, Checkov)
- Building and Docker image builds
- Deployment (Vercel preview + production, Docker Hub push)
- Infrastructure validation (Terraform plan/apply)

## Tech Stack

- GitHub Actions (YAML workflows, `workflow_call` triggers)
- Composite actions (`.github/actions/`)
- Shell scripts · Docker

## Read Before You Code

- `docs/` — workflow catalog and consumer integration guides
- `README.md` — project overview and how consumer repos reference these workflows

## Critical Rules

1. Never commit secrets — use `${{ secrets.NAME }}` exclusively.
2. Pin all third-party action versions to a commit SHA — never `@main` or `@latest`.
3. All workflows intended for external use must have an `on: workflow_call:` trigger.
4. Treat every workflow change as a **breaking change candidate** — all consumer repos call these.
5. Set minimum required permissions using the `permissions:` block on every workflow.
6. Never use `pull_request_target` with an untrusted code checkout.
7. Use GitHub Environments (`environment:`) for all production deployment jobs.
8. Adding a `required: true` input is a breaking change — always `required: false` + `default:` or coordinate with all consumers.

## Commands

```bash
make lint       # actionlint — validate all workflow YAML
make check-all  # run all local checks
```

## Prompts

AI prompts for development tasks are in `prompts/`:

- `prompts/dev/` — implement new or modify existing reusable workflows
- `prompts/architect/` — cross-repo CI/CD architecture design
- `prompts/code_review/` — review for correctness, security, and backward compatibility
- `prompts/tester/` — validate workflows behave correctly for all consumers
- `prompts/docs/` — document workflows for consumer repo developers
