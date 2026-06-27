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

Repos, contracts, tables/migrations, identity/JWT, secrets/env (Terraform), user surfaces.

## Contract-first sequence

Ordered so no consumer is built before its contract exists.

| # | Slice (vertical, flag-gated) | Repo | Depends on | PR | State |
| --- | --- | --- | --- | --- | --- |
| 1 | schema + migration (expand) + endpoint | fitness-app-backend | — | #-- | planned |
| 2 | extend / regenerate shared contract | kriegerdataforge-sdk | 1 | #-- | planned |
| 3 | consumer / UI behind flag | fitness-app-frontend | 2 | #-- | planned |
| 4 | env vars / secrets / flag wiring | kriegerdataforge-terraform | 1 | #-- | planned |
| 5 | enable flag + e2e verify + contract (cleanup) migration | — | 1–4 | #-- | planned |

## Rollout & rollback

Flag enable plan (who / when), monitoring to watch, and how to revert safely.

## Decision log

Date-stamped notes as slices land and decisions are made (link ADRs for the big ones).

## Open questions

Unresolved items blocking or shaping remaining slices.
