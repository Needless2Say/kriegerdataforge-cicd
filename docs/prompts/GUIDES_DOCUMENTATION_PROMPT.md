# kriegerdataforge-cicd — Guide Documentation (write a how-to / operational runbook)

**Context.** Centralized CI/CD platform library for the KDF ecosystem: reusable GitHub Actions workflows (workflow_call), a run-e2e composite-action engine, stdlib Python scripts (deployer gate, secret/token rotation, strict +1 version check, kit distribution), and JSON registries. No HTTP surface. Every workflow is consumed live from @main by tenant repos, so inputs/secrets/outputs are a public contract and any interface change is a breaking-change candidate. Docs are already mature and taxonomy-organized; docs/agent/, WORKFLOW.md, and skills.md are kit-synced (byte-identical, not locally editable), while AGENTS.md is repo-specific. All five candidate doc types map cleanly to real, high-value needs here; no additional type is warranted without forcing it.

You (an AI or a human) are asked to write ONE durable **how-to / operational runbook** for this
repo — a task-oriented guide a developer can follow start to finish. One guide per run.

**Learn the repo yourself — don't rely on this prompt for repo detail.** Start at `CLAUDE.md`
-> `AGENTS.md` (vision, module map, critical rules), `WORKFLOW.md` (lanes), and `skills.md`
(security playbook) where present. That's where this repo's real structure and invariants live.
Honor the stated vision; surface conflicts to me rather than resolving them.

**Pick the target.**
- If I named a task (deploy, migrate, rotate a key, run the e2e stack, scaffold a module), do that.
- If I didn't, survey the repo's real operational surface (Makefile targets, scripts, CI, compose)
  and `docs/guides/`, then propose a ranked list of not-yet-covered how-tos and ask me which.

**Output — and only this.**
- Write `docs/guides/<slug>.md` (kebab-case; create `docs/guides/` if absent) and update the
  guides index if one exists. This task WRITES A DOC — no code or config changes.

**Section template — omit a section only if truly N/A and say so.**
1. **Goal & when to use** — what this accomplishes and the situation that calls for it.
2. **Prerequisites** — tools, access, env, state assumed before step 1.
3. **Steps** — numbered, **copy-pasteable real commands** (from the Makefile/scripts — never an
   invented flag), each with the expected result.
4. **Verify** — how to confirm it worked.
5. **Troubleshooting** — a symptom -> cause -> fix table of the real failure modes.
6. **Rollback / cleanup** — how to undo or reset.
7. **Related** — `[[links]]` to reference docs and sibling guides.

**For `kriegerdataforge-cicd` specifically — what to prioritize (from the ecosystem doc assessment):**
Author step-by-step operational runbooks with copy-paste commands tied to the fail-closed gates and registries: tenant onboarding, adding/modifying a reusable workflow safely, and deployer-gate/version-check/secret-expiry/kit-drift troubleshooting.

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
