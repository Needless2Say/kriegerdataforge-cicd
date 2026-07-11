# kriegerdataforge-cicd — Reference Documentation (interface & config reference)

**Context.** Centralized CI/CD platform library for the KDF ecosystem: reusable GitHub Actions workflows (workflow_call), a run-e2e composite-action engine, stdlib Python scripts (deployer gate, secret/token rotation, strict +1 version check, kit distribution), and JSON registries. No HTTP surface. Every workflow is consumed live from @main by tenant repos, so inputs/secrets/outputs are a public contract and any interface change is a breaking-change candidate. Docs are already mature and taxonomy-organized; docs/agent/, WORKFLOW.md, and skills.md are kit-synced (byte-identical, not locally editable), while AGENTS.md is repo-specific. All five candidate doc types map cleanly to real, high-value needs here; no additional type is warranted without forcing it.

You (an AI or a human) are asked to produce ONE durable, source-verified **reference** for a slice
of this repo's interface or configuration surface, so consumers and future maintainers can look
up exact contracts without re-reading the code. One surface per run.

**Learn the repo yourself — don't rely on this prompt for repo detail.** Start at `CLAUDE.md`
-> `AGENTS.md` (vision, module map, critical rules), `WORKFLOW.md` (lanes), and `skills.md`
(security playbook) where present. That's where this repo's real structure and invariants live.
Honor the stated vision; surface conflicts to me rather than resolving them.

**Pick the surface.**
- If I named one (HTTP endpoints, exported API, env-vars/config, data model, Terraform module
  contracts, reusable-workflow contracts, Rego policies), document exactly that.
- If I didn't, read `docs/reference/` for what exists, then propose a ranked list of the repo's
  un-referenced surfaces and ask me which. One surface per run.

**Output — and only this.**
- Write `docs/reference/<slug>.md` (kebab-case; create `docs/reference/` if absent) and update the
  reference index if one exists. This task WRITES A DOC — no code or config changes.

**Section template — use the shape that fits the surface; omit what's N/A and say so.**
1. **Overview** — what this surface is and who consumes it.
2. **The contract** — the exhaustive, source-verified table:
   - *Endpoints*: `METHOD /path`, auth/role, request + response shape, error/status codes.
   - *Exported API*: symbol, signature, params, return, raised errors, which extra/module gates it.
   - *Env / config*: var, required?, default, prod-vs-dev name, where it's read (`file:line`).
   - *Data model*: table, columns, constraints, indexes, migrations, ownership column
     (invariant: no FK to `kdfusers`; `user_id` is a plain column off the JWT).
   - *Module / workflow / policy contract*: inputs (name/type/default/required), outputs,
     managed resources / assertions, and a minimal caller snippet.
3. **Live vs. stub / deprecated** — call out what is not actually wired, with `file:line`.
4. **Related** — `[[links]]` to feature docs, guides, and the relevant spec.

**For `kriegerdataforge-cicd` specifically — what to prioritize (from the ecosystem doc assessment):**
Catalog reusable-workflow contracts (inputs type/default/required, secrets, outputs, permissions, minimal caller uses: snippet) plus the deployer/secret/kit registry JSON schemas and env vars — every entry treated as a public contract with consumer/caller notes.

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
