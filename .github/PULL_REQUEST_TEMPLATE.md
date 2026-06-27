<!-- KriegerDataForge PR template. Full bar: ../docs/agent/DEFINITION_OF_DONE.md -->

## What & why
<!-- What changed and the reason. Link the issue / epic tracker if any. -->

## Lane
<!-- Quick | Standard | Epic (see WORKFLOW.md). For Epic, link the hub epic tracker + design doc/ADR. -->

## How verified
<!-- Commands run, tests added, manual checks. -->

## Definition of Done
See [`docs/agent/DEFINITION_OF_DONE.md`](../docs/agent/DEFINITION_OF_DONE.md) for the full,
change-type-specific bar. Baseline:

- [ ] Local `make ci` is green; version bumped (+ any required sync)
- [ ] Change is scoped and self-reviewed; no secrets in code/commits/logs
- [ ] Tests added at the right tier for new behavior (unit / integration / e2e)
- [ ] Docs updated; **ADR (`D-NNN`)** added if architectural
- [ ] Data change → backward-compatible migration + rollback path
- [ ] Security-relevant → followed the matching [`skills.md`](../skills.md) scenario
- [ ] Cross-repo contract → contract-first order + epic tracker updated + behind a feature flag
