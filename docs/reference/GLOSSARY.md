# Glossary - kriegerdataforge-cicd

> Every coined term, ID prefix, and piece of shorthand this repo's docs assume, defined inline.
> This repo is public, so this page stands alone instead of linking into the private ecosystem
> docs. Coined a new term in this repo's docs? Add it here in the same PR.

Written 2026-08-22, for humans and AI agents alike. Each definition names the exact identifier
and the doc or file where the concept lives.

## Control plane and CI

| Term | Definition |
| --- | --- |
| **Control plane** | This repo, the public CI/CD control plane for the KriegerDataForge (KDF) ecosystem. Reusable workflows, the agent kit, secret rotation, and the E2E engine live here. All other KDF repos are private, and app infrastructure plus app plane secrets belong to the separate private terraform repo. |
| **Thin caller** | A consumer repo workflow that only `uses:` a reusable workflow from this repo with `secrets: inherit`. Logic stays here, repos keep stubs. |
| **Canonical lane names** | Several reusable workflows here hardcode the make target they invoke in the calling repo, `ci-lint`, `ci-typecheck`, `ci-build`, `ci-unit-tests`, `ci-npm-audit`, so those names are canonical ecosystem wide by enforcement. The Python workflows take the command as an input instead. See `docs/reference/MAKEFILE.md`. |
| **Strict exactly-+1 VERSION gate** | The shared version check (`bump-version-check.yml`), each PR bumps exactly one `VERSION` segment by exactly one, lower segments reset. Kit sync PRs are the deliberate docs only exemption. |
| **`style / Style (kdf-fmt)`** | The required style check name, backed by the kdf-fmt formatter and its per repo baseline (`ci-python-kdf-fmt.yml`). |
| **`dev` / `prod` / `github-pages`** | The three fixed GitHub Environment names used across all repos. Names are fixed, do not invent aliases. |
| **Environment gate / deployer gate** | Every deploy pauses at an Environment approval before secrets load, and a fail closed per repo allow list (`scripts/check_deployer.py` + `deployer_registry.json`) gates on the triggering actor. |

## Kit and distribution

| Term | Definition |
| --- | --- |
| **The agent kit** | The byte identical agentic workflow markdown synced to the fleet from `kit/common/` here. `AGENTS.md` and `CLAUDE.md` are per repo and excluded from sync. |
| **`KIT_VERSION`** | The kit version marker, the sync engine refuses to run when the repo marker and kit marker disagree. |
| **`kit_registry.json`** | The list of sync target repos for kit distribution. |
| **Kit drift** | A local edit to a synced kit file. Never edit synced copies, change them here and redistribute. |
| **KDF Code Review Process** | How any code is reviewed, one function to every repo. The orchestrator fixes, fresh Claude and Codex sessions review from one brief at one pinned commit, ChatGPT Sol reads in rounds, every finding is reproduced and every fix pinned, and the owner merges. The standard is `kit/common/docs/agent/CODE_REVIEW_PROCESS.md`, D-028 and D-029. |
| **Scale** | How much of the process a review needs, spot (one function to one pull request, no plan), feature, repo, multi repo, or ecosystem. Picked first, it sets the plan, the slices, the Sol rounds and where the files live. |
| **Pin** | The pushed commit a review reads, named in its brief. Each reviewer reads it in the repo folder in its own turn, `kdf-review.sh --pin` checks that origin holds it and the folder is at it, and the launcher keeps the other reviewer's report of the scope out of the folder meanwhile, so a reviewer that runs later reads the same code and never another's report. |
| **`.env.kdf`** | The closed local env file, every credential that works beyond this machine, the GitHub package tokens, the hub's client secret and service key, and third party keys. Its twin `.env.local` holds only values that work on this machine and is open to every model. Each has a tracked example. ADR D-030. |
| **Review branch** | A branch that stays at a review's pin, `review/<pfx>-<slice>`, pushed so Codex in the cloud reads exactly the pin from GitHub. Codex fetches it, makes `review/<pfx>-<slice>-codex` from the pin, and pushes its report there with no pull request, and `kdf-review.sh --collect-branch` brings it in (ADR D-048). |
| **Role** | What an agent may do on a task, the same for every model and tool. Implementer by default, reviewer for a review, orchestrator for the session that runs one, chat reader in a chat. The charter is `kit/common/docs/agent/AGENT_ROLES.md`, and the guard enforces the same rules on Claude. |
| **Orchestrator** | The one long running session that runs a review campaign, writes the briefs, launches the fresh reviewers, adjudicates and opens the pull requests. It never merges, tags or deploys. |
| **Fresh review** | A review by a new session with an empty memory, briefed only by the brief and reading the pin, so it cannot inherit the orchestrator's assumptions. Claude and Codex each do one per slice. |
| **Sol dispatch** | One self contained prompt over one area of a slice, pasted by the owner into a fresh ChatGPT Sol session. A slice runs one round of them, or three for a trust slice. |
| **The guard** | `tools/claude-code/kdf-guard.js`, a Claude Code PreToolUse hook. Exit 2 refuses a tool call and says why. It enforces the owner rules in every session and the reviewer rules where `KDF_ROLE=reviewer`. |
| **`KDF_ROLE`** | The environment variable that sets a session's role for the guard. `reviewer` means read only git, no GitHub CLI, no writes outside `docs/reviews`, the review archive, no secret files and no outward facing tools. |
| **Blocks** | A finding's yes or no field. Yes is a P, or an M that reaches an account, a token, a credential, a privilege or someone else's data. Only yes is fixed first. |

## Secrets and ops

| Term | Definition |
| --- | --- |
| **`secret_registry.json`** | The rotation source of truth, which secrets live where. |
| **Rotation engine (`rotate_secret.py`)** | The secret rotation tool, `generate` mode mints a new value, `paste` mode takes one you provide. CI plane secrets only, it refuses `terraform_managed` entries. |
| **Two planes** | CI plane secrets are rotated from here, app plane secrets belong to terraform. |
| **Ops Console** | Issue form front ends for privileged operations, for example the rotate-a-secret form and its `ops:rotate-secrets` label. |
| **`USE_GITHUB_APP`** | The repo variable that switches workflows from `CICD_PAT` to short lived GitHub App installation tokens. |
| **C-series controls** | The numbered control plane security controls in `docs/security/CONTROL_PLANE_SECURITY.md`. |

## E2E and reports

| Term | Definition |
| --- | --- |
| **E2E engine vs journeys** | The Playwright engine lives here, each app repo declares its one journey in `e2e/manifest.json`, run by the `run-e2e` composite action and the `ci_stack.py` driver (ADRs D-006, D-007, D-008). |
| **Three run modes** | `RUN_E2E_GATE` on PRs, `RUN_E2E_CD` on push to main plus a weekly schedule (the CD / nightly lane), and on demand `workflow_dispatch`. |
| **`check-oidc-rp-drift.yml`** | The workflow that detects drift of the shared OIDC RP core across the two tenant frontends and files a deduped issue (PL-084). |
| **Reports standard / certified packages** | The reports contract in `docs/agent/REPORTS_STANDARD.md`, the certified pair is the `kdf_reports` backend package and the `@needless2say/report-form` widget. |
| **AI triage** | The weekly scheduled pass (ships disarmed) or on demand run that clusters pending reports and files issues and board items, triggered through `trigger_triage.py`. |

## ID prefixes

| Prefix | Meaning |
| --- | --- |
| **`<PFX>-<slice>-n`** | A finding id in a review campaign. `SDK-S1-3` is the third finding of the fresh Claude review of slice S1 of the SDK campaign, `-C3` is Codex, `-D2-R1-3` a Sol finding of dispatch 2 round 1, `-FIN-3` a final review. |
| **`D-NNN`** | An Architecture Decision Record in `docs/CHANGELOG_AND_DECISION_LOG.md`. Numbering is per repo across the ecosystem, qualify with the repo. |
| **`PL-###`** | A finding id from the ecosystem's 2026 production launch security audit, cited in this repo's workflows and docs wherever a control exists because of that finding. The register itself is private, ask the owner for the detail behind a specific id. |
