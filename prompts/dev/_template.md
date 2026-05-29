# Dev Prompt Template — kriegerdataforge-cicd

**Role:** You are a CI/CD engineer building and maintaining the KriegerDataForge shared
reusable workflow library. Workflows in this repo are called by `fitness-app-frontend`,
`tiffanys-space`, `kriegerdataforge`, `arthurs-portfolio`, and `kriegerdataforge-terraform`
via `uses: Needless2Say/kriegerdataforge-cicd/.github/workflows/<workflow>.yml@main`.

**Before coding**, read:
- `CLAUDE.md` — full context, consumer repos, critical rules
- `docs/` — workflow catalog and existing interface contracts

---

## Task

**Name:** <!-- e.g., "Add reusable Vercel deploy workflow" -->
**Size:** <!-- 🟢 S | 🟡 M | 🟠 L | 🔴 XL -->
**Type:** <!-- new-workflow | modify-workflow | new-composite-action | bug-fix -->
**Consumer(s):** <!-- Which repos will call this: fitness-app-frontend | tiffanys-space | kriegerdataforge | arthurs-portfolio | kriegerdataforge-terraform | all -->
**Summary:** <!-- One sentence description -->

---

## Workflow Interface

**Trigger:** `on: workflow_call:` <!-- + workflow_dispatch for manual testing? -->

**Inputs:**
```yaml
# inputs:
#   example-input:
#     description: '...'
#     required: false   # NEVER required: true without coordinating with all consumers
#     default: ''
```

**Secrets:**
```yaml
# secrets:
#   EXAMPLE_SECRET:
#     description: '...'
#     required: false
```

**Outputs:**
```yaml
# outputs:
#   example-output:
#     description: '...'
#     value: ${{ jobs.<job-id>.outputs.<output-name> }}
```

---

## Requirements

**Must have:**
- 

**Should have:**
- 

**Could have:**
- 

**Won't have (this task):**
- 

---

## Definition of Done

- [ ] Workflow YAML is valid (`make lint` / `actionlint`)
- [ ] Trigger includes `on: workflow_call:`
- [ ] Secrets referenced as `${{ secrets.NAME }}`, never hardcoded
- [ ] `permissions:` block scoped to minimum required
- [ ] No breaking changes to existing `inputs:` / `outputs:` / `secrets:` (or all consumers updated)
- [ ] At least one consumer repo calling syntax documented in `docs/` or inline comments
- [ ] Production jobs use `environment:` for GitHub Environment gates
