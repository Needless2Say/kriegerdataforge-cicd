# kriegerdataforge-cicd — Design & ADR Documentation (author a design doc + decision record)

**Context.** Centralized CI/CD platform library for the KDF ecosystem: reusable GitHub Actions workflows (workflow_call), a run-e2e composite-action engine, stdlib Python scripts (deployer gate, secret/token rotation, strict +1 version check, kit distribution), and JSON registries. No HTTP surface. Every workflow is consumed live from @main by tenant repos, so inputs/secrets/outputs are a public contract and any interface change is a breaking-change candidate. Docs are already mature and taxonomy-organized; docs/agent/, WORKFLOW.md, and skills.md are kit-synced (byte-identical, not locally editable), while AGENTS.md is repo-specific. All five candidate doc types map cleanly to real, high-value needs here; no additional type is warranted without forcing it.

You (an AI or a human) are asked to author ONE **design document + ADR** for a proposed change in
this repo — the artifact the owner-approves-before-code design gate requires. This writes a
PROPOSAL; it does not implement anything.

**Learn the repo yourself — don't rely on this prompt for repo detail.** Start at `CLAUDE.md`
-> `AGENTS.md` (vision, module map, critical rules), `WORKFLOW.md` (lanes), and `skills.md`
(security playbook) where present. That's where this repo's real structure and invariants live.
Honor the stated vision; surface conflicts to me rather than resolving them.

**Respect the kit-sync boundary.** In this ecosystem `docs/agent/*` (AGENT_OPERATING_STANDARD,
DEFINITION_OF_DONE, DESIGN_AND_EPICS, `docs/agent/templates/*`), `WORKFLOW.md`, and `skills.md`
are **kit-synced from `kriegerdataforge-cicd` — byte-identical, do NOT edit them locally**
(a local edit is flagged as drift and overwritten). The writable surface is the repo-owned
`AGENTS.md`, `README`, `CLAUDE.md`, and **net-new** repo-specific files. If a kit file is wrong,
report it to me (the fix lands in `cicd/kit/common/`) — don't patch it here.

**Pick the target.**
- Describe the proposed change; confirm its scope and boundaries with me before drafting.
- Reuse this repo's `design-spec` / `adr-entry` templates (in `docs/agent/templates/`) where they
  exist — follow them, don't edit them.

**Output — and only this.**
- Write the design doc `docs/design/<slug>.md` (create `docs/design/` if absent).
- Append the decision as an immutable `D-NNN` ADR entry to `docs/CHANGELOG_AND_DECISION_LOG.md`
  (create it if absent; never rewrite prior entries).
- This task WRITES A PROPOSAL — no product code, migrations, or config change.

**Section template (design doc) — omit a section only if truly N/A and say so.**
1. **Problem & context** — what's wrong / needed and why now.
2. **Goals / non-goals** — scope fence.
3. **Options considered** — 2+ with trade-offs.
4. **Decision & rationale** — the chosen option and why.
5. **Blast radius & sequencing** — cross-repo impact and contract-first ordering (who ships first).
6. **Invariants honored** — how it respects THIS repo's hard constraints (the landmines below).
7. **Migration & backward-compat** — transition plan; behavior during rollout.
8. **Rollout / flags · Testing · Open questions.**
**ADR entry:** `D-NNN`, date, status (proposed/accepted), the decision in one paragraph, and
consequences.

**For `kriegerdataforge-cicd` specifically — what to prioritize (from the ecosystem doc assessment):**
Follow the existing design-note + paired impl-LOG + ADR (D-NNN) convention and the kit templates in docs/agent/templates/; force cross-repo blast-radius, consumer-coordination/breaking-change ordering, and fail-closed/least-privilege/tenant-agnostic analysis.

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
