# Design — the reports-ecosystem standard (GitHub Projects + AI bug reporter)

> **Status:** Delivered (epic close-out D-011, kit v1.4.0) · **ADR:** D-010 (this repo's changelog) · **Epic tracker:**
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
4. **Auth is App-first for PYTHON package downloads; a short-lived classic PAT for board
   provisioning; a dedicated classic PAT for npm.**
   ONE GitHub App, installed account-wide, mints short-lived installation tokens for the pip
   `git+https` installs; `GH_PACKAGES_PAT` (fine-grained, full read) serves only local dev +
   Vercel builds on the Python side. **npm is the second exception (W3 spike, docs-verified
   2026-07): GitHub Packages accepts ONLY classic PATs or the Actions `GITHUB_TOKEN`** — it
   rejects fine-grained PATs (so `GH_PACKAGES_PAT` can never serve npm) and GitHub Apps have no
   Packages permission at all (the planned W3.5 "App-token npm plumb" is not viable). The npm
   model is therefore: publish from the package repo with its own `GITHUB_TOKEN`
   (`packages:write`, zero secrets); consume via **`GH_NPM_TOKEN`** (classic, `read:packages`
   only — registry entry + §8.2a recipe) or, for consumer CI, a zero-secret per-repo
   **Actions-access grant** on the package. The GH-Packages scope must equal the repo owner, so
   the widget publishes as `@needless2say/report-form` until the org move.
   **Board provisioning is the exception (resolved W1 finding, 2026-07-12):** neither a GitHub App
   token nor a fine-grained PAT can create/modify user-owned Projects v2 — GitHub exposes a Projects
   permission only for organizations, so on a personal account `createProjectV2` on a user `ownerId`
   is refused ("does not have permission to create projects"). Board creation needs a **classic** PAT
   with the `project` scope acting as the owner, so the owner stages a short-lived classic PAT in
   `SECRET_VALUE_NEW` for the run and revokes it after (`repo` scope optional — only for automatic
   repo-linking, which the engine treats as best-effort). This is why the owner standard "cicd ops
   use `CICD_PAT`" can't apply here — `CICD_PAT` is fine-grained. Runtime board *item* writes by the
   reports app go through the App installation token (a separate path).

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
  Chore / Docs / Infra), Severity (Critical / High / Moderate / Minor / N/A — mirrors the reports
  module's `ReportSeverity`). Repo tracking uses the **built-in Repository field** (auto-populated
  per item) — a custom `Repo`/`Repository` field is *not* created, that name being reserved by
  Projects v2 (caught live 2026-07-12). `Inbox` is the landing Status the reports package's v0.2.0
  field-setting will use.

## App-credential distribution + package-install tokens (W2.5, `distribute_app_secrets.py`)

Wave 2.5 ships the cicd plumbing the package model needs:

- **`ops:distribute-app-secrets`** (owner-requested, plan fact 15) fans this repo's `KDF_APP_ID` /
  `KDF_APP_PRIVATE_KEY` out to every consumer repo carrying `distribute_source_env` in
  `secret_registry.json` — generalizing `ops-setup-e2e.yml`'s fixed 6-repo copy step into a
  registry-driven check/execute engine (`check` = read-only audit of which repos lack copies;
  `execute` = idempotent sealed-box PUTs with per-target error aggregation). The 12-repo target
  list (six E2E-journey repos + `reports-sdk` + `report-form` + the four templates) is the ONE
  authoritative inventory of App-credential copies — and the org-move cleanup checklist. The
  workflow's App token is scoped `secrets:write` to exactly the registry targets (the engine's
  `targets` mode computes the list; nothing is hardcoded in the workflow). Source values are
  shape-checked (`numeric` / `pem`) before the first write so swapped env wiring can't
  half-distribute, and the engine's output never contains a value (unit-tested invariant), which
  is what makes tee-ing its report into the public issue comment safe. It also closes the App-key
  rotation gap: `SECRET_ROTATION.md` §8.3a now fans the new key out **before** the old key is
  deleted (a stale consumer copy would otherwise keep minting from the deleted key and break).
- **`ci-python-*` installs are App-token-first**: the five `needs_sdk_auth` lanes mint a
  short-lived installation token (`contents: read` only, auto-revoked at job end) when the caller
  sets `USE_GITHUB_APP` and holds the distributed pair — `GH_PACKAGES_PAT` remains the fallback
  and the local-dev/Vercel-build credential (the epic's token model). The npm lanes follow in
  W3.5 after the GH-Packages auth spike.
- **Registry deltas:** `GH_PACKAGES_PAT` targets += `kriegerdataforge-reports-sdk` (its CI
  installs `kdf_sdk` as a peer dep); `kit_registry.json` repos += both package repos.

## Triage trigger (W4, `trigger_triage.py`)

The scheduled doorbell for decision 3, deliberately thin — the app owns everything hard:

- **Registry-driven** (`scripts/reports_registry.json`, one entry per app × environment;
  onboarding = a registry edit, AGENTS.md rule 12) with selection modes `enabled` (the
  scheduled default), `all`, and explicit slugs. **Disarmed twice over at birth**: the schedule
  job requires the (unset) `RUN_REPORTS_TRIAGE` repo variable AND per-entry `enabled: true`;
  manual dispatch / the `ops:triage-reports` issue form need neither, so verification precedes
  arming. Scheduled runs always target prod.
- **POSTs are never status-retried** (`build_session` retries statuses only for GET/PUT/HEAD):
  a `502`-that-actually-triaged must not double-fire a batch — re-runs are manual, and the
  app-side PL-134 concurrency guard (`409`) absorbs true double-fires. All selected cron
  secrets resolve BEFORE the first POST (a mis-wired run fires nothing, never half a fan-out);
  per-app failures aggregate. A quiet week is green (`202`, `total_reports=0`).
- **Metadata-only output (unit-tested invariant):** success echoes a whitelist of scalar batch
  counters; non-2xx statuses map to fixed local interpretations and response bodies are never
  echoed — cluster payloads / `error_message` can carry user report content, which must not
  reach public Actions logs or issue comments (this is what makes the ops form's tee-to-comment
  safe). Connection errors print the exception type only.
- **`base_url` identity is a security property**: the secret goes wherever the URL points, so
  a look-alike host would capture it. The tiffanys URLs were committed only after verifying
  they serve the Tiffany's Space openapi (the bare subdomain IS the prod project; `-dev` is
  dev); the fitness URLs ship as engine-refused `TODO_` placeholders because their real Vercel
  domains carry random suffixes (the `kriegerdataforge-backend-gilt` pattern) and were not
  derivable — never guess a base_url. The fitness dev project additionally sits behind Vercel
  deployment protection (SSO), recorded in the registry notes.
- **Dual-store cron secrets** (`REPORTS_CRON_SECRET_FITNESS_APP` / `_TIFFANYS_SPACE`):
  authoritative value = Terraform app-side (`reports_cron_secret`, same value in both env
  roots so ONE cicd copy serves both); rotate app-side first, then paste the cicd copy
  (§8.13a). Registry entries are ordinary paste-kind rotation entries targeting this repo.

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
| `KDF_APP_ID` / `KDF_APP_PRIVATE_KEY` copies | repo secrets in 12 consumer repos (W2.5) | fanned out by `ops:distribute-app-secrets`; source of truth = this repo's secrets; registry target list = org-move cleanup checklist |
| `REPORTS_CRON_SECRET_FITNESS_APP` / `_TIFFANYS_SPACE` | repo secrets (Wave 4) | cicd-side copies; authoritative value is Terraform-owned app-side — rotate there, paste here |
| `RUN_REPORTS_TRIAGE` | repo variable (Wave 4) | unset at birth = weekly schedule disabled |

Board **node ids are metadata, not secrets** — they appear in run summaries/issue comments and get
wired into each app's `GH_REPORTS_*PROJECT_ID` env.

## Alternatives considered

- **One board per repo (14+)** — rejected: the shipped reporter routes per *app* (one
  `project_node_id` per app slug); fe/be work for one product would split across two boards; more
  grooming surface for zero routing benefit.
- **Provisioning via a long-lived Projects-scoped PAT** — rejected: no new *long-lived* credential
  is needed. The classic PAT is short-lived and revoked after each provisioning run; App tokens
  cover package downloads and the read-only `check`.
- **Central reports service (keep all apps' reports in fitness-be)** — rejected: per-client
  audience isolation means other apps' JWTs are refused by fitness-be; per-app modules also make
  template bundling possible.
- **Vercel cron as the triage scheduler** — rejected by owner decision: orchestration must live
  in GitHub so it survives a future GCP (or multi-cloud) migration.
