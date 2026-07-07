# kriegerdataforge-cicd — documentation index

CI/CD platform repo — agentic-workflow kit source, repo provisioning, and ops automation.

> Organized into the standard KDF docs taxonomy. The agent kit in `docs/agent/` is **centrally managed (kit-sync)** — do not edit it locally.

## Start here / active

- [Changelog & Decision Log — kriegerdataforge-cicd](./CHANGELOG_AND_DECISION_LOG.md)

## Reference

Architecture, data model, and codebase technical reference.

- [Workflow Catalog](reference/WORKFLOWS.md)

## Guides

How-to and operational walkthroughs.

- [Contributor Onboarding — kriegerdataforge-cicd](guides/CONTRIBUTOR_ONBOARDING.md)
- [Manual Setup Guide](guides/MANUAL_SETUP.md)

## Design

Approved design specs.

- [Design — KriegerDataForge "Ops Console" (issue-form front-ends for privileged operations)](design/ops-console.md)
- [Design — Decouple the Tier-2 E2E tests out of cicd into each tenant repo](design/e2e-test-decoupling.md) ([impl log](design/e2e-test-decoupling-LOG.md))
- [Design — E2E as a per-repo CI job (composite action), not a callable workflow](design/e2e-cijob-refactor.md) ([impl log](design/e2e-cijob-refactor-LOG.md))
- [Design — Every repo owns a distinct E2E journey (its dependency subgraph)](design/e2e-every-repo-journeys.md) ([impl log](design/e2e-every-repo-journeys-LOG.md))

---

`docs/CHANGELOG_AND_DECISION_LOG.md` (living decision log) stays at the docs/ root; `docs/design/` keeps design specs.
