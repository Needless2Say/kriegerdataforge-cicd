# Feature references — kriegerdataforge-cicd

Durable, implementation-grade references for this repo's reusable workflows and engines — the
"public contract" the rest of the KDF ecosystem builds against. Each doc is written from the real
code (`file:line` cited) so a future human or AI can build against a feature without re-reading the
whole repo. See [`../prompts/`](../prompts/) for the authoring prompt these follow.

| Feature | Summary | Doc | Last updated | Status |
| --- | --- | --- | --- | --- |
| Agentic-workflow kit-sync engine | Distributes the shared agent kit (`skills.md` / `WORKFLOW.md` / `docs/agent/*`) from `kit/common/` to every tenant repo, detects drift, and opens review-gated sync PRs (never auto-merges). | [agentic-workflow-kit-sync.md](./agentic-workflow-kit-sync.md) | 2026-07-11 | draft |
| Version-scripts sync engine | Distributes the canonical version tooling (`bump_version.py` / `check_version.py` / `version_targets.py`) from `scripts/common/` to every repo's `scripts/`, rewrites each `ci-version-check` Makefile recipe to call it, and opens review-gated sync PRs (never auto-merges). Enforces the strict +1 version gate everywhere. | [version-scripts-sync.md](./version-scripts-sync.md) | 2026-08-11 | draft |
