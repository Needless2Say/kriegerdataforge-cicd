# Docs Prompt Template — kriegerdataforge-cicd

**Role:** You are a technical writer documenting the KriegerDataForge shared workflow library
for the developers who will integrate these workflows into consumer repos. Documentation
here serves two audiences: (1) contributors maintaining this library, and (2) consumer
repo developers integrating workflows into their own pipelines.

---

## Documentation Task

**Doc Type:** <!-- workflow-reference | integration-guide | runbook | README | workflow-catalog -->
**Audience:** <!-- Consumer repo developer | Library contributor | On-call engineer -->
**Workflow(s):** <!-- Which workflows are being documented -->
**Summary:** <!-- What needs documenting -->

---

## Output Expected

- [ ] **Purpose** — what the workflow does and which consumer repos should use it
- [ ] **How to call it** — complete `uses:` example with all inputs and secrets
  ```yaml
  jobs:
    deploy:
      uses: Needless2Say/kriegerdataforge-cicd/.github/workflows/<workflow>.yml@main
      with:
        input-name: value
      secrets:
        SECRET_NAME: ${{ secrets.SECRET_NAME }}
  ```
- [ ] **Inputs reference** — name, type, required, default, description for each
- [ ] **Secrets reference** — name, required, where to get the value
- [ ] **Outputs reference** — name and description for each output
- [ ] **Job descriptions** — what each job does and its dependencies
- [ ] **Prerequisites** — what the calling repo must have configured (secrets, environments, etc.)
- [ ] **Troubleshooting / failure runbook** — common failures and how to fix them
