# Follow-ups - read this first when you revisit `kriegerdataforge-cicd`

**Written:** 2026-08-09, closing the ecosystem-wide Makefile standardization pass (the last of 18).
**Status:** `make ci` lanes 2 and 3 are green locally. Lane 1 was not verified here - see item 2.
**`VERSION` 0.2.80 -> 0.2.81.** This was the only repo in the ecosystem whose version was not
already ahead of `main`.

**This repo is PUBLIC.** Nothing below names a real credential, host or account, and nothing added
to it should.

---

## 1. `e2e-up` was starting a stack without the hub - fixed, but re-run the suite to confirm

**Start here.** It is the only functional bug found, and it silently degraded the E2E suite.

`e2e-up` delegated to `fitness-app-frontend`'s **`docker-up`**. Under the ecosystem ladder rule that
starts a repo's own layer and everything **below** it - frontend + backend + db + minio - and
nothing above. The hub (KDF backend + auth UI) comes from **`docker-up-full`**.

Consequences while it was wrong:

- `e2e-seed-user` runs `docker exec kdf-api ...` - **no such container**;
- the OIDC login journey had no auth UI to authenticate against.

`e2e-down` already cascaded the full ladder via `docker-stop`, and that up/down asymmetry is what
exposed it. Now calls `docker-up-full`.

**I verified the delegation resolves (`make -n`), but did NOT run a real E2E pass** - `e2e-up`
starts the whole ecosystem stack and `e2e-ci-up` builds every service from source. Worth one real
`make e2e-up && make e2e-seed-user && make e2e` before trusting the suite again.

Likely a knock-on from the ladder correction made earlier in the same wave, when `docker-up` stopped
cascading upward to the hub.

**The rest of the ecosystem was swept for the same bug on 2026-08-09 and is clean.** Every other
cross-repo delegation is correct: a `docker-up` that calls the layer *below* it
(`fitness-app-frontend` -> `$(FITNESS_BE) docker-up`, `tiffanys-space` -> `$(TIFFANYS_BE) docker-up`,
`kriegerdataforge-auth-ui` -> `$(KDF_HUB) docker-up`), and a `docker-up-full` that calls
`$(AUTH_UI) docker-up` (fitness-app-backend, fitness-app-frontend, tiffanys-space,
tiffanys-space-backend, template-fastapi). This repo's `e2e-up` was the only offender - because it
is the only place that delegates to a sibling expecting a *full* stack rather than a layer.

---

## 2. `ci-lint` could not be verified locally

`actionlint` is not installed on the machine this pass ran on, and `ci-lint` **deliberately has no
skip-if-missing guard** (a CI-parity lane that passes when the tool is absent is worse than no
lane). So lane 1 failed locally for want of the binary, not for a workflow problem.

Nothing was installed to work around it - deliberately, given this pass had just finished removing
system-environment pollution from this very repo.

```bash
brew install actionlint     # or: go install github.com/rhysd/actionlint/cmd/actionlint@latest
make ci                     # all three lanes
```

The local `lint` target still skips gracefully with an install hint; only `ci-lint` is strict.

---

## 3. Renaming a lane here can break other repos' CI

Recorded because it is not obvious from inside this repo.

These reusable workflows **hardcode** the make target they invoke *in the calling repo*:

| Workflow | Runs in the caller |
| --- | --- |
| `ci-nextjs-lint-typecheck.yml` | `make ci-lint`, `make ci-typecheck` |
| `ci-nextjs-build.yml` | `make ci-build` |
| `ci-nextjs-tests.yml` | `make ci-unit-tests` |
| `ci-npm-audit.yml` | `make ci-npm-audit` |

That is *why* those names are canonical ecosystem-wide - enforcement, not preference. The Python
reusable workflows take the command as an input instead (`typecheck_command`, `test_command`, ...),
which is precisely how the Python repos drifted onto `ci-type-check` / `ci-test` until this pass
renamed them.

Before touching any of the four: the canon is the hub's
[`docs/reference/MAKEFILE_CONVENTIONS.md`](https://github.com/Needless2Say/kriegerdataforge/blob/main/docs/reference/MAKEFILE_CONVENTIONS.md).

---

## 4. A deprecation the test run surfaced

`scripts/common/db_backup_base.py:114` uses `datetime.utcnow()`:

```text
DeprecationWarning: datetime.datetime.utcnow() is deprecated and scheduled for removal
```

Ten warnings from `test_db_backup_base.py`. Harmless today, will break on a future Python. The fix
is `datetime.now(datetime.UTC)`, but the produced string feeds backup **filenames**
(`%Y%m%d_%H%M%S`), so check nothing parses or sorts those before changing it. Left alone - a
timestamp format change in a backup path is not a Makefile-pass edit.

---

## 5. Smaller things, genuinely optional

- **`e2e-ci` calls `$(PY_SYS) ci_stack.py down` from inside `e2e/`** (it has already `cd e2e`), while
  the sibling targets call `$(PY_SYS) e2e/ci_stack.py` from the repo root. Both work; the
  inconsistency is only cosmetic, and I left the working invocation alone.
- **`kdf-style-debt.json` holds 366 hidden findings.** Recorded debt, owner-paced, same as every
  other repo. Do not regenerate the baseline.
- **`version-check` has no local target.** It runs `bump-version-check.yml` against the base branch,
  so it needs PR context. Same gap as terraform, same recommendation: leave it, and keep it
  documented so it stays a decision rather than an oversight.

---

## What was already done in the pass (do not redo)

- **`make ci` created** - three lanes mirroring `ci.yml`. It did not exist, while ~10 docs
  (`CLAUDE.md`, `AGENTS.md`, `WORKFLOW.md`, `DEFINITION_OF_DONE.md`, the PR template, the agent-kit
  onboarding template) all told contributors to run it.
- **`e2e-up` -> `docker-up-full`** - item 1.
- **A real virtualenv.** The repo previously ran a bare `py` (no version pin) and pip-installed
  pytest and kdf-fmt into the contributor's **system Python**. Now the standard `.venv` +
  `PYTHON_VERSION ?= 3.14` block. `PY_SYS` remains, deliberately and documented, for the stdlib-only
  `ci_stack.py` helpers - which CI also invokes with a bare `python`.
- **`test` split from `test-coverage`.** `test` ran `--cov` while CI ran plain pytest: one name,
  two behaviours. `test` now matches CI.
- **`KDF_FMT_VERSION` reads `ci.yml`'s `kdf_fmt_ref`** instead of a hardcoded `v1.1.0`.
- `##@` groups replace the flat help list; `.PHONY` split per section; `setup` and `clean` added;
  **415 non-ASCII characters removed**; `MAKEFLAGS += --no-print-directory`.
- New [`reference/MAKEFILE.md`](reference/MAKEFILE.md) - this was the **only repo in the ecosystem
  without one**.
