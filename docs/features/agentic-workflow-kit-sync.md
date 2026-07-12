# Feature — Agentic-workflow kit-sync engine

_Last updated: 2026-07-12 · Status: draft_

## 1. Overview

The **kit-sync engine** distributes the ecosystem's shared **agentic-workflow kit** — the
language-agnostic Markdown that tells every AI/human agent how to work in a KDF repo (`skills.md`,
`WORKFLOW.md`, and `docs/agent/*` standards + templates) — from ONE canonical source
(`kit/common/` in this repo) out to every tenant repo, and keeps each repo's copy in sync. There
is one source of truth (`kit/common/`), one registry of targets
(`scripts/kit_registry.json`), and a Python propagation engine (`scripts/distribute_kit.py`) that
either reports drift (`check`) or opens one review-gated pull request per drifted repo
(`distribute`). It **never auto-merges** — the owner reviews and merges each sync PR. It exists so
that a change to how agents operate is authored once and fans out to ~14 repos as ordinary PRs,
instead of being hand-copied and going stale (ADR **D-001**; see
[`../CHANGELOG_AND_DECISION_LOG.md`](../CHANGELOG_AND_DECISION_LOG.md)).

Unlike the deploy/CI reusable workflows in this repo, the kit-sync engine is **not** called by
tenant repos via `uses:`. The direction is inverted: this repo reaches *into* the tenant repos over
the GitHub API (using a write-scoped token) and opens PRs against them. The only obligation a
consumer repo carries is passive — its version-check must exempt the kit paths so a docs-only sync
PR doesn't fail the strict `VERSION` gate (handled centrally by `scripts/common/check_version.py`;
ADR D-001 option B).

## 2. Architecture & data flow

```
  ┌─────────────────────────── kriegerdataforge-cicd (SOURCE) ───────────────────────────┐
  │                                                                                        │
  │   kit/KIT_VERSION ── v1.2.0 ──┐  (canonical version marker)                            │
  │                               ├── _assert_version_consistency()  (must match)          │
  │   kit/common/docs/agent/KIT_VERSION ── v1.2.0 ──┘  (vendored copy, itself a synced file)│
  │                                                                                        │
  │   kit/common/                       scripts/kit_registry.json                          │
  │     ├ skills.md                       ├ files[]  (12 kit paths, exact)                 │
  │     ├ WORKFLOW.md                     └ repos[]  (14 owner/repo + branch targets)      │
  │     └ docs/agent/{AGENT_OPERATING_STANDARD, DESIGN_AND_EPICS,                          │
  │        DEFINITION_OF_DONE, DOCUMENTATION_STANDARD, KIT_VERSION, templates/*}           │
  │                    │                          │                                        │
  │                    └────────┬─────────────────┘                                        │
  │                             ▼                                                          │
  │              scripts/distribute_kit.py  ──── modes ────►  check  │  distribute         │
  │                             │                                                          │
  │   Triggered by one of three front-ends (D-002 "Ops Console"):                          │
  │     • distribute-kit.yml      workflow_dispatch (mode/only/repos) + weekly cron (check) │
  │     • ops-distribute-kit.yml  issue-form + `ops:distribute-kit` label                  │
  │     • CLI (local)             GH_TOKEN=… python distribute_kit.py check|distribute      │
  │                             │                                                          │
  │   all privileged paths ──► _authorize-owner.yml  (fail-closed owner gate)              │
  │                             │                                                          │
  │   token: GitHub App install token (USE_GITHUB_APP) │ fallback CICD_PAT                 │
  └─────────────────────────────┼──────────────────────────────────────────────────────────┘
                                 │  GitHub REST API (Contents + git refs)
       ┌─────────────┬──────────┼───────────┬─────────────┐            (per drifted repo)
       ▼             ▼          ▼           ▼             ▼
  kriegerdataforge  -sdk   fitness-app-*  tiffanys-*   template-* …   ← for each: compare copy
       │                                                               to kit/common; if drift →
       │  check  →  read-only: fetch each file, diff, print report, exit 1 if any drift
       └  distribute → create branch `chore/kit-sync-<ver>`, PUT drifted files, open ONE PR
                        titled "chore(kit): sync agentic-workflow kit <ver>"  (never merges)
                                 │
                                 ▼
                        consumer repo's version-check SKIPS the PR
                        (check_version.py `_is_kit_only_pr`, ADR D-001 option B)
```

**Cross-repo boundary.** The public contract this feature exposes to the ecosystem is *not* a
`workflow_call` interface. It is (a) the **set of files** the engine treats as canonical
(`kit_registry.json → files[]`) and (b) the **exemption** every consumer's version-check applies to
those same paths. Because `check_version.py` derives its exempt set from the *same*
`kit_registry.json` (`check_version.py:105`), the "what gets synced" list can never drift from the
"what skips the version gate" list. A consumer repo depends only on receiving well-formed,
review-gated PRs; it never calls upstream.

## 3. Key modules

| File | Role | Entry point |
| --- | --- | --- |
| `scripts/distribute_kit.py` | The propagation engine (`check` / `distribute` modes). | `main()` — `scripts/distribute_kit.py:380` |
| `scripts/kit_registry.json` | The registry: `files[]` (synced kit paths) + `repos[]` (targets). | `scripts/kit_registry.json:1` |
| `kit/common/` | Canonical source tree of the 12 synced kit files. | `kit/common/skills.md`, `kit/common/WORKFLOW.md`, `kit/common/docs/agent/…` |
| `kit/KIT_VERSION` | Canonical kit version (`v1.2.0`); read by `_kit_version()`. | `kit/KIT_VERSION:1` |
| `kit/common/docs/agent/KIT_VERSION` | Vendored version marker — itself a synced file; must equal the canonical. | `scripts/distribute_kit.py:86` (`_assert_version_consistency`) |
| `.github/workflows/distribute-kit.yml` | `workflow_dispatch` + weekly cron front-end that runs the engine. | `.github/workflows/distribute-kit.yml:38` (`jobs`) |
| `.github/workflows/ops-distribute-kit.yml` | Issue-form parser front-end, triggered by the `ops:distribute-kit` label. | `.github/workflows/ops-distribute-kit.yml:18` (`jobs`) |
| `.github/ISSUE_TEMPLATE/ops-distribute-kit.yml` | The Ops-Console issue form (mode / target repos / file filter). | `.github/ISSUE_TEMPLATE/ops-distribute-kit.yml:9` (`body`) |
| `.github/workflows/_authorize-owner.yml` | Reusable fail-closed owner-only gate (`workflow_call`, output `authorized`). | `.github/workflows/_authorize-owner.yml:24` (`jobs.verify`) |
| `scripts/common/check_version.py` | Consumer-side kit-only-PR exemption so a sync PR skips the version gate. | `scripts/common/check_version.py:141` (`_is_kit_only_pr`) |
| `scripts/tests/test_distribute_kit.py` | Unit tests for the engine (drift, selection, version consistency, PR flow). | `scripts/tests/test_distribute_kit.py:1` |

**Engine internals worth knowing (all in `scripts/distribute_kit.py`):**

- `compute_drift()` (`:166`) — for each registry file, fetch the repo's copy and compare; a file is
  "drifted" if it is **missing** or its content differs.
- `_normalize()` (`:104`) — comparison ignores CRLF/LF differences, so "byte-identical" is precisely
  "content-identical modulo line endings". (ADR D-003 deliberately softened the guarantee wording to
  "the engine keeps this file byte-identical … drift is flagged and re-synced".)
- `_get_remote_file()` (`:144`) — GitHub Contents API read; returns `(None, None)` on 404 (treated as
  drift/missing).
- `_SESSION` (built by `common/http.py::build_session`) — a shared `requests.Session` with a `urllib3`
  retry adapter: transient GitHub failures (`429`/`500`/`502`/`503`/`504`) and DNS/connection blips are
  retried with exponential backoff, so a single hiccup on a ~14-repo fan-out no longer aborts a repo.
  Retries are limited to **idempotent** methods (GET/PUT) — the branch- and PR-create POSTs are not
  status-retried, so a 502-after-success can't create a duplicate ref/PR; `404` (missing = drift) and
  `422` (ref exists) are never retried. The same session hardens `rotate_secret.py` (GitHub + Vercel).
- `_select_files()` (`:109`) — applies `--only` as a **substring** match on file paths.
- `_select_repos()` (`:118`) — applies `--repos` as a comma-separated **exact** match on `owner/repo`
  or the short repo name (case-insensitive); an empty value selects all. Exactness is deliberate so
  `kriegerdataforge` never fans out to `kriegerdataforge-sdk`.
- `_get_branch_sha()` / `_create_branch()` / `_put_file()` / `_create_pr()` (`:182`–`:248`) — the
  distribute path: branch off the target's default branch, commit each drifted file via the Contents
  API, open a PR. `_create_branch()` treats a 422 ("ref exists") as reuse, so re-running distribute
  for the same version updates the existing `chore/kit-sync-<ver>` branch instead of failing.

## 4. Workflow contract (triggers / inputs / secrets / outputs)

> **Not a `uses:` reusable workflow.** The kit-sync front-ends live in *this* repo and act on the
> other repos over the API. So the "contract" below is the trigger surface, not a
> `uses:`-callable interface. The one genuine `workflow_call` piece is `_authorize-owner.yml`.

### 4a. `distribute-kit.yml` — dispatch + scheduled front-end

`workflow_dispatch` inputs (`.github/workflows/distribute-kit.yml:16`):

| Input | Type | Default | Required | Meaning |
| --- | --- | --- | --- | --- |
| `mode` | `choice` (`check` / `distribute`) | `check` | no | `check` = read-only drift report; `distribute` = open one sync PR per drifted repo. |
| `only` | `string` | `""` | no | Sync only kit files whose path contains this substring (e.g. `skills.md`). Blank = all. |
| `repos` | `string` | `""` | no | Comma-separated **exact** repo names to target. Blank = all registry repos. |

Trigger events (`:14`): `workflow_dispatch`, plus `schedule` cron `0 12 * * 1` (Mondays 12:00 UTC).
The scheduled run is a **read-only drift alarm** — `mode` defaults to `check` via
`${{ github.event.inputs.mode || 'check' }}` (`:91`), so a failing weekly run means some repo has
drifted.

Permissions (`:35`): top-level `contents: read`. The write capability comes from a separately-minted
token, not `GITHUB_TOKEN`.

Secrets / vars consumed: `secrets.KDF_APP_ID`, `secrets.KDF_APP_PRIVATE_KEY` (GitHub App, when
`vars.USE_GITHUB_APP == 'true'`), else `secrets.CICD_PAT` fallback (`:77`–`:90`).

### 4b. `ops-distribute-kit.yml` — issue-form front-end

Trigger (`.github/workflows/ops-distribute-kit.yml:10`): `issues: [labeled]`, gated to the
`ops:distribute-kit` label (`:20`, `:30`). The issue-form fields
(`.github/ISSUE_TEMPLATE/ops-distribute-kit.yml`) map to the same three engine arguments:

| Form field | id | Maps to |
| --- | --- | --- |
| Mode (`check` / `distribute`) | `mode` | positional `mode` |
| Target repos (multi-select; `ALL` or subset) | `repos` | `--repos` (comma-joined; `ALL` → no filter) |
| Kit file filter | `only` | `--only` |

Job permissions (`:34`): `contents: read` + `issues: write` (to post the result comment). Parsed
issue content is treated as untrusted — extracted with `awk` from an env var, passed via `env:` into
an argv **array** (never inlined into a shell string), and `mode` is allow-listed before use
(`:64`–`:106`).

### 4c. `_authorize-owner.yml` — the reusable gate (the real `workflow_call` contract)

```yaml
# both front-ends call it as a job:
jobs:
  authorize:
    uses: ./.github/workflows/_authorize-owner.yml
```

- **Inputs:** none.
- **Outputs:** `authorized` — `'true'` only when `github.triggering_actor` equals
  `github.repository_owner` (case-insensitive) (`.github/workflows/_authorize-owner.yml:16`,
  `:39`).
- **Behavior:** on a non-owner it emits `::error::` and `exit 1`, so any job that `needs:` it is
  skipped — fail-closed.

### 4d. Engine CLI (local / automation contract)

```bash
GH_TOKEN=<pat-or-app-token> python scripts/distribute_kit.py check
GH_TOKEN=… python scripts/distribute_kit.py check --only skills.md
GH_TOKEN=… python scripts/distribute_kit.py distribute --only skills.md
GH_TOKEN=… python scripts/distribute_kit.py distribute --repos kriegerdataforge-sdk,fitness-app-backend
```

- **Env:** `GH_TOKEN` (required) — `contents:read` for `check`, `contents` + `pull-requests:write`
  for `distribute` (`scripts/distribute_kit.py:25`, `:384`).
- **Exit codes:** `check` exits `1` on any drift or API error, `0` when all in sync
  (`:280`–`:287`); `distribute` exits `1` if any repo failed (`:331`–`:336`).

## 5. Inputs, outputs & state

- **Inputs:** the three engine args (`mode`, `--only`, `--repos`); the canonical files under
  `kit/common/`; the registry `kit_registry.json`; `kit/KIT_VERSION`.
- **Outputs (`check`):** a per-repo drift report to stdout (`… in sync` / `… DRIFT (n): file, …`)
  and a process exit code. No repo state is changed.
- **Outputs (`distribute`):** one branch `chore/kit-sync-<version>` and one PR per drifted repo,
  titled `chore(kit): sync agentic-workflow kit <version>` (`:296`), body listing the updated files
  and pointing at ADR D-001. The `ops-*` front-end additionally posts the captured engine output as a
  comment back on the triggering issue (`ops-distribute-kit.yml:127`).
- **Persisted state / version markers:** two files must agree — `kit/KIT_VERSION` (canonical) and
  `kit/common/docs/agent/KIT_VERSION` (the vendored marker that ships into every repo). At startup the
  engine calls `_assert_version_consistency()` (`:86`, `:383`) and **refuses to run** if they differ.
  Both currently read `v1.2.0`.
- **Concurrency / caches:** none — neither front-end declares a `concurrency:` group, and the engine
  keeps no cache. Re-running `distribute` for the same version is idempotent-ish: it reuses the
  existing sync branch (422-on-create is swallowed) and re-PUTs the current file contents.
- **Deployment targets:** none — this feature opens PRs; it deploys nothing and touches no GitHub
  Environment.

## 6. Security & authz

- **Fail-closed owner gate.** Every privileged path routes through `_authorize-owner.yml`, which
  compares `github.triggering_actor` (not the frozen `event.sender`, so a manual "Re-run" is
  attributed to whoever re-ran it) to `github.repository_owner`, case-insensitively and never
  hard-coded to a username (`_authorize-owner.yml:31`–`:49`). This repo is **public**, so
  authorization — not obscurity — is the control (ADR D-002). The scheduled weekly run has no human
  actor, so it is intentionally the read-only `check` path only; the `distribute-kit.yml` job's `if:`
  requires `needs.authorize.outputs.authorized == 'true'` on the `workflow_dispatch` path and lets the
  gate-less schedule through via `always()` + an explicit event check (`distribute-kit.yml:52`).
- **Short-lived, downscoped token.** When `vars.USE_GITHUB_APP == 'true'`, both front-ends mint a
  GitHub **App installation token** via `actions/create-github-app-token` downscoped to
  `permission-contents: write` + `permission-pull-requests: write` — exactly what pushing a sync
  branch and opening a PR needs. It is auto-revoked at job end (effective lifetime = job runtime).
  When the App flag is off it falls back to `secrets.CICD_PAT` (`distribute-kit.yml:75`–`:90`,
  `ops-distribute-kit.yml:111`). This is least-privilege, ephemeral-credential CI practice
  (OWASP CI/CD Security `CICD-SEC-6` — insufficient credential hygiene; GitHub's own guidance to
  prefer scoped, short-lived App tokens over long-lived PATs).
- **Untrusted input handling.** The issue body is attacker-controllable (public repo). It is read only
  as `awk` data from an `env:` variable, every extracted value flows into an argv **array** (never
  interpolated into a `run:` shell string — no command injection), and `mode` is allow-listed to
  `check|distribute` before use (`ops-distribute-kit.yml:64`–`:106`). This is the standard mitigation
  for GitHub Actions script-injection (`CICD-SEC-4` — poisoned pipeline execution).
- **No auto-merge, human in the loop.** `distribute` only *opens* PRs; the owner reviews and merges
  (`distribute_kit.py:15`, `:320`). A sync PR is docs-only and is exempted from the version gate by
  `check_version.py` only when **every** changed file is a kit path (`_is_kit_only_pr`,
  `check_version.py:141`) — a PR that sneaks a non-kit file in is *not* exempt and hits the normal
  gate.
- **No secrets in scope of the data.** The registry and kit files carry no secrets; the token is never
  echoed. `_excluded_notes` in the registry documents why cicd is not a self-target (no self-PRs) and
  why per-repo pointer files (`AGENTS.md`, `CLAUDE.md`, `.cursorrules`) are **never** synced
  (`kit_registry.json:31`).

## 7. Configuration & environment

| Setting | Where | Effect |
| --- | --- | --- |
| `kit/KIT_VERSION` | this repo | Canonical kit version; drives branch name, PR title, and the consistency check. Bump via `make bump-*`? — **no**; the kit version is separate from the repo `VERSION` and is edited by the kit epic (ADR D-003). |
| `kit/common/docs/agent/KIT_VERSION` | this repo (a synced file) | Vendored marker; must equal the canonical or the engine aborts (`_assert_version_consistency`). Bump **both together**. |
| `kit_registry.json → files[]` | this repo | The exact set of synced paths; also the source of the version-check exemption set. |
| `kit_registry.json → repos[]` | this repo | The 14 target repos (`owner/repo` + `branch`, default `main`). cicd itself is deliberately absent. |
| `vars.USE_GITHUB_APP` | repo Actions **variable** | `'true'` → mint a GitHub App token; anything else → `CICD_PAT` fallback. |
| `secrets.KDF_APP_ID`, `secrets.KDF_APP_PRIVATE_KEY` | repo/org secrets | GitHub App credentials (only used when `USE_GITHUB_APP=true`). |
| `secrets.CICD_PAT` | repo/org secret | Fallback token with contents + PR write across targets. |
| `GH_TOKEN` | env (CLI / step) | The token the engine actually reads (`distribute_kit.py:384`). Wired from the App token or `CICD_PAT`. |
| runner + Python | both front-ends | `runs-on: ubuntu-slim`, Python `3.14`, `pip install -r scripts/requirements.txt` (`requests`, `PyNaCl`). |

There is no prod-vs-dev split — the engine operates against each target's configured branch
(default `main`) directly. The only "mode" distinction is `check` (read-only, also the weekly
alarm) vs `distribute` (opens PRs).

## 8. Usage & how to extend

**Report drift across the whole ecosystem (safe, opens nothing):**
1. Actions → **Distribute Agentic-Workflow Kit** → Run workflow → `mode = check` (or wait for the
   Monday cron). A red run = drift; the log lists which repos and which files.

**Push a kit change to the fleet:**
1. Edit the canonical file under `kit/common/` and bump **both** `kit/KIT_VERSION` and
   `kit/common/docs/agent/KIT_VERSION` (per the kit epic / ADR D-003).
2. Merge that change into this repo's `main` (cicd is sync-excluded, so its own copies update here).
3. Run **Distribute** with `mode = distribute` (dispatch), or open the **Ops · Distribute
   Agentic-Workflow Kit** issue form, fill mode/repos/filter, and add the `ops:distribute-kit` label.
4. Review and merge each opened PR in the tenant repos (nothing auto-merges).

**Onboard a new tenant repo:** add a `{ "repo": "Needless2Say/<name>", "branch": "main" }` entry to
`kit_registry.json → repos[]` and, for the Ops form, add the name to the `repos` dropdown options
(`ops-distribute-kit.yml` issue template). Because `check_version.py` derives its exempt set from the
same registry, no consumer-side change is needed for the version gate.

**Add a new synced kit file:** add its repo-relative path to `files[]`. If it lives outside
`docs/agent/**`, `skills.md`, or `WORKFLOW.md`, also confirm the version-check exemption covers it —
the exempt set is `files[]` unioned with the `docs/agent/` prefix and a `{skills.md, WORKFLOW.md}`
fallback (`check_version.py:106`, `:118`).

**Safe seams:** the mode/registry/file split is the extension surface — keep the engine
tenant-agnostic (Critical rule #12, `AGENTS.md`) and drive new behavior from the registry rather than
hard-coding repo names in the script.

## 9. Testing

- **Unit tests:** `scripts/tests/test_distribute_kit.py` — all network I/O is mocked; covers
  `_normalize` CRLF-folding, `_select_files`/`_select_repos` (exact vs substring, case-insensitivity,
  multi-token, no-match exits), `_get_remote_file` (404 → `None`, base64 decode), `compute_drift`
  (diff + missing, line-ending normalization), `cmd_check` (0/1 exit paths, `--repos` filter),
  `cmd_distribute` (opens PR on drift, skips in-sync, reports failure rc), and
  `_assert_version_consistency` (match / mismatch / marker-absent).
- **Run:** `make test` (pytest in `scripts/` with coverage) or `make check-all` (actionlint +
  tests) — the local gate before a PR.
- **Notable gaps:** no end-to-end test hits the real GitHub API (by design — the HTTP helpers
  `_get_branch_sha`/`_create_branch`/`_put_file`/`_create_pr` are exercised only through mocks); the
  YAML front-ends' owner-gate/`if:` logic is covered by `actionlint` lint only, not a behavioral test;
  and `main()` / CLI arg parsing isn't directly unit-tested.

## 10. Related docs & references

- ADRs — [`../CHANGELOG_AND_DECISION_LOG.md`](../CHANGELOG_AND_DECISION_LOG.md): **D-001** (kit
  Standard v1.1 + the propagation model), **D-002** (Ops Console issue-form front-ends + the shared
  owner gate), **D-003** (Standard v1.2 pre-launch hardening + the vendored `KIT_VERSION` marker and
  honest sync wording), **D-009** (Standard v1.3: `DOCUMENTATION_STANDARD.md` + the
  contributor-onboarding template; files[] 9 → 11).
- Epic tracker — `kriegerdataforge/docs/epics/agent-kit-distribution.md` (in the hub repo).
- [`../reference/WORKFLOWS.md`](../reference/WORKFLOWS.md) — the full workflow catalog (the PAT used by
  the kit engine and repo-provisioning is described in its secrets section).
- [`../guides/SECRET_ROTATION.md`](../guides/SECRET_ROTATION.md) — the sibling Ops-Console flow
  (`rotate_secret.py`) that shares the same `_authorize-owner.yml` gate pattern.
- `scripts/common/check_version.py` — the consumer-side kit-only-PR version-check exemption
  (ADR D-001 option B).
- External: OWASP **Top 10 CI/CD Security Risks** — `CICD-SEC-4` (poisoned pipeline execution) and
  `CICD-SEC-6` (insufficient credential hygiene); GitHub Actions "Security hardening for GitHub
  Actions" (script injection, least-privilege `permissions:`).

---

### Follow-ups noted while documenting (not fixed here)

- ~~**Stale help text** in the `distribute_kit.py` argparse epilog~~ — fixed (the epilog now says
  "comma-separated EXACT names, not substrings"; PR #122).
