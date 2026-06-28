# ADR entry template

> **How to use:** append this block to `docs/CHANGELOG_AND_DECISION_LOG.md` (create that file if
> your repo doesn't have one yet — it is the canonical ADR home across the ecosystem). Use the
> next id — **continue the repo's existing scheme if its log already uses one** (e.g. `ADR-NNN`); use
> `D-NNN` only when starting a fresh log. ADRs are append-only and immutable: to change a decision, add a new ADR that
> supersedes the old one — don't edit history.

## D-NNN — {short decision title}

- **Date:** YYYY-MM-DD
- **Status:** Proposed | Accepted | Superseded by D-MMM | Deprecated
- **Tier / scope:** Standard-plus | Epic · repos: {list}
- **Design doc:** {link, if any} · **Epic tracker:** {link, if cross-repo}

**Context.** What forced a decision — the problem, constraints, and the goal it serves.

**Decision.** The choice we are making, stated plainly.

**Alternatives considered.**

- Option A — rejected because…
- Option B — rejected because…

**Trade-offs.** What we gain and what we give up / take on.

**Consequences.** Follow-on work, migration notes, things future changes must respect
(e.g. flag cleanup, contract version, security invariant).
