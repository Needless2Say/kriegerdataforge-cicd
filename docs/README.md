# kriegerdataforge-cicd — documentation index

CI/CD platform repo — agentic-workflow kit source, repo provisioning, and ops automation.

> Organized into the standard KDF docs taxonomy. The agent kit in `docs/agent/` is **centrally managed (kit-sync)** — do not edit it locally. `docs/prompts/` is doc-authoring tooling, not content.

## Start here / active

- [Changelog & Decision Log — kriegerdataforge-cicd](./CHANGELOG_AND_DECISION_LOG.md) — the **append-only ADR register** for this repo (D-NNN entries: kit, ops-console, GitHub-App migration, E2E decoupling). New architectural decisions land here.

## Reference

Interface, config, and technical reference.

- [Workflow Catalog](reference/WORKFLOWS.md) — per-workflow reference: inputs, secrets, caller patterns, the deployer-authorization gate, and the consumer-repo summary.

## Features

Implementation-grade references for this repo's reusable workflows and engines (the ecosystem "public contract"). Index: [`features/README.md`](features/README.md).

- [Agentic-workflow kit-sync engine](features/agentic-workflow-kit-sync.md) — distributes the shared agent kit (`skills.md` / `WORKFLOW.md` / `docs/agent/*`) from `kit/common/` to every tenant repo, detects drift, and opens review-gated sync PRs.

## Guides

How-to and operational walkthroughs.

- [Contributor Onboarding — kriegerdataforge-cicd](guides/CONTRIBUTOR_ONBOARDING.md) — clone → green `make check-all` → first PR.
- [Manual Setup Guide](guides/MANUAL_SETUP.md) — the runbook for everything that can't be automated: GitHub Environments, environment secrets, PAT/token creation, tenant onboarding, org migration.
- [Secret Rotation — runbook](guides/SECRET_ROTATION.md) — rotate a repo/environment secret via `scripts/rotate_secret.py` + `secret_registry.json`.
- [End-to-end (E2E) testing — CI gate, CD/nightly, or on demand](guides/E2E_TESTING.md) — how the reusable E2E engine runs.
- [GitHub Projects boards — catalog + operations](guides/PROJECTS_BOARDS.md) — the 6 ecosystem ticket boards, the `ops:provision-projects` runbook, and the one-time manual steps (Status options, views, invites).

## Security

Control-plane security model & threat posture. Index: [`security/README.md`](security/README.md).

- [Security model & threat posture of the CI/CD control plane](security/CONTROL_PLANE_SECURITY.md) — the source-verified control catalog: ephemeral least-privilege GitHub-App tokens (auto-revoked), the deployer-registry fail-closed gate + Environment protection, secret handling (never echoed, never baked into an image layer via BuildKit `--mount=type=secret`), strict +1 version discipline, and the tenant-agnostic trust boundary.

## Design

Approved design specs (each `*-LOG.md` is the paired implementation log). See [`design/README.md`](design/README.md) for a per-file index.

- [Design — KriegerDataForge "Ops Console" (issue-form front-ends for privileged operations)](design/ops-console.md)
- [Design note — migrate GitHub PATs to a GitHub App (+ Vercel master auto-rotation)](design/github-app-migration.md)
- [Design note — decouple the Tier-2 E2E tests out of cicd into each tenant repo](design/e2e-test-decoupling.md) ([impl log](design/e2e-test-decoupling-LOG.md))
- [Design note — E2E as a per-repo CI job (composite action), not a callable workflow](design/e2e-cijob-refactor.md) ([impl log](design/e2e-cijob-refactor-LOG.md))
- [Design note — Every repo owns a distinct E2E journey (its dependency subgraph)](design/e2e-every-repo-journeys.md) ([impl log](design/e2e-every-repo-journeys-LOG.md))
- [Design — the reports-ecosystem standard (Projects boards + AI bug reporter)](design/reports-ecosystem.md) — D-010; epic tracker lives in the hub (`kriegerdataforge/docs/epics/`)

## Agent kit

Centrally kit-synced from `kriegerdataforge-cicd` — **do not edit locally** (a local edit is drift; see `docs/agent/KIT_VERSION`).

- [`docs/agent/`](agent/) — `AGENT_OPERATING_STANDARD`, `DEFINITION_OF_DONE`, `DESIGN_AND_EPICS`, `DOCUMENTATION_STANDARD`, and `templates/` (ADR / design-spec / epic-tracker / contributor-onboarding). Its [`README`](agent/README.md) explains every kit file and the reading order.

## Prompts

- [`docs/prompts/`](prompts/) — doc-authoring prompt toolkit (tooling, not content). Feed one to an AI (or follow it yourself) to produce a specific kind of doc. See [`prompts/README.md`](prompts/README.md).

---

`docs/CHANGELOG_AND_DECISION_LOG.md` (living decision log) stays at the docs/ root; `docs/design/` keeps design specs and their implementation logs.
