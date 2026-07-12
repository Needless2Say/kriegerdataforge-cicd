# docs/guides — how-to & operational walkthroughs

Step-by-step guides for working in and operating this repo. Start with
[`CONTRIBUTOR_ONBOARDING.md`](CONTRIBUTOR_ONBOARDING.md) if you're new; the rest are
task-shaped — open the one matching what you're doing.

| Guide | What it walks you through |
| --- | --- |
| [`CONTRIBUTOR_ONBOARDING.md`](CONTRIBUTOR_ONBOARDING.md) | Clean checkout → green `make check-all` → first PR (the gate *is* the run here) |
| [`E2E_TESTING.md`](E2E_TESTING.md) | The per-repo E2E engine: `e2e/manifest.json` journeys, the `run-e2e` action, `RUN_E2E_GATE`/`RUN_E2E_CD` opt-ins |
| [`SECRET_ROTATION.md`](SECRET_ROTATION.md) | Rotating ecosystem credentials via the Ops Console (owner-gated) |
| [`MANUAL_SETUP.md`](MANUAL_SETUP.md) | The one-time manual pieces automation can't do (labels, secrets, environments) |

New guide? Follow [`../agent/DOCUMENTATION_STANDARD.md`](../agent/DOCUMENTATION_STANDARD.md) and
add it to [`../README.md`](../README.md) (the docs index) in the same PR.
