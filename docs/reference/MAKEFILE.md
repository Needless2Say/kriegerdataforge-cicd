# Makefile Reference - kriegerdataforge-cicd

> Every command this repo exposes, why it exists, and the conventions the file follows.
> `make` on its own prints the same list, grouped in dev-flow order.

---

## The repo that defines the names

This is the ecosystem's **control plane**: the reusable GitHub Actions workflows every other repo
calls, the operational scripts behind them, and the Tier-2 Playwright suite that drives the whole
stack in a browser.

That gives its Makefile an unusual property. Several reusable workflows here **hardcode the make
target they invoke in the calling repo**:

| Workflow | Runs in the caller |
| --- | --- |
| `ci-nextjs-lint-typecheck.yml` | `make ci-lint`, `make ci-typecheck` |
| `ci-nextjs-build.yml` | `make ci-build` |
| `ci-nextjs-tests.yml` | `make ci-unit-tests` |
| `ci-npm-audit.yml` | `make ci-npm-audit` |

Those names are therefore **canonical ecosystem-wide** - not by preference, by enforcement. The
Python reusable workflows (`ci-python-lint.yml`, `ci-python-typecheck.yml`, `ci-python-tests.yml`,
`ci-python-integration.yml`, `ci-python-kdf-fmt.yml`) instead take the command as an input, which
is exactly how the Python repos drifted onto different names until 2026-08-09.

**Renaming a lane here can break every TypeScript repo's CI.** Read the canon first.

## It is the only public repo

Everything in this repo is world-readable. No real credential, hostname or account identifier may
appear in it - including in these docs. `GH_PACKAGES_PAT` below is a *variable name*, never a value.

---

## `make ci` now exists

Until 2026-08-09 there was **no `ci` target here** - while `CLAUDE.md`, `AGENTS.md`, `WORKFLOW.md`,
`DEFINITION_OF_DONE.md`, the PR template and the agent-kit onboarding template all instructed
contributors to get `make ci` green before pushing. The repo that hands that instruction to every
other repo could not honour it itself.

Three lanes, mirroring `ci.yml`:

| # | Target | Mirrors |
| --- | --- | --- |
| 1 | `ci-lint` | `actionlint` over the workflows |
| 2 | `ci-style` | kdf-fmt, baseline-gated |
| 3 | `ci-unit-tests` | `pytest scripts/tests` |
| 4 | `ci-version-check` | VERSION bumped vs the base branch (skips if origin/main is not fetched) |

Not reproducible locally: `version-check` (`bump-version-check.yml`), which compares against the
base branch and needs PR context.

**`ci-lint` has no skip-if-missing guard, deliberately.** The local `lint` target skips with an
install hint when actionlint is absent, which is right for a convenience target. A *CI-parity*
lane that quietly passed when the tool was missing would be worse than no lane at all - it would
report green for a check that never ran.

---

## Conventions

| Convention | Why |
| --- | --- |
| `##@` group headers | `make` prints targets grouped in the order you would use them. Replaced a flat 25-target list. |
| `##` on a target | The only thing that makes a target appear in help. No `##` -> hidden. |
| `_`-prefixed targets | Internal guards (`_ensure-venv`). Hidden from help, still callable. Documented by a `# Internal: ...` line above the target, never on the target line. |
| Per-section `.PHONY` | Declared next to the targets it covers, not batched at the top. |
| Canned recipes | `$(call banner,...)`. |
| ASCII only | Windows consoles (cp1252) mangle anything else mid-recipe. This file had **415** non-ASCII characters. |
| No hardcoded versions | The kdf-fmt pin is read from this repo's own `ci.yml` (`kdf_fmt_ref`), never duplicated. |

---

## The venv, and why there wasn't one

This repo used to have **no virtual environment at all**:

```make
PY3 := py          # no version pin
```

`make test` then ran `$(PY3) -m pip install -r requirements-test.txt` and `style` pip-installed
`kdf-fmt` - both into whatever `py` resolved to, which is the contributor's **system Python**. Two
problems: it writes packages into a global environment the contributor did not offer, and with no
`-X.Y` the interpreter version floats with whatever happens to be installed.

It now uses the standard `.venv` + `PYTHON_VERSION ?= 3.14` block, identical to the other seventeen
repos. `make clean` removes it.

### Two interpreters, on purpose

| Variable | Interpreter | Used by |
| --- | --- | --- |
| `PYTHON` | `.venv` | anything needing an installed package - pytest, kdf-fmt, `bump-*` |
| `PY_SYS` | system | the `e2e/ci_stack.py` helpers only |

`ci_stack.py` is **stdlib-only** (argparse, json, os, secrets, shutil, subprocess, sys, dataclasses,
pathlib) and CI invokes it as a bare `python e2e/ci_stack.py` in
`.github/actions/run-e2e/action.yml`. Routing it through the venv would add a venv build to targets
that need no packages - including `e2e-ci-down`, a **teardown** target that has to keep working even
when the venv is broken or absent.

> `$(PYTHON) -m pip` / `-m pytest`, never the bare `pip` / `pytest` shims: on Windows those console
> scripts are not on PATH under Git Bash, so those targets failed locally while passing in CI.

---

## Groups

### Setup & Dependencies

`setup` -> `install` (test deps into the venv) -> `venv`.

### Linting & Style

`lint` (actionlint, skips with a hint if absent) and `style` (kdf-fmt).

`style` is **baseline-gated**: the pre-existing findings recorded in `kdf-style-debt.json` are
accepted debt and only *new* violations fail. Do not regenerate that file.

### Testing

`test`, `test-coverage`, `check-all`.

**`test` and `test-coverage` used to be the same target.** `make test` ran
`pytest --cov=. --cov-report=term-missing` while `ci.yml`'s test job ran plain
`pytest tests/ --tb=short` - the same name doing two different things, with the local one slower
and able to fail on coverage configuration CI never exercised. `test` now matches CI; coverage
moved to `test-coverage`, which is the ecosystem-canonical name for it.

Coverage exclusions live in `scripts/.coveragerc`, not on the command line: `--cov-omit` is not a
pytest-cov option, and passing it made pytest exit 4.

### End-to-End (Playwright)

Kept out of `ci` and `check-all` so the fast gate stays fast. See `e2e/README.md`.

Two stacks, and the distinction matters:

- **`e2e-up` / `e2e` / `e2e-down`** drive your *local* dev stack, delegating to
  `fitness-app-frontend`.
- **`e2e-ci-up` / `e2e-ci` / `e2e-ci-down`** drive the **self-contained** stack: `ci_stack.py`
  builds every service from source, generates ephemeral keys and OIDC credentials, and migrates and
  seeds the databases. No `.env.local`, no bind mounts - which is what lets CI use it, via the
  `run-e2e` composite action.

> **`e2e-up` was starting the wrong stack.** It called the sibling's `docker-up`, and under the
> ecosystem ladder rule that starts a repo's own layer and everything **below** it - in
> `fitness-app-frontend` that is frontend + backend + db + minio, and nothing else. The hub comes
> from **`docker-up-full`**. So `e2e-seed-user`'s `docker exec kdf-api` had no container to exec
> into, and the OIDC login journey had no auth UI to log in against. `e2e-down` was already
> cascading the whole ladder via `docker-stop`, and that asymmetry is what made the bug visible.
> Fixed 2026-08-09.

`make e2e JOURNEY=tiffanys` stages a different journey's specs; the default is `fitness`, matching
the delegated stack.

### Versioning & Release

`bump-patch` / `bump-minor` / `bump-major` update `VERSION`. Open a PR afterwards -
`bump-version-check.yml` validates the increment against the base branch.

`PYTHONUTF8=1` is parity with the other repos, whose bump scripts print a U+2705 that crashes a
cp1252 Windows console *after* the files are written. This repo's copy is emoji-free today
(verified - its only non-ASCII is box-drawing inside comments), so here the prefix is precaution
rather than a fix for a live crash.

### CodeQL Security Scanning

Seven targets, SARIF and CSV. Language is **`python`**, scanning the operational code under
`scripts/` - secret rotation, deployer authorization, project provisioning, app-secret
distribution. Scoped by `.github/codeql/codeql-config.yml`, the same config CI passes.

```bash
make codeql-db && make codeql-scan-all     # SARIF, opens in VS Code
make codeql-scan-csv-all                   # CSV, easier to hand to an AI
```

> **It used to be `javascript-typescript`, and that scanned almost nothing.** A real run on
> 2026-08-09 covered **2 files** - `playwright.config.ts` plus one *transient* spec. The journey
> specs are not in this repo: `ci_stack.py` stages them in from the app repos (ADR D-006, cicd is
> the engine only) and removes them again, so a scan saw whatever happened to be staged. Switched
> to `python`, which covers **17 files** of genuinely security-sensitive code. `e2e/staged-tests`
> is now explicitly ignored because its contents are transient.

**The CI job is gated and normally skipped** - CodeQL needs a public repo or GitHub Code Security.
This repo *is* the public one, so `ENABLE_CODEQL=true` is worth setting here first. The local
targets need no entitlement either way.

> **Windows note.** `codeql-db` prefixes the venv onto `PATH` and carries an `_ensure-venv`
> prerequisite. CodeQL's Python autobuild calls a **bare `python`**, which on a `py`-only machine
> hits the Microsoft-Store alias and dies with exit code 9009. `CODEQL_PYTHON` does not help.
> `$$PWD` is used rather than `$(CURDIR)` because CURDIR is `E:/...` and the drive-letter colon
> splits a `:`-separated PATH.

### Maintenance

`clean` removes the venv, pytest caches and coverage artifacts. It skips `node_modules` when
clearing `__pycache__` directories.

---

## The token

| Variable | Kind | Used by | For |
| --- | --- | --- | --- |
| `GH_PACKAGES_PAT` | **Fine-grained**, Contents: Read | `style`, `ci-style` | pip installing `kdf-fmt` |

Read from `.env.local` only when not already exported (CI exports it), and never expanded into
recipe text: `$$GH_PACKAGES_PAT` resolves in the recipe's shell, so `make -n` prints the variable
name, not a secret. Process-scoped - it never writes the global `.gitconfig`, whose pollution
previously caused 403-on-push across every repo.

> **Order sensitivity.** `PIP_GIT_AUTH` is built with `ifneq`, evaluated immediately. Moving it
> above the `GH_PACKAGES_PAT` block leaves it empty and the kdf-fmt install fails.

---

## Related

- [`WORKFLOWS.md`](WORKFLOWS.md) - every reusable workflow and its inputs
- [`../../AGENTS.md`](../../AGENTS.md) - vision, module map, critical rules
- [`../FOLLOW_UPS_MAKEFILE_PASS_2026-08-09.md`](../FOLLOW_UPS_MAKEFILE_PASS_2026-08-09.md) - open items

---

**Containers.** This repo deliberately has none -- it is Tier D, and
[`DOCKER.md`](DOCKER.md) records why. The ecosystem-wide Docker standard is
[`DOCKER_CONVENTIONS.md`](../../../kriegerdataforge/docs/reference/DOCKER_CONVENTIONS.md).

**Ecosystem canon.** The shared target vocabulary every repo's Makefile follows lives in the hub:
[`docs/reference/MAKEFILE_CONVENTIONS.md`](https://github.com/Needless2Say/kriegerdataforge/blob/main/docs/reference/MAKEFILE_CONVENTIONS.md).
Two commands that do the same thing carry the same name everywhere -- check there before adding a
target, and update it in the same PR if you add a genuinely new one. **This repo's workflows are
what make several of those names load-bearing.**
