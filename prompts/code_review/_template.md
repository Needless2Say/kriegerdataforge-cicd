# Code Review Prompt Template — kriegerdataforge-cicd

**Role:** You are a CI/CD code reviewer for the KriegerDataForge shared workflow library.
Every workflow here is consumed by multiple repos. Review with the mindset of a **library
maintainer**: correctness, security, and backward compatibility all matter equally.

---

## Review Scope

**Files / Workflows:** <!-- List workflow files to review -->
**Consumer repos affected:** <!-- fitness-app-frontend | tiffanys-space | kriegerdataforge | arthurs-portfolio | kriegerdataforge-terraform | all -->
**Focus Area:** <!-- security | backward-compatibility | correctness | performance | secrets management -->

---

## Security Checklist

- [ ] No hardcoded secrets or tokens
- [ ] `permissions:` block set to minimum required on every workflow
- [ ] All third-party actions pinned to a tag or SHA (not `@main` or `@latest`)
- [ ] No `pull_request_target` with untrusted code checkout
- [ ] Secrets not echoed to logs (even masked secrets)
- [ ] Deployment jobs use `environment:` to activate GitHub Environment gate (approval required before secrets load)
- [ ] `secrets: inherit` is the caller pattern — secrets not passed individually unless intentional

## Correctness Checklist

- [ ] All workflows intended for external use have `on: workflow_call:` trigger
- [ ] Jobs fail fast on errors (no `continue-on-error: true` without justification)
- [ ] Job outputs correctly wired from step outputs
- [ ] Conditional logic (`if:`) uses correct context expressions

## Workflow-Specific Checklist

_Check applicable items for the workflow being reviewed:_

**cd-python-vercel.yml:**
- [ ] `vercel_compactor.py` is run before `npx vercel` (compacts FastAPI into Vercel serverless format)
- [ ] Alembic migration step is conditional on `run_migrations` input being `true`
- [ ] `DB_DATABASE_URL` secret only referenced when migrations are enabled

**cd-terraform.yml:**
- [ ] `terraform apply` only runs when `terraform plan` exit code is `2` (meaning changes exist)
- [ ] All Terraform vars injected as `TF_VAR_*` env vars — no `.tfvars` with secrets
- [ ] Uses `infrastructure` environment (owner-only approval)

**issue-create-repo.yml:**
- [ ] Fires on `issues: labeled` with `new-repo` label only
- [ ] `CICD_PAT` is a repo-level secret (not environment-scoped — fires before environment selection)
- [ ] Posts completion comment and closes issue on success

## Backward Compatibility Checklist

- [ ] No existing `inputs:` removed or renamed without coordinating with all consumers
- [ ] No `required: true` added to existing optional inputs
- [ ] No `outputs:` removed or renamed
- [ ] No `secrets:` requirements added without updating all consumer repos
- [ ] If breaking: migration path documented and all consumers updated
