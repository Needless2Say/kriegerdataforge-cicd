# End-to-end (E2E) testing — CI gate, CD/nightly, or on demand

How the KriegerDataForge ecosystem runs **full-stack, browser-and-API E2E** tests, and
how a repo chooses **when** they run — as a per-PR **CI gate**, on a **CD / nightly**
schedule, or only **on demand**. This is the developer-facing guide; the engine
internals + local-run instructions live in
[`kriegerdataforge-cicd/e2e/README.md`](../../e2e/README.md).

## The model — every repo owns one journey

E2E is **decoupled** (ADR D-006 → D-007 → D-008): the reusable *engine* lives in
`kriegerdataforge-cicd` (the `ci_stack.py` driver + the shared identity compose + the
`run-e2e` composite action), and **each repo owns its own journey** — a
`e2e/manifest.json` + a Playwright spec + (where needed) a compose fragment, all in
*that* repo. cicd holds **no** per-repo content, so onboarding a repo never edits cicd.

Each journey is scoped to that repo's **dependency subgraph** — the repo plus what it
depends on *downstream* (toward the auth DB), **never** its upstream consumers. So a
backend's journey stands up the backend + identity, but **not** its frontend — its gate
never depends on the frontend's `main`.

| Repo | `journey` | What it proves |
|---|---|---|
| `fitness-app-frontend` | `fitness` | full browser journey: login → `/database` renders backend data |
| `fitness-app-backend` | `fitness-api` | headless OIDC → real hub token → protected API serves the seeded catalogue |
| `tiffanys-space` | `tiffanys` | full browser journey: login → `/shop` |
| `tiffanys-space-backend` | `tiffanys-api` | headless OIDC → protected `/cart` served **with** the token, rejected **without** |
| `kriegerdataforge-auth-ui` | `auth` | hosted login/consent + hub + db, a synthetic client, no tenant app |
| `kriegerdataforge` (hub) | `hub` | OIDC discovery/JWKS + full auth-code+PKCE flow + userinfo + refresh + negatives, vs. the built image + real DB |

The backend/hub journeys are **headless**: with no frontend to run the OIDC callback,
the spec itself plays the OIDC client — it drives a real login through the hosted
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
`hub` (or a comma-list, or `all` for the app browser journeys). See
[`e2e/README.md`](../../e2e/README.md) for the self-contained (`make e2e-ci`) vs.
delegated (`make e2e-up`) local stacks.

## In CI/CD — three run modes

Each repo ships a **dormant** job, `.github/workflows/e2e.yml`, that `uses:` the
`run-e2e` action. It stays a near-instant no-op until you opt into a mode via two repo
**variables** (Settings → Secrets and variables → Actions → Variables):

| Mode | Set the variable | E2E runs… | Choose it when |
|---|---|---|---|
| **CI gate** | `RUN_E2E_GATE = true` | on every **PR** to `main` | you want E2E to **block merges** (a hard per-PR gate) |
| **CD / nightly** | `RUN_E2E_CD = true` | on **push to `main`** (post-merge) **+ weekly** | you **don't** want E2E on every PR, but want it on the deploy path + a schedule |
| **On demand** | *(neither)* | only on a manual **`workflow_dispatch`** | you run it yourself, ad hoc |

- A manual **`workflow_dispatch` always runs**, regardless of the variables (repo
  write-access is the gate).
- The two variables are **independent** — set both for a per-PR gate *and* a nightly
  safety net, or just `RUN_E2E_CD` to keep PRs fast while still validating the merged
  main.
- **Which should I use?** For tightly-coupled repos (hub ↔ frontends, SDK consumers)
  prefer **CD / nightly** — a hard per-PR gate can deadlock on changes that must land in
  two repos together (see the caveat below). For a standalone repo, the **CI gate** is
  fine.

### Enabling it

1. **Secrets** (any running mode needs them): `KDF_APP_ID`, `KDF_APP_PRIVATE_KEY` — the
   action mints its App token from these. The `ops-setup-e2e` issue flow (in cicd)
   copies them and sets `RUN_E2E_GATE=false` for you.
2. **Variable**: set `RUN_E2E_GATE=true` (CI gate) and/or `RUN_E2E_CD=true` (CD/nightly).
3. **CI-gate only**: add the resulting **E2E** check to branch protection → *Require
   status checks to pass*.

> **Caveat — cross-repo lockstep.** A change that must land in two repos together (an
> OIDC-contract change in the hub *and* a frontend, an SDK bump) can't go green in
> either repo's *per-PR* gate — each tests against the other's old `main`. That's why
> the **CD / nightly** mode exists: run the full journey **after** merge (and on a
> schedule) instead of blocking each PR, while the fast in-repo unit/contract tests stay
> the per-PR check.

## Onboarding a new repo

Add, **in the new repo** (zero cicd edits): `e2e/manifest.json` (declares its journey +
synthetic OIDC client), a Playwright spec under `e2e/tests/`, a compose fragment if it
runs its own service(s), and a `.github/workflows/e2e.yml` copied from the template in
[`e2e/README.md`](../../e2e/README.md) with its own `journey:`. Then flip
`RUN_E2E_GATE`/`RUN_E2E_CD` when ready. See
[`docs/design/e2e-every-repo-journeys.md`](../design/e2e-every-repo-journeys.md) (ADR
D-008).
