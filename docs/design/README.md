# Design specs — index

Approved design notes for `kriegerdataforge-cicd`. Each spec captures the problem, the
decision, and the plan; every `*-LOG.md` is the paired **implementation log** tracking what
actually shipped. The corresponding **D-NNN ADR** for each lives in
[`../CHANGELOG_AND_DECISION_LOG.md`](../CHANGELOG_AND_DECISION_LOG.md).

| Spec | Implementation log | About |
|---|---|---|
| [ops-console.md](ops-console.md) | — | The "Ops Console": issue-form front-ends for privileged platform operations. |
| [github-app-migration.md](github-app-migration.md) | — | Retire long-lived GitHub PATs in favour of a GitHub App (+ Vercel master-token auto-rotation). |
| [e2e-test-decoupling.md](e2e-test-decoupling.md) | [e2e-test-decoupling-LOG.md](e2e-test-decoupling-LOG.md) | Move the Tier-2 E2E tests out of cicd into each tenant repo (cicd keeps only the reusable engine). |
| [e2e-cijob-refactor.md](e2e-cijob-refactor.md) | [e2e-cijob-refactor-LOG.md](e2e-cijob-refactor-LOG.md) | Run E2E as a per-repo CI job (composite action) rather than a callable workflow. |
| [e2e-every-repo-journeys.md](e2e-every-repo-journeys.md) | [e2e-every-repo-journeys-LOG.md](e2e-every-repo-journeys-LOG.md) | Every repo owns a distinct E2E journey (its own dependency subgraph). |

> The three `e2e-*` specs are slices of the E2E-decoupling epic (ADR **D-006**). See also the
> guide [`../guides/E2E_TESTING.md`](../guides/E2E_TESTING.md).
