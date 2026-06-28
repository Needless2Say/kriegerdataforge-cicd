# Design — {feature name}

> **How to use:** copy this to `docs/design/{feature}.md` (or paste it into the epic tracker for
> cross-repo work). Fill every section; delete one only if you can say why it doesn't apply. See
> [`../DESIGN_AND_EPICS.md`](../DESIGN_AND_EPICS.md) for when this is required and how it's approved.
>
> Status: Draft | In review | Approved (date) | Superseded · Tier: Standard-plus | Epic ·
> Repos touched: {list} · Decision log: D-NNN · Epic tracker: {link if cross-repo}

## 1. Overview

- **One-sentence description:**
- **Category:** core | differentiator | parity | delight | tech-debt
- **Target users / personas:**
- **Problem statement:** what hurts today and why it matters to the product goal.

## 2. User stories

- As a {user}, I want to {action}, so that {benefit}.
- (secondary, edge-case stories…)

## 3. Requirements (MoSCoW)

- **Must have:**
- **Should have:**
- **Could have:**
- **Won't have (now):** explicit scope boundary.

## 4. UX / interaction

User flow (entry → steps → exit), key screens/components, mobile + accessibility, error states.

## 5. Technical design

- **Best-case design:** what would best serve this repo's (and every touched repo's) vision if
  effort weren't the constraint? Name it first — *then* state what you're proposing now and why.
- Approach & key components; how it fits existing architecture and patterns.
- **API contract** (endpoints, request/response schemas) — defined in the repo that **owns** it,
  *before* consumers; a per-app API reaches the frontend via its generated client (never hand-edited).
- **Feature flag:** name + default + enable plan.
- Alternatives considered (and why rejected) — mirror into the ADR.

## 6. Data

Tables / fields / enums; migration plan (expand→contract); backward-compatibility + rollback.
**Identity:** in the **hub**, user FKs reference `kdf_users.id`; in a **tenant app DB**, `user_id`
is a plain column from the verified JWT — **no cross-DB FK to `kdf_users`**, no per-app user table.

## 7. Cross-repo / blast radius

Contracts, secrets/env (Terraform), identity/JWT impact, ordering. (Epic → also fill the tracker.)
**For every repo you touch, fill this in — read each repo's `AGENTS.md` first:**

| Repo | Its vision / purpose (1 line) | Critical rules this change must respect | How this design honors them (or a conflict to escalate) |
| --- | --- | --- | --- |
| {repo} | | | |

A conflict between two repos' visions or rules is **surfaced to the owner**, never resolved silently.

## 8. Success metrics

Primary KPI + secondary KPIs + target benchmarks; how measured.

## 9. Risks & mitigation

Technical / adoption / security / cost risks and how each is handled.

## 10. Open questions & assumptions

Load-bearing assumptions (surface to owner). Unknowns to resolve before/with build.
