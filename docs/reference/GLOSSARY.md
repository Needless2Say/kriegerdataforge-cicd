# Glossary - kriegerdataforge-cicd

> Every coined term, ID prefix, and piece of shorthand this repo's docs assume, defined inline.
> This repo is public, so this page stands alone instead of linking into the private ecosystem
> docs. Coined a new term in this repo's docs? Add it here in the same PR.

Written 2026-08-22, for humans and AI agents alike. Each definition names the exact identifier
and the doc or file where the concept lives.

## Control plane and CI

| Term | Definition |
| --- | --- |
| **Control plane** | This repo, the public CI/CD control plane for the KriegerDataForge (KDF) ecosystem. Reusable workflows, the agent kit, secret rotation, and the E2E engine live here. All other KDF repos are private, and app infrastructure plus app-plane secrets belong to the separate private terraform repo. |
| **Thin caller** | A consumer repo workflow that only `uses:` a reusable workflow from this repo with `secrets: inherit`. Logic stays here, repos keep stubs. |
| **Canonical lane names** | Several reusable workflows here hardcode the make target they invoke in the calling repo, `ci-lint`, `ci-typecheck`, `ci-build`, `ci-unit-tests`, `ci-npm-audit`, so those names are canonical ecosystem-wide by enforcement. The Python workflows take the command as an input instead. See `docs/reference/MAKEFILE.md`. |
| **Strict exactly-+1 VERSION gate** | The shared version check (`bump-version-check.yml`), each PR bumps exactly one `VERSION` segment by exactly one, lower segments reset. Kit-sync PRs are the deliberate docs-only exemption. |
| **`style / Style (kdf-fmt)`** | The required style check name, backed by the kdf-fmt formatter and its per-repo baseline (`ci-python-kdf-fmt.yml`). |
| **`dev` / `prod` / `github-pages`** | The three fixed GitHub Environment names used across all repos. Names are fixed, do not invent aliases. |
| **Environment gate / deployer gate** | Every deploy pauses at an Environment approval before secrets load, and a fail-closed per-repo allow-list (`scripts/check_deployer.py` + `deployer_registry.json`) gates on the triggering actor. |

## Kit and distribution

| Term | Definition |
| --- | --- |
| **The agent kit** | The byte-identical agentic-workflow markdown synced to the fleet from `kit/common/` here. `AGENTS.md` and `CLAUDE.md` are per-repo and excluded from sync. |
| **`KIT_VERSION`** | The kit version marker, the sync engine refuses to run when the repo marker and kit marker disagree. |
| **`kit_registry.json`** | The list of sync-target repos for kit distribution. |
| **Kit drift** | A local edit to a synced kit file. Never edit synced copies, change them here and redistribute. |

## Secrets and ops

| Term | Definition |
| --- | --- |
| **`secret_registry.json`** | The rotation source of truth, which secrets live where. |
| **Rotation engine (`rotate_secret.py`)** | The secret-rotation tool, `generate` mode mints a new value, `paste` mode takes one you provide. CI-plane secrets only, it refuses `terraform_managed` entries. |
| **Two planes** | CI-plane secrets are rotated from here, app-plane secrets belong to terraform. |
| **Ops Console** | Issue-form front-ends for privileged operations, for example the rotate-a-secret form and its `ops:rotate-secrets` label. |
| **`USE_GITHUB_APP`** | The repo variable that switches workflows from `CICD_PAT` to short-lived GitHub App installation tokens. |
| **C-series controls** | The numbered control-plane security controls in `docs/security/CONTROL_PLANE_SECURITY.md`. |

## E2E and reports

| Term | Definition |
| --- | --- |
| **E2E engine vs journeys** | The Playwright engine lives here, each app repo declares its one journey in `e2e/manifest.json`, run by the `run-e2e` composite action and the `ci_stack.py` driver (ADRs D-006, D-007, D-008). |
| **Three run modes** | `RUN_E2E_GATE` on PRs, `RUN_E2E_CD` on push to main plus a weekly schedule (the CD / nightly lane), and on-demand `workflow_dispatch`. |
| **`check-oidc-rp-drift.yml`** | The workflow that detects drift of the shared OIDC-RP core across the two tenant frontends and files a deduped issue (PL-084). |
| **Reports standard / certified packages** | The reports contract in `docs/agent/REPORTS_STANDARD.md`, the certified pair is the `kdf_reports` backend package and the `@needless2say/report-form` widget. |
| **AI triage** | The weekly scheduled pass (ships disarmed) or on-demand run that clusters pending reports and files issues and board items, triggered through `trigger_triage.py`. |

## ID prefixes

| Prefix | Meaning |
| --- | --- |
| **`D-NNN`** | An Architecture Decision Record in `docs/CHANGELOG_AND_DECISION_LOG.md`. Numbering is per repo across the ecosystem, qualify with the repo. |
| **`PL-###`** | A finding id from the ecosystem's 2026 production-launch security audit, cited in workflows and docs here (see `skills.md`). |
