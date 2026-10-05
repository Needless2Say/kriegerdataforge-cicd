# docs/guides. How to & operational walkthroughs

Step by step guides for working in and operating this repo. Start with
[`CONTRIBUTOR_ONBOARDING.md`](CONTRIBUTOR_ONBOARDING.md) if you're new. The rest are
task shaped, open the one matching what you're doing.

| Guide | What it walks you through |
| --- | --- |
| [`CONTRIBUTOR_ONBOARDING.md`](CONTRIBUTOR_ONBOARDING.md) | Clean checkout → green `make check-all` → first PR (the gate *is* the run here) |
| [`E2E_TESTING.md`](E2E_TESTING.md) | The per repo E2E engine. `e2e/manifest.json` journeys, the `run-e2e` action, `RUN_E2E_GATE`/`RUN_E2E_CD` opt ins |
| [`PROD_GATE.md`](PROD_GATE.md) | The workflow a release must pass before `prod`. Its lanes per stack, running it for a release, and reading a red run |

The owner's runbooks, `MANUAL_SETUP.md`, `SECRET_ROTATION.md`, `PROJECTS_BOARDS.md` and `REPORTS_TRIAGE_OPS.md`,
moved to the private context repo on 2026-10-05 (D-050), `kriegerdataforge-context/ops/`.

New guide? Follow [`../agent/DOCUMENTATION_STANDARD.md`](../agent/DOCUMENTATION_STANDARD.md) and
add it to [`../README.md`](../README.md) (the docs index) in the same PR.
