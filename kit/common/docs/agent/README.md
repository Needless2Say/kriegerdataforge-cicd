# The agentic-workflow kit — what's in this directory and how to use it

Kept byte-identical across every KDF repo by the kit-sync engine (canonical source:
`kriegerdataforge-cicd/kit/common/`; version marker: [`KIT_VERSION`](KIT_VERSION)). This directory
plus the repo-root [`WORKFLOW.md`](../../WORKFLOW.md) and [`skills.md`](../../skills.md) **is the
kit** — the shared operating standard that lets any developer or AI agent work the same way in
every KriegerDataForge repo. **Never edit the kit files locally** (a local edit is drift and gets
overwritten); change `kit/common/` in `kriegerdataforge-cicd` instead. Repo-specific agent
deep-dives (`<slug>.md`) may live alongside these files and are repo-owned.

## Reading order (first time in the ecosystem)

1. **`AGENTS.md`** (repo root, per-repo) — what this repo is, its vision, module map, critical rules.
2. [**`WORKFLOW.md`**](../../WORKFLOW.md) (repo root, kit) — the three-lane loop every task follows:
   Quick / Standard (plan → owner approves → implement → `make ci` → PR) / Epic.
3. [**`skills.md`**](../../skills.md) (repo root, kit) — the scenario-organized security playbook;
   read the matching scenario before any security-sensitive work.
4. This directory — the deeper standards below, consulted when their topic comes up.

## What each file here is for

| File | What it is | Consult it when |
| --- | --- | --- |
| [`AGENT_OPERATING_STANDARD.md`](AGENT_OPERATING_STANDARD.md) | The "why" behind the whole standard: the five principles, the three lanes with worked examples, who owns which contract, the glossary | You want to understand how the pieces fit, or you're prompting/reviewing an agent |
| [`DEFINITION_OF_DONE.md`](DEFINITION_OF_DONE.md) | The real bar beyond "CI is green", scaled by change type | **Before opening any PR** |
| [`DESIGN_AND_EPICS.md`](DESIGN_AND_EPICS.md) | The design gate + cross-repo Epic playbook (design doc → ADR → approval → vertical slices) | Anything complex, novel, or spanning repos |
| [`DOCUMENTATION_STANDARD.md`](DOCUMENTATION_STANDARD.md) | How repo docs are organized, kept honest, and kept discoverable (taxonomy, README front door, deprecate-with-banner) | Any documentation work |
| [`templates/design-spec.template.md`](templates/design-spec.template.md) | Copy-me 10-section design spec → `docs/design/{feature}.md` | The design gate applies |
| [`templates/adr-entry.template.md`](templates/adr-entry.template.md) | Copy-me ADR block → `docs/CHANGELOG_AND_DECISION_LOG.md` | Recording an architectural decision (`D-NNN`) |
| [`templates/epic-tracker.template.md`](templates/epic-tracker.template.md) | Copy-me tracker → `kriegerdataforge/docs/epics/{name}.md` (the hub) | Coordinating a cross-repo Epic |
| [`templates/contributor-onboarding.template.md`](templates/contributor-onboarding.template.md) | Copy-me onboarding spine → `docs/guides/CONTRIBUTOR_ONBOARDING.md` | Creating/refreshing a repo's contributor onboarding |
| [`KIT_VERSION`](KIT_VERSION) | The kit version this repo carries | Checking sync state / reporting drift |

## How to use the kit to work well here

- **Every task**: pick a lane in `WORKFLOW.md` and follow its loop — plan first, owner approves,
  `make ci` green locally before any PR, never self-merge.
- **Before a PR**: walk `DEFINITION_OF_DONE.md` for your change type; the PR template is its
  checkbox form.
- **Security-sensitive work** (auth, tokens, secrets, CSP, payments, infra, CI): open `skills.md`
  first and follow the matching scenario; when unsure, choose the fail-closed option.
- **Docs work**: follow `DOCUMENTATION_STANDARD.md` — code is ground truth; update the doc in the
  same PR as the behavior; deprecate with a banner, don't delete.
- **To improve the kit itself**: propose the change in `kriegerdataforge-cicd` (`kit/common/` +
  both `KIT_VERSION` markers), per *How the standard is maintained* in
  [`AGENT_OPERATING_STANDARD.md`](AGENT_OPERATING_STANDARD.md).
