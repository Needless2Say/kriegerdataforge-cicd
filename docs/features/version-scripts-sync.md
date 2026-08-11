# Feature — Version-scripts sync engine

_Last updated: 2026-08-11 · Status: draft_

## 1. Overview

The **version-scripts sync engine** distributes the ecosystem's shared version tooling —
`bump_version.py`, `check_version.py` and their common target-resolution module
`version_targets.py` — from ONE canonical source (`scripts/common/` in this repo) out to every
tenant repo as `scripts/*.py`, and keeps each repo's copy byte-identical. It is the script-sync
sibling of the [agentic-workflow kit-sync engine](./agentic-workflow-kit-sync.md): one source of
truth, one registry ([`scripts/scripts_registry.json`](../../scripts/scripts_registry.json)), one
propagation engine ([`scripts/distribute_scripts.py`](../../scripts/distribute_scripts.py)) that
either reports drift (`check`) or opens one review-gated pull request per drifted repo
(`distribute`). It **never auto-merges** (ADR **D-013**; see
[`../CHANGELOG_AND_DECISION_LOG.md`](../CHANGELOG_AND_DECISION_LOG.md)).

It exists because the per-repo copies of the version tooling had forked into four variants, and the
weakest of them let an invalid `0.10.6 → 0.10.8` version jump through both `make ci` and CI. The
canonical scripts close that hole twice over:

- **`check_version.py`** enforces the **strict single-increment rule** (exactly one of
  `X.Y.Z+1` / `X.Y+1.0` / `X+1.0.0` vs `origin/main`) plus consistency of every version-bearing
  file, and is the SAME file in three seats: the consumer CI job (`.cicd/scripts/common/…`), the
  vendored local copy (`scripts/check_version.py`, run by `make ci-version-check`), and the
  reusable [`bump-version-check.yml`](../../.github/workflows/bump-version-check.yml).
- **`bump_version.py`** computes bumps **from `origin/main`'s VERSION**, not the local file, so a
  double `make bump-patch` is idempotent instead of stacking to an invalid +2.
- **`version_targets.py`** is the one place that decides WHICH files carry the version
  (auto-detect by presence: `VERSION`, `pyproject.toml`, `vercel_api/pyproject.toml`,
  `src/*/__init__.py`, `package.json`, `package-lock.json`; or the repo's optional
  `scripts/version_targets.json` manifest, which is authoritative and hard-fails on a declared
  file that went missing — the rename-safety guard). Bump and check consume the same resolution,
  so they can never disagree. A new repo shape is a manifest entry or a new kind here — never a
  new script.

Beyond the three files, each sync PR also **rewrites the repo's `ci-version-check:` Makefile
recipe** to the canonical thin call of the vendored checker (registry key `makefile_patch`). The
patch replaces the target line plus its tab-indented recipe lines — a well-delimited make block —
idempotently; a Makefile without the target is reported `NEEDS MANUAL ATTENTION` without aborting
the fan-out.

## 2. Operating it

Like all privileged ops, it is issue-form driven and owner-gated:

1. Open a **"Ops · Distribute Ecosystem Dev Scripts"** issue
   ([`.github/ISSUE_TEMPLATE/ops-distribute-scripts.yml`](../../.github/ISSUE_TEMPLATE/ops-distribute-scripts.yml)) —
   pick `check` or `distribute`, select `ALL` or a subset of repos, optionally filter to one file.
2. Add the **`ops:distribute-scripts`** label. The workflow
   ([`.github/workflows/ops-distribute-scripts.yml`](../../.github/workflows/ops-distribute-scripts.yml))
   authorizes via the reusable owner-only gate, runs `distribute_scripts.py`, and comments the
   result on the issue.

CLI (same engine, e.g. from a local checkout):

```bash
GH_TOKEN=<CICD_PAT> python scripts/distribute_scripts.py check
GH_TOKEN=<CICD_PAT> python scripts/distribute_scripts.py distribute --repos kriegerdataforge,tiffanys-space
GH_TOKEN=<CICD_PAT> python scripts/distribute_scripts.py distribute --only check_version.py
```

## 3. Version-gate exemption

A scripts-sync PR does not bump VERSION. `scripts/common/check_version.py` exempts PRs whose
changed files are ALL synced paths — the registry `dest` paths, plus `Makefile` **only** on
`chore/scripts-sync-*` head branches (an ordinary Makefile-only PR still requires a bump). This
mirrors the kit exemption (ADR D-001 option B) and is registry-derived, so adding a file to the
registry auto-extends the exemption.

## 4. Versioning

`scripts/SCRIPTS_VERSION` is the sync marker (mirrors `kit/KIT_VERSION`): bump it whenever a
canonical script changes, so sync branches (`chore/scripts-sync-<version>`) and PR titles identify
the wave. Unlike the kit marker it is NOT itself a synced file.

## 5. Engine internals

The GitHub Contents/Refs transport, retrying session, repo selection and the generic
check/distribute fan-out loops live in
[`scripts/common/repo_sync.py`](../../scripts/common/repo_sync.py) (`SyncItem` = dest path + a
`desired(remote_text)` callable; whole-file items ignore the argument, patch items transform it and
raise `PatchError` when they cannot). `distribute_kit.py` shares the transport layer but keeps its
own loops (its white-box tests patch module-level names). Tests:
`scripts/tests/test_repo_sync.py`, `test_distribute_scripts.py`, `test_version_targets.py`,
`test_bump_version.py`, `test_check_version.py`.
