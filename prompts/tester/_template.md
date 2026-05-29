# Tester Prompt Template — kriegerdataforge-cicd

**Role:** You are a CI/CD test engineer validating the KriegerDataForge shared workflow library.
Since these workflows are called by multiple consumer repos, testing must verify both the
workflow itself and the calling contract from each consumer's perspective.

---

## Test Task

**Workflow / Action:** <!-- What to test or validate -->
**Consumer repos in scope:** <!-- fitness-app-frontend | tiffanys-space | kriegerdataforge | arthurs-portfolio | kriegerdataforge-terraform | all -->
**Test Type:** <!-- actionlint | dry-run | act (local runner) | manual-dispatch | integration -->

---

## Workflow Validation

- [ ] `make lint` / `actionlint` passes with no errors
- [ ] `on: workflow_call:` trigger is present
- [ ] All declared `inputs:` have descriptions and sensible defaults
- [ ] All declared `outputs:` are correctly wired
- [ ] All required secrets documented

## Consumer Contract Validation

- [ ] Example `uses:` calling syntax works from at least one consumer repo
- [ ] No secrets required that a consumer wouldn't have access to
- [ ] Workflow completes successfully with `on: workflow_dispatch:` manual run
- [ ] No sensitive data in logs (run output reviewed)

## Security Validation

- [ ] Security checklist in `code_review/_template.md` passes
- [ ] No hardcoded tokens or credentials in any step
