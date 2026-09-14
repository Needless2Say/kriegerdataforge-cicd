# kriegerdataforge-cicd. Agent Documentation (keep agent facing docs accurate, author deep dives)

**Context.** Centralized CI/CD platform library for the KDF ecosystem. Reusable GitHub Actions workflows (workflow_call), a run-e2e composite action engine, stdlib Python scripts (deployer gate, secret/token rotation, strict +1 version check, kit distribution), and JSON registries. No HTTP surface. Every workflow is consumed live from @main by tenant repos, so inputs/secrets/outputs are a public contract and any interface change is a breaking change candidate. Docs are already mature and taxonomy-organized. Docs/agent/, WORKFLOW.md, and skills.md are kit synced (byte identical, not locally editable), while AGENTS.md is repo-specific. All five candidate doc types map cleanly to real, high value needs here. No additional type is warranted without forcing it.

You (an AI or a human) are asked to keep this repo's **agent facing operational docs** truthful
and to author focused deep dives an agent needs, so the next agent works correctly instead of
against the grain. One target per run.

**Learn the repo yourself. Don't rely on this prompt for repo detail.** Start at `CLAUDE.md`
-> `AGENTS.md` (vision, module map, critical rules), `WORKFLOW.md` (lanes), and `skills.md`
(security playbook) where present. That's where this repo's real structure and invariants live.
Honor the stated vision. Surface conflicts to me rather than resolving them.

**Respect the kit sync boundary.** In this ecosystem `docs/agent/*` (AGENT_OPERATING_STANDARD,
DEFINITION_OF_DONE, DESIGN_AND_EPICS, `docs/agent/templates/*`), `WORKFLOW.md`, and `skills.md`
are **kit synced from `kriegerdataforge-cicd`. Byte identical, do NOT edit them locally**
(a local edit is flagged as drift and overwritten). The writable surface is the repo owned
`AGENTS.md`, `README`, `CLAUDE.md`, and **net new** repo specific files. If a kit file is wrong,
report it to me (the fix lands in `cicd/kit/common/`). Don't patch it here.

**Pick the target.**
- If I named one (refresh `AGENTS.md`'s module map, write a deep dive on X), do exactly that.
- If I didn't, audit the repo owned `AGENTS.md` against the actual code and report the drift
  (stale module map, renamed/moved modules, rules that no longer hold) plus a short ranked list
  of missing deep dives, then ask me which to fix/write. One target per run.

**Output, and only this.**
- To fix drift. Edit the **repo owned** `AGENTS.md` / `README` / `CLAUDE.md` in place.
- For a deep dive. Write `docs/agent/<slug>.md` (kebab-case). A NET NEW, repo specific file.
- NEVER touch the kit synced files listed above. This task changes only agent docs. No product
  code, config, or behavior.

**Section template (deep dive). Omit a section only if truly N/A and say so.**
1. **What an agent must know & why.** The mental model + the mistake this prevents.
2. **Area / module map.** The files involved, each a one liner + `file:line` anchor.
3. **Critical rules & invariants.** The repo's landmines, each phrased as a do/don't.
4. **Workflows & commands.** How to build/test/run/deploy the relevant slice.
5. **Gotchas & failure modes.** The non-obvious traps and their tells.
6. **Related docs.** `[[links]]` to reference/guides/design docs and the kit standards.

**For `kriegerdataforge-cicd` specifically. What to prioritize (from the ecosystem doc assessment):**
Refresh the repo root AGENTS.md (module map, critical rules, commands) against the actual workflows/scripts/registries. Enforce the hard rule that kit synced files (docs/agent/, WORKFLOW.md, skills.md) are never edited locally. Change kit/common/ source instead.

**Accuracy discipline.** Document what the code ACTUALLY does today, verified by reading the real
files. Never what you assume or what an older doc/comment claims. Cite `file:line`. Distinguish
current state from historical/ADR narrative (the latter is correct as of its date, don't
"correct" it). Never invent an endpoint, field, symbol, var, or flag you didn't see in the source.
If the code contradicts a doc, or you spot a bug / security gap / dead code while reading, record
it in your summary to me as a follow-up. Do NOT fix code here. That's a separate change under
the normal workflow.

**Hard constraints.** Never echo secret values or read `.pem` private keys / recovery codes.
Reference by name and location only. Never paste a real secret, token, `tfstate`/`tfplan`, or
credential into a doc. Use obvious placeholders. Keep per client OIDC audiences distinct in any
example.

**Plan first (light).** Confirm the target and its boundaries with me before drafting. For a
large or cross cutting doc, show me the outline first and get a nod before the full draft.
I review the doc. Don't claim coverage you didn't verify by reading the code.

**How you get there is your call.** Reading order, tooling, diagram style, depth within each
section. The above defines what the doc must contain and the guardrails, not how.
