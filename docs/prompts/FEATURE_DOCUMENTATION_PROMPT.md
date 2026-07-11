# kriegerdataforge-cicd — Feature Documentation (write one feature at a time)

**Context.** This repo is the ecosystem's shared CI/CD: reusable GitHub Actions workflows, the `run-e2e` engine, GitHub-App token minting, secret-sync, and the agent automation — all consumed by the other repos as a PUBLIC CONTRACT. A "feature" here is a reusable workflow or engine. You (an AI or a human) are asked to produce ONE
durable, implementation-grade feature reference so future humans and AIs can build
against it without re-reading the whole codebase. Document one feature per run.

**Learn the repo yourself — don't rely on this prompt for repo detail.** Start at
`CLAUDE.md` -> `AGENTS.md` (vision, module map, critical rules), `WORKFLOW.md` (lanes),
and `skills.md` (security playbook) where present. That's where this repo's real
structure and invariants live. Honor the stated vision; surface conflicts to me rather
than resolving them.

**Pick the feature.**
- If I named one, document exactly that — confirm its boundaries with me if fuzzy
  (where it starts/stops, which flows are in vs out).
- If I didn't, first read `docs/features/README.md` for what's already covered, then
  survey the repo and propose a short, ranked list of documentable, not-yet-covered
  features and ask me which. Examples of a "feature" here: a reusable workflow (version-check, Vercel deploy, `run-e2e` engine, secret-sync, GitHub-App token minting), the PR-sync engine, and the agent skeleton.

**Output — and only this.**
- Write `docs/features/<feature-slug>.md` (kebab-case; create `docs/features/` if absent).
- Update the index `docs/features/README.md` (create if absent): a table of
  feature · one-line summary · link · last-updated · status (draft/reviewed).
- This task WRITES A DOC. It does not change code, config, or behavior. The ONLY files
  you touch are under `docs/features/`.

**Section template — follow in order; omit a section only if truly N/A and say so.**
1. **Overview** — what it is, why it exists, who/what consumes it (2–4 sentences).
2. **Architecture & data flow** — the components and how a job / token / artifact moves through
   them; an ASCII diagram if it clarifies. Mark cross-repo boundaries (other repos call these reusable workflows via `uses:` — treat every input/secret/output as a public contract; a repo depends only on what it consumes downstream, never its upstream consumers).
3. **Key modules** — the files that implement it, each a one-liner + a `file:line`
   anchor to its entry point. This is the map an implementer follows.
4. **Workflow contract (inputs / secrets / outputs)** — the reusable workflow's contract: `inputs` (name, type, default, required?), `secrets`, `outputs`, the events/permissions it needs, and a minimal caller `uses:` snippet. This is what other repos depend on.
5. **Inputs, outputs & state** — the workflow's inputs/outputs and any persisted state — caches, artifacts, concurrency groups, and environment/deployment targets.
6. **Security & authz** — token scoping (GitHub-App, ephemeral, least-privilege, auto-revoked at job end), secret handling (never echoed, never baked into an image layer via `--mount=type=secret`), and the trust boundary the workflow enforces. Cite OWASP / CI-security guidance where it applies.
7. **Configuration & environment** — env vars / settings that enable or tune it,
   defaults, and prod-vs-dev differences.
8. **Usage & how to extend** — a concrete walkthrough plus the safe seams to extend it.
9. **Testing** — where its tests live, how to run them, what's covered, notable gaps.
10. **Related docs & references** — `[[links]]` to sibling feature docs, guides,
    ADRs/design docs, and external specs.

**Accuracy discipline.** Document what the code ACTUALLY does today, verified by reading
the real files — never what you assume or what an older doc/comment claims. Cite
`file:line`. Distinguish current-state from historical/ADR narrative (the latter is
correct as-of-its-date — don't "correct" it). Never invent an endpoint, field, symbol,
or flag you didn't see in the source. If the code contradicts a doc, or you spot a
bug / security gap / dead code while reading, record it in your summary to me as a
follow-up — do NOT fix code here; that's a separate change under the normal workflow.

**Hard constraints.** Never echo secret values or read `.pem` private keys / recovery
codes — reference by name and location only. Never paste a real secret, token,
`tfstate`/`tfplan`, or credential into a doc; use obvious placeholders. Keep per-client
OIDC audiences distinct in any example.

**Plan first (light).** Confirm the feature and its boundaries with me before drafting.
For a large or cross-cutting feature, show me the section outline first and get a nod
before the full draft. I review the doc — don't claim coverage you didn't verify by
reading the code.

**How you get there is your call** — reading order, tooling, diagram style, depth within
each section. The above defines what the doc must contain and the guardrails, not how.
