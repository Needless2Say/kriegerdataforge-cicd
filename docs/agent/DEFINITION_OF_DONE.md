# Definition of Done — KriegerDataForge

Kept byte-identical across every KDF repo by the kit-sync engine. "CI is green" is necessary but **not**
sufficient. A change is *done* when it meets the bar below for **its change type**. The repo's
`.github/PULL_REQUEST_TEMPLATE.md` is the checkbox form of this doc — keep it in sync: its Testing
section should reduce to a single **`make ci`** gate rather than a hand-maintained list of granular
sub-commands (which drift from the Makefile), and **every command it names must be a real target in
that repo's Makefile** (`make help`).

---

## Baseline — every change

- [ ] **Local `make ci` is green** (lint, type-check, tests, and the repo's security/audit steps).
- [ ] **Version bumped** with the repo's script — level by impact (no behavior/contract → patch;
      additive feature/contract → minor; breaking change → major); any required post-build sync run
      (e.g. `make vercel-compact`). The CI check enforces consistency + strictly-ahead, not the level.
- [ ] **Scoped** — the diff does only what the *approved plan* said; no unrelated drive-by changes.
      Ambition belongs in the **plan** (proposed to the owner); restraint belongs in the **diff** —
      never smuggle a bigger idea silently into the code.
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
- [ ] **Identity decoupling respected** — in the **hub** (`kriegerdataforge`), user FKs reference
      `kdf_users.id`. In a **tenant app DB** (fitness, tiffanys, …), `user_id` is a **plain column
      from the verified JWT — no cross-DB FK to `kdf_users`**, and no per-app user/identity table.

## If it's security-relevant (auth, OIDC, tokens, sessions, authz, secrets, CSP, infra, CI)

- [ ] **Followed the matching [`skills.md`](../../skills.md) scenario.**
- [ ] **Server is authoritative** — security/$-relevant values recomputed, never trusted from the client.
- [ ] **Incentive / gamification surfaces are abuse-resistant** (if present) — points/badges granted
      server-side from verified events only; award endpoints **idempotent** (keyed on the source event)
      against replay; streak windows on the **server clock**; grants append-only/auditable and
      rate-limited; leaderboards computed from server-owned totals. See the gamification scenario in
      [`skills.md`](../../skills.md).
- [ ] **Least privilege** — closed request schemas + field allow-lists; exact ownership checks;
      validated `iss`/`aud` with distinct per-client audiences.
- [ ] **OIDC/auth-protocol change** carried a design note and stays backward-compatible through the transition.
- [ ] **Adversarial review before handback** — a pass that tries to *refute* the change (missing
      authz, broken contract, violated rule). Use `/code-review ultra` or reviewer sub-agents if your
      tool supports them; otherwise do the refutation pass manually.

## If it touches a cross-repo contract (API / OpenAPI / SDK)

- [ ] **Contract changed first, in the repo that owns it**, consumers regenerated after — a per-app
      API through its backend's OpenAPI (`make openapi` → frontend `make generate-client`, a
      **read-only** generated client); the SDK slice only when the **auth/JWT** contract changes.
- [ ] **Epic tracker** in `kriegerdataforge/docs/epics/<name>.md` updated; this PR links to it.
- [ ] Shipped **behind a feature flag**; the flag/rollout is documented.

## If it adds a user-facing surface

- [ ] **Observability** — meaningful logs/telemetry for the new path (no secrets/PII in logs).
- [ ] **Accessibility & responsive** basics for UI (keyboard, labels, mobile).
- [ ] **Errors are user-friendly**, not raw/technical; error details are sanitized.
