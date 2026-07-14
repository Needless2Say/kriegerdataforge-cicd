# Reports triage — trigger operations guide

How the ecosystem's AI report triage gets FIRED (reports-ecosystem epic Wave 4, ADR D-010).
The pipeline itself — PII redaction, AI clustering, GitHub issue + board-item creation — runs
**in-process in each app** via the `kdf_reports` package; this repo only rings the doorbell:
`scripts/trigger_triage.py` POSTs each app's `X-Cron-Secret`-gated `POST /reports/triage/cron`
endpoint, driven by `scripts/reports_registry.json`. Orchestration lives in GitHub Actions (not
Vercel cron / a cloud scheduler) by owner decision — it must survive a future cloud move.

## The moving parts

| Piece | What it is |
| --- | --- |
| `scripts/reports_registry.json` | One entry per (app_slug, environment): `base_url`, `cron_secret_env`, `enabled`. Onboarding an app = a registry edit, never a workflow edit. |
| `scripts/trigger_triage.py` | The engine: selection (`enabled` / `all` / explicit slugs), all-secrets-resolve-before-first-POST, per-app result aggregation, metadata-only output. `--dry-run` prints the plan without firing. |
| [`trigger-reports-triage.yml`](../reference/WORKFLOWS.md) | The weekly schedule (Mon 09:23 UTC → `--apps enabled --environment prod`) + `workflow_dispatch` for manual runs. **Ships disarmed** — see below. |
| `ops:triage-reports` issue form | The owner's run-now button ([`ops-triage-reports.yml`](../reference/WORKFLOWS.md), D-002 pattern): dry-run/execute, dev/prod, result commented on the issue. |
| `REPORTS_CRON_SECRET_FITNESS_APP` / `_TIFFANYS_SPACE` | cicd repo secrets — caller-side **copies** of each app's `REPORTS_CRON_SECRET`. Authoritative value is Terraform app-side ([`SECRET_ROTATION.md` §8.13a](SECRET_ROTATION.md)). |

## Disabled at birth — and how to arm it

The schedule is a no-op until the owner deliberately arms BOTH layers (plan directive 8):

1. **`RUN_REPORTS_TRIAGE` repo variable** (Settings → Secrets and variables → Actions →
   Variables): unset by default → scheduled runs skip. Set to `true` to arm the workflow.
2. **Per-app `enabled` flag** in `scripts/reports_registry.json`: every entry ships
   `enabled: false`, and scheduled runs select `--apps enabled` — so even an armed schedule
   fires nothing until an entry is flipped to `true` (a reviewed registry edit).

Manual runs (dispatch or the issue form) do **not** require `RUN_REPORTS_TRIAGE` — you must be
able to verify the pipeline before arming the schedule. Scheduled runs always target **prod**
(that's where user reports accumulate); dev exists for verification.

## First-time wiring checklist (per app)

1. **App side (terraform repo):** set `reports_cron_secret` in the app module's tfvars — use
   the SAME value in the dev and prod environment roots (one cicd copy serves both) — and
   `terraform apply`. Until then the endpoint answers **503** (PL-056 fail-closed).
2. **Deploy the backend** so the deployed build actually has the `/reports` routes (a merged
   adoption PR isn't live until the owner dispatches a deploy — the registry notes record that
   both tiffanys deployments predated the module as of 2026-07-14).
3. **cicd side:** paste the same value into the matching `REPORTS_CRON_SECRET_*` repo secret via
   the `ops:rotate-secrets` paste flow (§8.13a). Until then the engine refuses to fire.
4. **Registry:** confirm the entry's `base_url` (fitness entries ship `TODO_` placeholders —
   fill from the Vercel dashboard → project → Domains; the fitness dev project additionally
   sits behind Vercel deployment protection, which must be disabled or bypassed before the
   trigger can reach it).
5. **Verify:** issue form → Apps = the slug, Environment = `dev`, Mode = `dry-run` (plan +
   secret presence), then Mode = `execute`. Expect `accepted (202)` with batch counters — a
   quiet app is `total_reports=0` and still green.
6. **Arm (when wanted):** flip the registry entry to `enabled: true` in a PR, and set
   `RUN_REPORTS_TRIAGE=true` once.

## Failure semantics (deliberate)

- **POSTs are never status-retried.** The engine's session retries statuses only for
  GET/PUT/HEAD, so a `502`-that-actually-triaged can never double-fire a batch. Re-runs are
  always manual (re-dispatch / re-label); the app's PL-134 concurrency guard makes even a true
  double-fire safe (the second run answers `409`).
- **All selected secrets resolve before the first POST** — a mis-wired run fires nothing,
  never half of a fan-out.
- **Per-app failures aggregate**: one app's failure doesn't stop the others; the run exits
  non-zero with a `RESULT: ok=N failed=M` line.
- **A red scheduled run means "look", not "retry loop"**: the engine's status interpretations
  (401 stale secret copy, 503 app-side secret unset, 409 already running, 429 AI rate limit,
  207 partial GitHub writes) say exactly what to fix; then re-fire via the issue form.

## Security posture

- **Metadata-only output (unit-tested invariant):** success output echoes only whitelisted
  scalar batch counters (`id`, `status`, `total_reports`, `clusters_created`, `issues_opened`,
  `model_name`, `prompt_version`); non-2xx statuses map to fixed local interpretations.
  Response **bodies are never printed** — cluster payloads / `error_message` can carry user
  report content, which must not leak into public Actions logs or issue comments. That
  invariant is what makes tee-ing engine output into issue comments safe.
- **Secret values never appear** in output (also unit-tested); they flow env → the
  `X-Cron-Secret` header, nothing else. Connection-error output prints the exception TYPE
  only — exception text can embed request details.
- **Registry `base_url`s are identity-verified before first use** (a cron secret POSTed to a
  look-alike host would leak it): the tiffanys URLs were verified to serve the Tiffany's Space
  openapi; the fitness URLs ship as `TODO_` placeholders precisely because their real domains
  carry Vercel-assigned suffixes and could not be derived — never guess a `base_url`.
- Executing against **prod** via the issue form requires the explicit Confirm dropdown (real
  GitHub issues + AI spend); dev and dry-run don't.

## Rotation

`REPORTS_CRON_SECRET_*` is dual-store: **rotate the Terraform app-side value first** (tfvars →
`terraform apply`), then paste the same value into the cicd copy — the full recipe is
[`SECRET_ROTATION.md` §8.13a](SECRET_ROTATION.md). Order matters: rotating only one side turns
every subsequent trigger into a `401` until the other side catches up.

## Related

- [`docs/design/reports-ecosystem.md`](../design/reports-ecosystem.md) — the cicd-side design
  decisions (trigger topology, auth model, W4 notes).
- [`PROJECTS_BOARDS.md`](PROJECTS_BOARDS.md) — where the created tickets land.
- Epic tracker: `kriegerdataforge/docs/epics/reports-ecosystem-standard-{PLAN,LOG}.md`.
