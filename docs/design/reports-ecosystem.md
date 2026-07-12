# Design — the reports-ecosystem standard (GitHub Projects + AI bug reporter)

> **Status:** In progress (Wave 1) · **ADR:** D-010 (this repo's changelog) · **Epic tracker:**
> `kriegerdataforge/docs/epics/reports-ecosystem-standard-PLAN.md` (+ `-LOG.md`) — the hub owns
> the cross-repo tracking; this doc owns the cicd-side design decisions.

## Problem

The AI bug reporter (user submits bug/feedback → PII-redact → AI clusters → GitHub issue +
Projects v2 item) is fully built and deployed — but only inside `fitness-app-backend/api/reports/`,
only for the fitness board, triggered only by an admin click. Tiffany's report UI is broken (its
backend never got the module), no other repo can adopt the feature without copy-paste, and the
ecosystem has no standard ticket boards for developers (or the first external collaborator) to
work from.

## Decision (owner-approved, 2026-07-12)

Promote it to an ecosystem standard in 7 waves (see the hub tracker for the full plan):

1. **Boards: per-app + infra (~6), user-owned Projects v2**, provisioned by a cicd engine
   (`scripts/provision_projects.py` + `scripts/projects_registry.json`) behind an ops-console
   form (`ops:provision-projects`, D-002 pattern). Registry-driven, check/execute, idempotent,
   adopt-by-title (or pinned `existing_node_id`) — the live Fitness board is adopted, never
   re-created.
2. **Per-app reports modules** via a certified Python package (`kriegerdataforge-reports-sdk`,
   import `kdf_reports`) extracted from fitness-be; each app backend owns its own `rpt_*` tables
   and `/reports` endpoints. A certified npm package (`@kriegerdataforge/report-form`, private
   GitHub Packages) carries the frontend widget.
3. **Triage trigger lives in GitHub (cloud-agnostic)**: a cicd scheduled workflow POSTs to each
   app's `X-Cron-Secret`-gated `/reports/triage/cron` endpoint; AI + redaction + GitHub writes
   stay in-process in the app. Ships **disabled** (`RUN_REPORTS_TRIAGE` unset + per-app
   `enabled:false`); when armed: weekly, Monday early morning.
4. **Auth is App-first everywhere.** ONE GitHub App, installed account-wide: CI/CD mints
   short-lived installation tokens for package downloads and for board provisioning.
   `GH_PACKAGES_PAT` (full read, all repos) serves only local dev + Vercel builds. For board
   provisioning, a staged classic PAT (`SECRET_VALUE_NEW`, `project`+`repo`) is the documented
   fallback iff the GraphQL API refuses App tokens for user-owned ProjectsV2 — the engine probes
   and switches with an explicit note, and the PAT is revoked after the run.

## Engine design notes (`provision_projects.py`)

- **Modeled on `distribute_kit.py`** (registry fan-out, check/execute) with `rotate_secret.py`'s
  per-target error aggregation. GraphQL via `common/http.py::build_session()` — POSTs are never
  status-retried by design; every mutation is guarded by an existence read, so a failed run is
  safely re-runnable rather than risking duplicate boards on a 502-that-succeeded.
- **No `viewer` dependency**: App installation tokens have no GraphQL viewer, so the owner login
  comes from `PROJECTS_OWNER` (defaults to the repository owner) and boards resolve via
  `user(login:)`.
- **Deliberate API limits, reported not forced:** the built-in **Status** field's options and
  **views** are not reliably API-manageable — both modes diff Status against the registry's
  `status_options` and print exactly what to add; option edits on existing custom fields are also
  manual (editing options via the API risks detaching items' selected values). One-time UI
  recipes live in `docs/guides/PROJECTS_BOARDS.md`.
- **Collaborator invites are best-effort** (`updateProjectV2Collaborators` support for user-owned
  projects varies) — failures are warnings with a manual-invite pointer, never run failures.
- **Field schema** (identical on all 6 boards): Status (built-in; target options Inbox / Triage /
  Backlog / In Progress / In Review / Done), Priority (P0–P3), Type (Bug / Feedback / Feature /
  Chore / Docs / Infra), Repo (derived per board from its member repos), Severity (Critical /
  High / Moderate / Minor / N/A — mirrors the reports module's `ReportSeverity`). `Inbox` is the
  landing Status the reports package's v0.2.0 field-setting will use.

## Relationship to `agents/`

`agents/README.md` brainstormed an **issue-triage-agent** (GitHub-issue-event-driven, direct
Anthropic API via `ANTHROPIC_API_KEY`). This epic supersedes that concept for the bug-report
domain: triage runs **in-process in each app** (GitHub Models via the app's own credentials, PII
redaction before egress) and cicd only schedules it. The `agents/` skeleton remains for the other
agent concepts (PR review, docs, changelog); its issue-triage row should be considered closed by
D-010.

## Secrets / config surface (cicd side)

| Item | Kind | Notes |
| --- | --- | --- |
| `SECRET_VALUE_NEW` | existing staging slot | fallback classic PAT for provisioning only; revoke after |
| `REPORTS_CRON_SECRET_FITNESS_APP` / `_TIFFANYS_SPACE` | repo secrets (Wave 4) | cicd-side copies; authoritative value is Terraform-owned app-side — rotate there, paste here |
| `RUN_REPORTS_TRIAGE` | repo variable (Wave 4) | unset at birth = weekly schedule disabled |

Board **node ids are metadata, not secrets** — they appear in run summaries/issue comments and get
wired into each app's `GH_REPORTS_*PROJECT_ID` env.

## Alternatives considered

- **One board per repo (14+)** — rejected: the shipped reporter routes per *app* (one
  `project_node_id` per app slug); fe/be work for one product would split across two boards; more
  grooming surface for zero routing benefit.
- **Provisioning via a long-lived Projects-scoped PAT** — rejected: App-first keeps zero new
  long-lived credentials; the classic PAT exists only as a staged, revoked-after fallback.
- **Central reports service (keep all apps' reports in fitness-be)** — rejected: per-client
  audience isolation means other apps' JWTs are refused by fitness-be; per-app modules also make
  template bundling possible.
- **Vercel cron as the triage scheduler** — rejected by owner decision: orchestration must live
  in GitHub so it survives a future GCP (or multi-cloud) migration.
