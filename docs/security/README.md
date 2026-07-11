# Security — `kriegerdataforge-cicd`

Security reference for the **CI/CD control plane** — the reusable workflows, composite action,
gate scripts, and registries every KDF tenant repo consumes live from `@main`. Each doc grounds its
claims in the real implementing file (`file:line`) and states the fail mode.

> This is the *control-plane* security surface (supply-chain + automation integrity). It is
> distinct from the disclosure policy in [`../../SECURITY.md`](../../SECURITY.md) (how to report a
> vulnerability) and the ecosystem-wide playbook `skills.md` (kit-synced, not edited locally).

## Documents

- [Security model & threat posture of the CI/CD control plane](CONTROL_PLANE_SECURITY.md) — the
  control catalog: ephemeral least-privilege GitHub-App tokens (auto-revoked), the deployer-registry
  fail-closed gate + Environment protection, the owner-only ops gate, secret handling (never
  echoed, never baked into an image layer via BuildKit `--mount=type=secret`), strict +1 version
  discipline, supply-chain pinning, and the tenant-agnostic trust boundary. Includes the
  least-privilege permissions matrix and the live-vs-advisory call-outs.

## See also

- [`../reference/WORKFLOWS.md`](../reference/WORKFLOWS.md) — per-workflow inputs/secrets/outputs and
  the deployment/Environment-gate model.
- [`../guides/SECRET_ROTATION.md`](../guides/SECRET_ROTATION.md) — the secret-rotation runbook.
- [`../../SECURITY.md`](../../SECURITY.md) — vulnerability disclosure process and in-scope surface.
