# The reports standard — GitHub Projects boards + the AI bug reporter

**Kit doc (synced to every repo).** This is the ecosystem standard for how user feedback becomes
worked tickets (cicd ADR D-010; epic tracker `kriegerdataforge/docs/epics/reports-ecosystem-standard-*`).
Like `skills.md`, sections marked *(app repos)* only apply where the feature can run — see the
applicability table at the end.

## The pipeline in one paragraph

A user submits a bug/feedback report in-app (the widget) → the app's backend **PII-redacts** it
and stores it in the app's own `rpt_*` tables → a weekly cicd trigger (or an admin click) rings
the app's cron endpoint → the app runs an **in-process AI triage batch** (GitHub Models) that
clusters reports → high-confidence clusters become **GitHub issues** on the app's Projects v2
board, landing **pre-sorted** (Status = `Inbox`, Severity, Type; Priority is always a human
call). Every ecosystem repo's work is tracked on one of the **six standard boards** (catalog:
cicd `docs/guides/PROJECTS_BOARDS.md`).

## The two certified packages *(app repos)*

| Package | What | Pinning |
| --- | --- | --- |
| `kriegerdataforge-reports-sdk` (import `kdf_reports`) | The whole backend: 5 `rpt_*` tables, role-gated `/reports` endpoints, redaction, AI triage, GitHub issue + board writes, `X-Cron-Secret` cron endpoint | `requirements.in`: `@ git+https://…/kriegerdataforge-reports-sdk.git@vX.Y.Z` — **tag-pinned, bump deliberately**. Peer: `kdf_sdk` ≥ the version its import-time guard names. |
| `@needless2say/report-form` (private GH Packages) | The frontend widget: validated form, context capture, no `app_slug` (server stamps it) | `package.json` `^X.Y.Z` + committed `.npmrc`; installs need `GH_NPM_TOKEN` (**classic** PAT, `read:packages` — GH Packages rejects fine-grained/App tokens). |

Never vendor/copy the module source into an app — that is exactly what this standard replaced.

## Adopting in a backend *(app repos)*

1. Dependency line (above) → mount `kdf_reports.router` (template-fastapi gates it behind the
   D-004 flag `FEATURE_REPORTS_ENABLED`, dark by default).
2. **One Alembic revision** copied from the reports-sdk repo's
   `docs/reference/alembic_template_revision.py` (the package owns no Alembic env; `app_slug` is
   born VARCHAR — never a shared enum, never an FK to `kdf_users`).
3. Env block (all fail-closed): `REPORTS_APP_SLUG` (server-stamped identity — inbound `app_slug`
   is ignored), `REPORTS_CRON_SECRET` (empty ⇒ cron endpoint answers **503**), `GH_REPORTS_REPO`,
   `GH_REPORTS_PROJECT_ID` (the board node id — metadata, not a secret),
   `GH_REPORTS_INSTALLATION_ID` + App id/key, `GH_REPORTS_GITHUB_TOKEN` (AI), `AI_*` knobs.
   App-side values are **Terraform-owned**.
4. Seed the repo labels the allow-list applies (`ai-triaged`, `severity-*`) — triage **never
   creates labels** (PL-117).
5. Enroll in the scheduled trigger: an entry in cicd `scripts/reports_registry.json` + the
   `REPORTS_CRON_SECRET_<APP>` cicd-side copy (dual-store; Terraform value is authoritative).
   Runbook: cicd `docs/guides/REPORTS_TRIAGE_OPS.md`. The weekly workflow ships **disarmed**
   (`RUN_REPORTS_TRIAGE` variable + per-entry `enabled:false`).

Consumer reference: reports-sdk `docs/guides/CONSUMER_SETUP.md`; worked examples =
fitness-app-backend, tiffanys-space-backend, template-fastapi (`docs/guides/REPORTS_SETUP.md`).

## Adopting in a frontend *(app repos)*

Dep + `.npmrc` + styles import + jest `transformIgnorePatterns` for the pure-ESM package; submit
through your **BFF proxy** to the backend's `POST /reports` (if the proxy has a path allow-list,
add `/reports` — a missing allow-list entry silently kills the whole pipeline). Docker installs
take `GH_NPM_TOKEN` as a **BuildKit secret mount, never an ARG**. Worked examples =
fitness-app-frontend (`src/features/report/`), tiffanys-space, template-nextjs
(`docs/guides/REPORT_WIDGET.md`).

## Security posture (all repos — do not weaken)

- **PII is redacted before persistence AND before AI egress**; triage trigger/ops output is
  metadata-only — report content never reaches Actions logs or issue comments.
- **`app_slug` is server-stamped** — a client can never file reports as another app.
- **Label allow-list + cap (PL-117)** — AI-suggested labels are filtered server-side; hallucinated
  labels never reach GitHub.
- **Fail-closed everywhere**: settings resolve lazily, so missing required config surfaces on the
  first request (not at boot); unset cron secret ⇒ 503; wrong secret ⇒ 401; the concurrency guard
  (PL-104) makes double-fires safe; GitHub outages can't corrupt a committed batch (PL-134: the
  batch is committed before the best-effort issue phase).
- **Priority is human-only**; the built-in Repository board field auto-populates (never create a
  custom `Repo` field — the name is reserved).

## Where tickets land (every repo)

All 16 repos map to one of six user-owned Projects v2 boards — Fitness, Tiffany's Space,
Platform, Infra, Portfolios, Templates — provisioned/audited by the cicd `ops:provision-projects`
flow (classic-PAT-only on a personal account; see the D-010 W1 finding). Standard fields:
Status (Inbox → … → Done), Priority (human), Type, Severity.

## Applicability by repo type

| Repo type | What applies |
| --- | --- |
| App backends (fitness-be, tiffanys-be) | Full backend adoption + trigger enrollment |
| App frontends (fitness-fe, tiffanys-space) | Widget adoption via the BFF |
| Templates (fastapi / nextjs) | Carry the bundled, dark-by-default integration — keep it compiling, keep it dark |
| Package repos (reports-sdk / report-form) | ARE the standard — changes there follow their own ADR logs and version gates |
| Hub / auth-ui / portfolios / cicd / terraform | Boards only (file + work tickets); no reports pipeline (hub adoption is a review-backlog item) |

## Evolving the standard

Changes to pipeline behavior belong in the **packages** (new tag + consumer bumps), never as
app-side forks. Board/topology/trigger changes go through cicd (registry edits + this doc).
Record decisions as ADRs in the owning repo and update this kit doc in the same wave.
