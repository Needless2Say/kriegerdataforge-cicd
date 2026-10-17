# Feature references, kriegerdataforge-cicd

Durable, implementation grade references for this repo's reusable workflows and engines, the
"public contract" the rest of the KDF ecosystem builds against. Each doc is written from the real
code (`file:line` cited) so a future human or AI can build against a feature without re-reading the
whole repo. See [`../prompts/`](../prompts/) for the authoring prompt these follow.

| Feature | Summary | Doc | Last updated | Status |
| --- | --- | --- | --- | --- |
| Agentic workflow kit sync engine | Distributes the shared agent kit (`skills.md` / `WORKFLOW.md` / `docs/agent/*`) from `kit/common/` to every tenant repo, detects drift, and opens review gated sync PRs (never auto merges). | [agentic-workflow-kit-sync.md](./agentic-workflow-kit-sync.md) | 2026-07-11 | draft |
| CI's Postgres mirror | Every Postgres lane pulls Docker's official image by its digest from `ghcr.io/needless2say/postgres`, copied and proven public by `mirror-ci-images.yml`, the lanes proven on each pull request that changes code by `postgres-lane-proof`, a patch ordered so no lane names an image the mirror lacks, and no version ever deleted (ADR D-077). | [ci-postgres-mirror.md](./ci-postgres-mirror.md) | 2026-10-17 | live |
| Version scripts sync engine | Distributes the canonical version tooling (`bump_version.py` / `check_version.py` / `version_targets.py`) from `scripts/common/` to every repo's `scripts/kdf_scripts/` vendor dir (excluded from tenant kdf-fmt/ruff configs, ADR D-014), rewrites each `ci-version-check` Makefile recipe to call it, and opens review gated sync PRs (never auto merges). Enforces the strict +1 version gate everywhere. | [version-scripts-sync.md](./version-scripts-sync.md) | 2026-08-11 | draft |
