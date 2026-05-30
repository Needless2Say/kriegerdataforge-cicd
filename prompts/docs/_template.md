# Docs Prompt Template — kriegerdataforge-cicd

**Role:** You are a technical writer documenting the KriegerDataForge shared workflow library
for the developers who will integrate these workflows into consumer repos. Documentation
here serves two audiences: (1) contributors maintaining this library, and (2) consumer
repo developers integrating workflows into their own pipelines.

**Canonical workflow reference:** `docs/WORKFLOWS.md` is the single source of truth for all
workflow calling syntax, inputs, secrets, and consumer integration examples. When documenting
a workflow, the primary output should be an entry in (or update to) `docs/WORKFLOWS.md`.

**Deployment model:** All deploys are manual (`workflow_dispatch` only). Every deploy uses a
GitHub Environment gate. Caller uses `secrets: inherit`. Document this for any deployment workflow.

---

## Documentation Task

**Doc Type:** <!-- workflow-reference | integration-guide | runbook | README | workflow-catalog -->
**Audience:** <!-- Consumer repo developer | Library contributor | On-call engineer -->
**Workflow(s):** <!-- Which workflows are being documented -->
**Summary:** <!-- What needs documenting -->

---

## Output Expected

- [ ] **Purpose** — what the workflow does and which consumer repos should use it
- [ ] **How to call it** — complete `uses:` example with all inputs and `secrets: inherit`
  ```yaml
  jobs:
    deploy:
      uses: Needless2Say/kriegerdataforge-cicd/.github/workflows/<workflow>.yml@main
      with:
        input-name: value
      secrets: inherit
  ```
- [ ] **Inputs reference** — name, type, required, default, description for each
- [ ] **Secrets reference** — name, required, which GitHub Environment it lives in
- [ ] **Outputs reference** — name and description for each output
- [ ] **Job descriptions** — what each job does and its dependencies
- [ ] **Prerequisites** — what the calling repo must have configured (GitHub Environments, secrets, branch restrictions)
- [ ] **Troubleshooting / failure runbook** — common failures and how to fix them
- [ ] **`docs/WORKFLOWS.md` updated** — new or changed workflow entry added to the catalog
