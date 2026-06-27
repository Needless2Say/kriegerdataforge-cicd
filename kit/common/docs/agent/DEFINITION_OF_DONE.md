# Definition of Done — KriegerDataForge

Vendored byte-identical across every KDF repo. "CI is green" is necessary but **not**
sufficient. A change is *done* when it meets the bar below for **its change type**. The
`.github/PULL_REQUEST_TEMPLATE.md` is the checkbox form of this doc.

---

## Baseline — every change

- [ ] **Local `make ci` is green** (lint, type-check, tests, and the repo's security/audit steps).
- [ ] **Version bumped** with the repo's script; any required sync run (e.g. `make vercel-compact`).
- [ ] **Scoped** — the diff does only what the plan said; no unrelated drive-by changes.
- [ ] **Self-reviewed** — you read your own diff as a reviewer before opening the PR.
- [ ] **No secrets** in code, tests, commits, or logs.
- [ ] **PR describes** what changed and how it was verified; links the issue/epic if any.

## If it changes behavior or adds a feature

- [ ] **Tests added at the right tier** — unit for pure logic/validation/calculations; integration
      for endpoints/components/flows; end-to-end for a critical user path. New endpoints and server
      actions always get tests.
- [ ] **Edge cases + failure paths** covered, not just the happy path.
- [ ] **Docs updated** — the doc that describes this behavior (README/`docs/*`) reflects reality.

## If it's architectural or introduces a new pattern

- [ ] **Went through the design gate** — design doc + **ADR (`D-NNN`)** in
      `docs/CHANGELOG_AND_DECISION_LOG.md` (create it if absent), approved by the owner before building.
- [ ] **Decision log updated** with the outcome and any deviations from the design.

## If it changes data (schema / migration)

- [ ] **Backward-compatible migration** (expand now, contract later) — `main` stays deployable
      against both old and new at every step.
- [ ] **Rollback path** stated — how to revert safely if the deploy goes bad.
- [ ] **Migration runs cleanly** forward (and the down-path is sane).
- [ ] User foreign keys reference `kdf_users.id`; no new per-app user/identity tables.

## If it's security-relevant (auth, OIDC, tokens, sessions, authz, secrets, CSP, infra, CI)

- [ ] **Followed the matching [`skills.md`](../../skills.md) scenario.**
- [ ] **Server is authoritative** — security/$-relevant values recomputed, never trusted from the client.
- [ ] **Least privilege** — closed request schemas + field allow-lists; exact ownership checks;
      validated `iss`/`aud` with distinct per-client audiences.
- [ ] **OIDC/auth-protocol change** carried a design note and stays backward-compatible through the transition.
- [ ] Consider an **adversarial review** / **`/code-review ultra`** before handback.

## If it touches a cross-repo contract (API / OpenAPI / SDK)

- [ ] **Contract changed first**, consumers regenerated/updated after (backend → SDK → frontend).
- [ ] **Epic tracker** in `kriegerdataforge/docs/epics/<name>.md` updated; this PR links to it.
- [ ] Shipped **behind a feature flag**; the flag/rollout is documented.

## If it adds a user-facing surface

- [ ] **Observability** — meaningful logs/telemetry for the new path (no secrets/PII in logs).
- [ ] **Accessibility & responsive** basics for UI (keyboard, labels, mobile).
- [ ] **Errors are user-friendly**, not raw/technical; error details are sanitized.
