# The PROD Gate. One workflow a release must pass before PROD

Every repo that deploys owns a workflow named **PROD Gate**, `.github/workflows/prod-gate.yml`. A release
reaches `prod` only after that workflow passed for it. This guide says what the gate runs, how to run it,
how the deploy reads it, and what to do when it is red (D-027).

> **Related.** [`E2E_TESTING.md`](E2E_TESTING.md), the journey, one lane of the gate.
> [`WORKFLOWS.md`](../reference/WORKFLOWS.md#prod-gate), how the deploy reads the gate.
> [`SECRET_ROTATION.md`](SECRET_ROTATION.md), the package token the installs fall back to.

## Releasing, in order

1. Merge the pull request that carries the version bump. `release.yml` cuts the tag `v<version>`.
2. **Actions, PROD Gate, Run workflow**, on the default branch, with **version** set to the release,
   `0.3.7` and not `v0.3.7`.
3. Wait for the run to end green. Its last job is named `PROD Gate v0.3.7`.
4. Dispatch the deploy to `prod`. Its `verify-prod-gate` job finds that job by name and lets the
   deploy through. Without it the deploy stops before it reads a secret.

A `dev` deploy is never refused. The same lookup runs and its result is reported, so DEV can be
soaked first and the gate dispatched once the release is what will go to PROD.

## What the gate runs

Every lane checks out the tag `v<version>`, the commit the deploy checks out. The workflow file is the
default branch's, the code under test is the release's.

| Lane | FastAPI repos, the hub and the two tenant backends | Next.js repos, the auth UI and the two tenant frontends |
|---|---|---|
| `ci` | lint (ruff), type check (mypy), the Vercel bundle's staleness, unit tests, integration tests, bandit, pip-audit, secret scan (gitleaks) | lint and type check, the Next.js build, unit tests, npm audit, secret scan (gitleaks) |
| `integration-tests` | inside `ci`, against a Postgres of the job's own | the flows under `src/__tests__/integration` |
| `system-tests` | the backend as a real server, on the source and on the Vercel bundle | |
| `mutation-tests` | every lane of the repo's mutant tables | every lane of the repo's mutant tables |
| `e2e` | the repo's journey, the whole stack in containers | the repo's journey, the whole stack in containers |
| `gate` | the verdict, `PROD Gate v<version>` | the verdict, `PROD Gate v<version>` |

`ci` is the repo's own `ci.yml`, called and not copied, so a check added to `ci.yml` is a check of
every release. The journey waits for every other lane, it builds the whole stack and is the slowest.

The last job, `gate`, needs every lane. It runs whenever the run was not cancelled, reads each lane's
result as GitHub wrote it, and passes only when every one is `success`. A lane that failed, a lane
skipped behind one that failed and a lane that was cancelled each fail it, and its summary names them.

## What the gate does not run, and why

| Job | Runs on | Why not in the gate |
|---|---|---|
| Version check | a pull request | It holds a pull request's version one above `main`'s. A release is a tag, and a tag is not a change to `main` |
| Style (kdf-fmt) | a pull request | How the code is laid out says nothing of whether a release works |
| Docker production image | a pull request | Vercel builds from source and runs no image. The job stays in `ci.yml`, a deploy target that runs the image needs it in the gate, see below |
| CodeQL | its own workflow | Off until a repo sets `ENABLE_CODEQL`, and it files findings, it does not pass or fail a commit |
| The hub's load smoke | by hand | Kept out of CI by its own marker |

Each of the first three carries `if: github.event_name == 'pull_request'` in `ci.yml`. **When a deploy
target runs the image**, remove that line from the `docker-build` job of the repo's `ci.yml`, and the
gate builds the image for every release from then on. Nothing else changes.

## How the deploy reads the gate

`cd-nextjs-vercel.yml` and `cd-python-vercel.yml` run `scripts/check_prod_gate.py` between the deployer
check and the deploy. A run counts when all of these hold.

- It is a run of `prod-gate.yml`. A run of the E2E workflow alone opens nothing, whatever its job is named.
- GitHub reports it `success`, and its job named `PROD Gate v<version>` passed.
- Its head is the tag's commit, or it was dispatched on the default branch. A dispatch on another branch
  does not count, that branch's copy of the workflow may have dropped a lane and kept the job's name.

## When the gate is red

Open the run. The `PROD Gate v<version>` job's summary names the lanes that did not pass.

| What the log says | Cause | What to do |
|---|---|---|
| `Invalid username or token` in an **Install** step | The package token `GH_PACKAGES_PAT` expired or was revoked. It is a person's token with an end date | Rotate it, [`SECRET_ROTATION.md`](SECRET_ROTATION.md). Set the repo's `USE_GITHUB_APP` variable to `true` and the lanes mint a token per job from the KDF App, and fall back to the package token only when the App is not set up |
| `No rule to make target` | The tag is older than the target the lane runs | The workflow is the default branch's and the tree is the tag's. Cut a release that holds the target and run the gate for that version |
| A mutant `survived` | A rule no test pins any more | Write the test that kills the mutant, or remove the mutant with the rule |
| A mutant `error, anchor stale` | The guarded line was rewritten and the mutant's anchor no longer matches | Update the anchor in the mutant's table |
| The run stops at startup | A lane the repo calls is not in this repo's `main`, or a called workflow asks for a permission its caller does not grant | Merge this repo first, then the consumer |

A fix lands on `main` and the gate tests the tag. So a red gate that needs a code change needs a new
release, and the gate is run again for the new version.

## Adding the gate to a new repo

Copy `prod-gate.yml`, `e2e.yml` and `ci.yml` from a repo of the same stack, and keep the job keys. Then
hold the repo to the shape in `scripts/tests/test_consumer_release_workflows.py`, which reads every
deploying repo that sits beside this one.
