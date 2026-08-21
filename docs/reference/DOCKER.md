# Docker Reference - kriegerdataforge-cicd

> **This repo has no `Dockerfile` and no `docker-compose.yml`, by rule.**
> The shared standard lives in [`DOCKER_CONVENTIONS.md`](../../../kriegerdataforge/docs/reference/DOCKER_CONVENTIONS.md); this file records why
> this repo sits outside it.

**Tier D** - no runtime service.

---

## Why there is no container

This is the control plane -- reusable workflows, operational scripts and the
Playwright suite. None of it is a service.

`make setup && make test` already works from a clean clone. A container would be a
*second* dependency path to keep in sync with the `.venv` path that CI actually uses, and
the two would drift -- the first time they disagreed, you would be debugging the
container instead of the code.

So the absence is deliberate. **Do not fill it.**

## How to run this repo

```bash
make setup     # Python venv + test requirements
make test      # the test suite
make ci        # the PR gate -- green before you push
```

Full target list: [`MAKEFILE.md`](MAKEFILE.md).

## If this repo ever grows a service

It moves to Tier A, B or C and adopts that tier **whole** - the same stage vocabulary, the
same compose skeleton, the same `docker-*` target names. It does not get a bespoke fourth
shape. Read the canon first, and update the tier table there in the same PR.

## The one exception: `e2e/docker-compose.shared.yml`

This repo *does* own a compose file, and it is **not** a Tier A/B/C stack. It is a
**test harness**: `e2e/ci_stack.py` builds every service from source, generates
ephemeral keys and OIDC credentials, and migrates and seeds the databases. No
`.env.local`, no bind mounts -- which is exactly what lets CI use it.

It builds each service `target: dev`, so it depends on the tier standards holding,
but it is exempt from the compose skeleton itself: it has no fixed ports (CI picks
them), no `restart` policy (it is torn down), and its own `e2e-net` rather than
`kdf-net`.

Driven by `make e2e-ci-up` / `e2e-ci` / `e2e-ci-down`. See `e2e/README.md`.

---

## Related

- [`../../../kriegerdataforge/docs/reference/DOCKER_CONVENTIONS.md`](../../../kriegerdataforge/docs/reference/DOCKER_CONVENTIONS.md) - the ecosystem standard, including the full Tier D list
- [`MAKEFILE.md`](MAKEFILE.md) - every target this repo exposes
