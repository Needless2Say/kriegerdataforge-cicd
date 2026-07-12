# GitHub Projects boards — catalog + operations guide

The ecosystem's ticket boards (reports-ecosystem epic, ADR D-010). Provisioned by
`scripts/provision_projects.py` from `scripts/projects_registry.json` via the
**`ops:provision-projects`** issue form; this guide covers the board catalog, the one-time manual
steps the API can't do, and how to harvest/wire the node ids.

## The catalog

| Board | Member repos | Purpose |
| --- | --- | --- |
| **KDF — Fitness** | fitness-app-frontend, fitness-app-backend | The fitness product. AI bug-report tickets for `fitness_app` land here. First collaboration board (the friend works here). |
| **KDF — Tiffany's Space** | tiffanys-space, tiffanys-space-backend | The tiffanys product. AI tickets for `tiffanys_space` land here (Wave 2+). |
| **KDF — Platform** | kriegerdataforge, kriegerdataforge-auth-ui, kriegerdataforge-sdk, kriegerdataforge-reports-sdk, kriegerdataforge-report-form | The SSO/identity platform + the certified packages. |
| **KDF — Infra** | kriegerdataforge-cicd, kriegerdataforge-terraform | Control plane + IaC. |
| **KDF — Portfolios** | arthurs-portfolio, kriegerdataforge-portfolio | The portfolio sites. |
| **KDF — Templates** | the 4 `kriegerdataforge-template-*` repos | Template fleet upkeep. |

Issues from ANY repo can be added to any board — repo linking only improves the board's pickers.
Membership is a partition: every ecosystem repo appears on exactly one board (tested in
`scripts/tests/test_provision_projects.py`).

## The standard field schema (every board)

| Field | Kind | Options | Who sets it |
| --- | --- | --- | --- |
| Status | built-in single-select | Inbox · Triage · Backlog · In Progress · In Review · Done | humans; the AI reporter sets **Inbox** from package v0.2.0 |
| Priority | custom single-select | P0 · P1 · P2 · P3 | humans only (deliberate) |
| Type | custom single-select | Bug · Feedback · Feature · Chore · Docs · Infra | humans; AI sets it from the report type (v0.2.0) |
| Repo | custom single-select | the board's member repo short names | humans; AI sets it (v0.2.0) |
| Severity | custom single-select | Critical · High · Moderate · Minor · N/A | AI sets it from `ReportSeverity`; humans adjust |

## Running the provisioner

1. Open the **"Ops · Provision Projects boards"** issue form → pick boards + mode → submit →
   add the **`ops:provision-projects`** label.
2. Run **check** first: a read-only drift report comments on the issue.
3. Run **execute**: creates missing boards/fields, links repos, adopts anything that already
   exists (the live Fitness board is adopted by title — if yours is titled differently, rename it
   in the UI first or pin its node id in the registry's `existing_node_id`).
4. **Harvest the node ids** from the issue comment (`title: PVT_…` lines). They're metadata, not
   secrets. Wire them into each app's env as `GH_REPORTS_PROJECT_ID` (Wave 2: tiffanys via
   Terraform tfvars; fitness keeps its existing value if the board was adopted).

**Auth (resolved W1 finding):** GitHub App installation tokens can *read* user-owned ProjectsV2 but
**cannot create or modify them** (`createProjectV2` on a user account is refused). So `check` runs
on the App token alone, but **`execute` needs a staged classic PAT**: create a short-lived **classic
PAT** with `project` + `repo` scopes → stage it in the `SECRET_VALUE_NEW` repo secret → re-add the
`ops:provision-projects` label with Mode=`execute` → the engine uses it for the whole run → **revoke
the PAT** and clear `SECRET_VALUE_NEW` afterward. (Runtime issue/board *item* writes by the reports
app are unaffected — the App can add items to a board it's already been granted.)

## One-time manual steps (the API can't do these)

The engine prints exactly which of these each board still needs (`~ manual:` lines).

### Reshape the built-in Status options

Board → ⋯ menu → *Settings* → *Status* field → edit options to exactly:
`Inbox`, `Triage`, `Backlog`, `In Progress`, `In Review`, `Done` (drag to that order; map any
existing "Todo" items to `Backlog` before deleting the old option so items keep a status).

### Create the standard views (per board)

1. **Board by Status** — *New view* → Board layout → group by `Status`. Default view.
2. **AI Inbox** — *New view* → Table layout → filter `label:ai-triaged` → sort by `Severity`.
   This is the triage queue the AI reporter feeds.
3. **By Priority** — *New view* → Board layout → group by `Priority` → filter `-status:Done`.

### Invite a collaborator (if the API invite warned)

Board → ⋯ menu → *Settings* → *Manage access* → invite by username → role **Write**. The friend
also needs repo-collaborator access on the board's member repos to see their issues (Wave 5
onboarding checklist).

### Auto-add workflows (optional, recommended on Fitness + Tiffanys)

Board → ⋯ menu → *Workflows* → enable **Auto-add to project** for each member repo with filter
`is:issue,pr` — new issues then appear on the board without the reporter/developer adding them
manually. (The AI reporter adds its issues explicitly via the API, so this is for human-filed
issues.)

## How tickets flow in (once the epic lands)

1. A user submits a bug/feedback report in an app → stored `pending` in that app's own `rpt_*`
   tables (PII-redacted).
2. Weekly (Monday, once armed) — or on the owner's `ops:triage-reports` run, or an admin's manual
   trigger — the app's triage endpoint clusters pending reports with AI and opens **one GitHub
   issue per cluster** in the app's repo, labeled `ai-triaged` + severity/category labels.
3. The issue is added to the app's board (Status=Inbox + Severity/Repo/Type from package v0.2.0).
4. Developers groom Inbox → Triage/Backlog on the board; the report rows flip `linked` and
   submitters can be followed up via the admin endpoints.
