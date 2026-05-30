# Tester Prompt Template — kriegerdataforge-cicd

**Role:** You are a CI/CD test engineer validating the KriegerDataForge shared workflow library.
Since these workflows are called by multiple consumer repos, testing must verify both the
workflow itself and the calling contract from each consumer's perspective.

**Deployment model context:**
- All deploys are `workflow_dispatch` only — no auto-deploy on push
- Every deploy job uses `environment:` — workflow pauses for required reviewer approval before secrets are loaded
- Consumer caller pattern: `secrets: inherit`
- `VERCEL_TOKEN`, `DB_DATABASE_URL`, and all credentials live only in GitHub Environment secrets

**Implemented workflows:**
- `cd-nextjs-vercel.yml` — `fitness-app-frontend`, `tiffanys-space`, `arthurs-portfolio`
- `cd-python-vercel.yml` — `kriegerdataforge` (FastAPI + Alembic)
- `cd-terraform.yml` — `kriegerdataforge-terraform`
- `issue-create-repo.yml` — internal

---

## Test Task

**Workflow / Action:** <!-- What to test or validate -->
**Consumer repos in scope:** <!-- fitness-app-frontend | tiffanys-space | kriegerdataforge | arthurs-portfolio | kriegerdataforge-terraform | all -->
**Test Type:** <!-- actionlint | dry-run | act (local runner) | manual-dispatch | integration -->

---

## Workflow Validation

- [ ] `make lint` / `actionlint` passes with no errors
- [ ] `on: workflow_call:` trigger is present (for externally-callable workflows)
- [ ] All declared `inputs:` have descriptions and sensible defaults
- [ ] All declared `outputs:` are correctly wired
- [ ] All required secrets documented
- [ ] `environment:` is present on deployment jobs

## Consumer Contract Validation

- [ ] Example `uses:` calling syntax works from at least one consumer repo
- [ ] Caller uses `secrets: inherit` — no individually-passed secrets unless intentional
- [ ] No secrets required that a consumer wouldn't have in their GitHub Environment
- [ ] Workflow completes successfully with `on: workflow_dispatch:` manual run
- [ ] No sensitive data in logs (run output reviewed)
- [ ] Environment gate fires and pauses for approval before secrets are loaded

## Security Validation

- [ ] Security checklist in `code_review/_template.md` passes
- [ ] No hardcoded tokens or credentials in any step
