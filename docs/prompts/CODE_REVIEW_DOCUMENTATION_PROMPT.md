# kriegerdataforge-cicd — Code-Review Documentation (author the review playbook, or capture findings)

**Context.** Centralized CI/CD platform library for the KDF ecosystem: reusable GitHub Actions workflows (workflow_call), a run-e2e composite-action engine, stdlib Python scripts (deployer gate, secret/token rotation, strict +1 version check, kit distribution), and JSON registries. No HTTP surface. Every workflow is consumed live from @main by tenant repos, so inputs/secrets/outputs are a public contract and any interface change is a breaking-change candidate. Docs are already mature and taxonomy-organized; docs/agent/, WORKFLOW.md, and skills.md are kit-synced (byte-identical, not locally editable), while AGENTS.md is repo-specific. All five candidate doc types map cleanly to real, high-value needs here; no additional type is warranted without forcing it.

You (an AI or a human) are asked to produce durable **code-review documentation** for this repo:
either the per-repo review playbook (what a reviewer must scrutinize here) or a captured record
of a specific review's findings. One target per run.

**Learn the repo yourself — don't rely on this prompt for repo detail.** Start at `CLAUDE.md`
-> `AGENTS.md` (vision, module map, critical rules), `WORKFLOW.md` (lanes), and `skills.md`
(security playbook) where present. That's where this repo's real structure and invariants live.
Honor the stated vision; surface conflicts to me rather than resolving them.

**Pick the mode — check what already exists first.**
- If this repo ALREADY has a review format (a `CODE_REVIEW_GUIDE.md` with trap IDs, or living
  per-domain audits with stable finding IDs), **reuse it**: capture a NAMED review's findings in
  that exact format/IDs — do not reinvent the checklist.
- If none exists, **author the per-repo review playbook** — the repo-specific failure modes and
  invariants a reviewer must check every time.

**Output — and only this.**
- Write under `docs/code_review/` (create if absent), following the repo's existing file/ID
  convention where there is one. Update the review index if the repo keeps one.
- This task WRITES DOCS. It does not change product code or behavior.

**Section template (playbook) — omit a section only if truly N/A and say so.**
1. **What reviews here must catch** — the risk surface (auth, money, PII, contracts, migrations…).
2. **Invariants & landmines checklist** — each a concrete review gate keyed to THIS repo, with a
   `file:line` example of the right and wrong shape.
3. **Failure modes with tells** — the repeatable bugs and how they show up.
4. **Severity guidance** — what's blocking vs. nit here; default findings to *refuted* until you
   can construct the concrete failure (inputs -> wrong output).
5. **How to run a review** — what to read first, order, tooling.
6. **Finding-ID convention** — reuse the repo's existing scheme; define one only if none exists.
7. **Related** — `[[links]]` to skills.md scenarios and reference docs.

**For `kriegerdataforge-cicd` specifically — what to prioritize (from the ecosystem doc assessment):**
Center the checklist on the public-contract breaking-change matrix (adding required inputs, renaming/removing inputs/secrets/outputs), action SHA/tag pinning, minimum permissions, environment: gate + deployer-registry fail-closed, strict +1 VERSION bump, no secret echo/log leaks, and the tenant-agnostic litmus.

**Accuracy discipline.** Document what the code ACTUALLY does today, verified by reading the real
files — never what you assume or what an older doc/comment claims. Cite `file:line`. Distinguish
current-state from historical/ADR narrative (the latter is correct as-of-its-date — don't
"correct" it). Never invent an endpoint, field, symbol, var, or flag you didn't see in the source.
If the code contradicts a doc, or you spot a bug / security gap / dead code while reading, record
it in your summary to me as a follow-up — do NOT fix code here; that's a separate change under
the normal workflow.

**Hard constraints.** Never echo secret values or read `.pem` private keys / recovery codes —
reference by name and location only. Never paste a real secret, token, `tfstate`/`tfplan`, or
credential into a doc; use obvious placeholders. Keep per-client OIDC audiences distinct in any
example.

**Plan first (light).** Confirm the target and its boundaries with me before drafting. For a
large or cross-cutting doc, show me the outline first and get a nod before the full draft.
I review the doc — don't claim coverage you didn't verify by reading the code.

**How you get there is your call** — reading order, tooling, diagram style, depth within each
section. The above defines what the doc must contain and the guardrails, not how.
