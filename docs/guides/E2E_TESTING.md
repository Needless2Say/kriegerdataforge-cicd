# End to end (E2E) testing. CI gate, CD/nightly, or on demand

How the KriegerDataForge ecosystem runs **full stack, browser and API E2E** tests, and
how a repo chooses **when** they run, as a per PR **CI gate**, on a **CD / nightly**
schedule, or only **on demand**. This is the developer facing guide. The engine
internals + local run instructions live in
[`kriegerdataforge-cicd/e2e/README.md`](../../e2e/README.md).

## The model. Every repo owns one journey

E2E is **decoupled** (ADR D-006 → D-007 → D-008). The reusable *engine* lives in
`kriegerdataforge-cicd` (the `ci_stack.py` driver + the shared identity compose + the
`run-e2e` composite action), and **each repo owns its own journey**, a
`e2e/manifest.json` + a Playwright spec + (where needed) a compose fragment, all in
*that* repo. cicd holds **no** per repo content, so onboarding a repo never edits cicd.

Each journey is scoped to that repo's **dependency subgraph**, the repo plus what it
depends on *downstream* (toward the auth DB), **never** its upstream consumers. So a
backend's journey stands up the backend + identity, but **not** its frontend. Its gate
never depends on the frontend's `main`.

| Repo | `journey` | What it proves |
|---|---|---|
| `fitness-app-frontend` | `fitness` | full browser journey. Login → `/database` renders backend data |
| `fitness-app-backend` | `fitness-api` | headless OIDC → real hub token → protected API serves the seeded catalogue |
| `tiffanys-space` | `tiffanys` | full browser journey. Login → `/shop` |
| `tiffanys-space-backend` | `tiffanys-api` | headless OIDC → protected `/cart` served **with** the token, rejected **without** |
| `kriegerdataforge-auth-ui` | `auth` | hosted login/consent + hub + db, a synthetic client, no tenant app |
| `kriegerdataforge` (hub) | `hub` | OIDC discovery/JWKS + full auth code+PKCE flow + userinfo + refresh + negatives, vs. the built image + real DB |

The backend/hub journeys are **headless**. With no frontend to run the OIDC callback,
the spec itself plays the OIDC client. It drives a real login through the hosted
auth-UI, mints a **real** hub access token (PKCE + confidential exchange), then calls
the target's API.

## Running it locally

From the **cicd** repo, with the sibling repos checked out next to each other:

```bash
python e2e/ci_stack.py up --journey <journey>   # build + up + migrate + seed
cd e2e && npm test                              # runs the staged spec
python e2e/ci_stack.py down
```

`<journey>` is any of `fitness`, `fitness-api`, `tiffanys`, `tiffanys-api`, `auth`,
`hub` (or a comma list, or `all` for the app browser journeys). See
[`e2e/README.md`](../../e2e/README.md) for the self contained (`make e2e-ci`) vs.
delegated (`make e2e-up`) local stacks.

## In CI/CD, three run modes

Each repo ships a **dormant** job, `.github/workflows/e2e.yml`, that `uses:` the
`run-e2e` action. It stays a near instant no-op until you opt into a mode via two repo
**variables** (Settings → Secrets and variables → Actions → Variables):

| Mode | Set the variable | E2E runs… | Choose it when |
|---|---|---|---|
| **CI gate** | `RUN_E2E_GATE = true` | on every **PR** to `main` | you want E2E to **block merges** (a hard per PR gate) |
| **CD / nightly** | `RUN_E2E_CD = true` | on **push to `main`** (post merge) **+ weekly** | you **don't** want E2E on every PR, but want it on the deploy path + a schedule |
| **On demand** | *(neither)* | only on a manual **`workflow_dispatch`** | you run it yourself, ad hoc |

- A manual **`workflow_dispatch` always runs**, regardless of the variables (repo
  write access is the gate).
- The two variables are **independent**. Set both for a per PR gate *and* a nightly
  safety net, or just `RUN_E2E_CD` to keep PRs fast while still validating the merged
  main.
- **Which should I use?** For tightly coupled repos (hub ↔ frontends, SDK consumers)
  prefer **CD / nightly**. A hard per PR gate can deadlock on changes that must land in
  two repos together (see the caveat below). For a standalone repo, the **CI gate** is
  fine.

### Enabling it

1. **Secrets** (any running mode needs them). `KDF_APP_ID`, `KDF_APP_PRIVATE_KEY`. The
   action mints its App token from these. The `ops-setup-e2e` issue flow (in cicd)
   copies them and sets `RUN_E2E_GATE=false` for you.
2. **Variable**. Set `RUN_E2E_GATE=true` (CI gate) and/or `RUN_E2E_CD=true` (CD/nightly).
3. **CI gate only**. Add the resulting **E2E** check to branch protection → *Require
   status checks to pass*.

> **Caveat. Cross repo lockstep.** A change that must land in two repos together (an
> OIDC contract change in the hub *and* a frontend, an SDK bump) can't go green in
> either repo's *per PR* gate. Each tests against the other's old `main`. That's why
> the **CD / nightly** mode exists. Run the full journey **after** merge (and on a
> schedule) instead of blocking each PR, while the fast in repo unit/contract tests stay
> the per PR check.

## The release gate, prod deploys need a green run on the tag

Since D-019 the two reusable Vercel deploys refuse a `prod` deploy of a release whose E2E workflow
has no successful run for the release. The order for a release is therefore, merge with the
version bump, let `release.yml` cut the tag `v<version>`, dispatch **Actions, E2E, Run workflow** with
the **version** input set to the release, wait for green, then dispatch the CD to `prod`. A `dev`
deploy is never refused, the gate reports what it found and lets it through, so DEV can be soaked
first and the E2E dispatched once the release is what will go to PROD.

One run counts (D-021, D-024), a dispatch with the `version` input. It checks out the tag
`v<version>`, names its job `E2E v<version>`, and writes the release and commit it tested to its step
summary, the gate finds it by that name. Dispatch it on the default branch, the form's own choice. A
release dispatched on another branch does not count, unless that branch's head is the tag's commit,
the workflow a run runs is the one on its ref. A dispatch with the input empty tests the ref chosen in
the form and runs the journey alone, so it does not count, on the tag or on `main` either, which
D-021 counted. The gate's verdict and the run it found are in the deploy's step summary,
[`WORKFLOWS.md`](../reference/WORKFLOWS.md#e2e-gate).

**A release dispatch runs the whole test suite, not only E2E (D-024).** Given the `version` input,
`e2e.yml` runs the repo's unit lane, its integration lane where it has one, and its system and
mutation lanes where it has them, against the tag `v<version>`, as jobs the `e2e` job `needs`. The `e2e` job only
starts once all of them pass, so a failure anywhere in the suite fails the whole run and no `E2E
v<version>` job exists to be found, the gate denies with the same "no successful run" reason it
always has. This keeps the per PR `ci.yml` lanes fast (unit + integration only, on the PR head, the
`pull_request` trigger alone), and puts the full suite, including the slow mutation lane, on the one
path that actually needs it before a release ships, the release dispatch. Mutation testing dropped
its weekly schedule with D-024, it now runs per release instead of on a timer. A release dispatch has
a concurrency group of its own, so a merge to `main` while it runs does not cancel it, and a second
dispatch of the same version on the same ref replaces the first.

## Onboarding a new repo

Add, **in the new repo** (zero cicd edits). `e2e/manifest.json` (declares its journey +
synthetic OIDC client), a Playwright spec under `e2e/tests/`, a compose fragment if it
runs its own service(s), and a `.github/workflows/e2e.yml` copied from the template in
[`e2e/README.md`](../../e2e/README.md) with its own `journey:`. Then flip
`RUN_E2E_GATE`/`RUN_E2E_CD` when ready. See
[`docs/design/e2e-every-repo-journeys.md`](../design/e2e-every-repo-journeys.md) (ADR
D-008).
