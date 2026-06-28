# Epic — {epic name}

> **How to use:** copy this to `kriegerdataforge/docs/epics/{name}.md` (the ecosystem hub). ONE
> tracker per cross-repo epic; every slice PR in every repo links back here. This is the single
> source of truth for "where is this epic." See [`../DESIGN_AND_EPICS.md`](../DESIGN_AND_EPICS.md).
>
> Status: Planning | In progress | Integrating | Done | Parked · Flag: `{feature_flag_name}`
> (default off) · Started: YYYY-MM-DD · Design doc: {link} · ADRs: D-NNN, D-MMM

## Goal

What this epic delivers and the product goal it advances (one paragraph).

## Blast radius

Contracts, tables/migrations, identity/JWT, secrets/env (Terraform), user surfaces — and, for
**every repo touched** (read each repo's `AGENTS.md` first):

| Repo | Its vision / purpose (1 line) | Critical rules to respect | Vision honored? / conflict to escalate |
| --- | --- | --- | --- |
| {repo} | | | |

## Contract-first sequence

Ordered so no consumer is built before its contract exists. **Each contract is defined in the repo
that owns it:** a per-app API in that app's backend (consumed via its OpenAPI-generated, read-only
client); the auth/JWT contract in `kriegerdataforge-sdk` (add an SDK slice **only** if that changes).

| # | Slice (vertical, flag-gated) | Repo | Depends on | PR | State |
| --- | --- | --- | --- | --- | --- |
| 1 | schema + migration (expand) + endpoint | fitness-app-backend | — | #-- | planned |
| 2 | regenerate typed client (`make openapi` → `make generate-client`) | fitness-app-backend → fitness-app-frontend | 1 | #-- | planned |
| 3 | consumer / UI on the generated client, behind flag | fitness-app-frontend | 2 | #-- | planned |
| 4 | env vars / secrets / flag wiring | kriegerdataforge-terraform | 1 | #-- | planned |
| 5 | enable flag + e2e verify + contract (cleanup) migration | — | 1–4 | #-- | planned |

> An **auth/JWT** contract change instead leads with a `kriegerdataforge-sdk` slice (extend/regenerate
> the shared contract), which lands before the backends that consume it.

## Rollout & rollback

Flag enable plan (who / when), monitoring to watch, and how to revert safely.

## Decision log

Date-stamped notes as slices land and decisions are made (link ADRs for the big ones).

## Open questions

Unresolved items blocking or shaping remaining slices.
