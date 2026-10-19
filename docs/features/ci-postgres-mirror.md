# Feature. CI's Postgres from the owner's mirror

_Last updated: 2026-10-17 (the lanes moved to the mirror, ADR D-077) · Status: live_

## 1. Overview

Every reusable lane here that starts a Postgres service, `ci-python-integration.yml`, `ci-python-mutation.yml` and
`ci-python-system.yml`, pulls `ghcr.io/needless2say/postgres` by the index digest
`sha256:ca0bd484cb98bf4b24eb1010e73fb3fcbd6714d240fbc1a10eea5b7dbecb641d`, PostgreSQL 16.15, `server_version_num`
160015. That image is Docker's official one, copied whole and byte for byte by `mirror-ci-images.yml` and proven
public on a runner (ADR **D-077**, see [`../CHANGELOG_AND_DECISION_LOG.md`](../CHANGELOG_AND_DECISION_LOG.md)).

It exists because a hosted runner shares its address with other tenants, and both registries the lanes used before
count their allowance by address. Docker Hub's pull limit failed whole jobs before a test ran (D-064), and then AWS
ECR Public's data limit did the same, "toomanyrequests: Data limit exceeded". GitHub documents anonymous pulls of a
public package and free storage and bandwidth for one, and the owner decides how long the image is kept.

A caller changes nothing. No lane's input, output, secret or permission changed, only each service's host.

Since D-080 the same copier keeps every image CI pulls, runs once a day as well, and proves each with a second job,
`verify-images`. [ci-images-mirror.md](./ci-images-mirror.md) describes the whole of it. The Postgres lanes and their
kept entry below are unchanged.

## 2. How it fits together

```
  docker.io / public.ecr.aws / mirror.gcr.io      (Docker's official image, the same digest on each)
                     │
                     │  skopeo copy --all --preserve-digests, by digest       mirror-ci-images.yml, job copy
                     ▼                                                        (main alone, packages: write)
  ghcr.io/needless2say/postgres@sha256:ca0bd484…   tag 16.15, public
                     │
        ┌────────────┼──────────────────────────────┐
        ▼            ▼                              ▼
  job verify     postgres-lane-proof           every caller's lane
  (no token      (ci.yml, the integration      (ci-python-integration / -mutation / -system,
   scope, reads   lane by a local reference,    the runner pulls the service before the
   --no-creds)    on each pull request)         first step)
```

- **The copier,** `.github/workflows/mirror-ci-images.yml`, runs on `main` alone, at a push that changes its own file
  and at the owner's dispatch, which takes no input. Its `KEPT` list holds each kept entry, its digest, its tag and
  its `server_version_num`, the newest last.
  - `copy` holds `packages: write` through the job's own token and checks out nothing and runs no action. An entry
    whose index and every manifest the index lists are already on the mirror, each hashed to its digest, is left as
    it is. Any other is copied from ECR Public, then Docker Hub, then Google's mirror, each by the same digest, and
    held to the same check after the copy.
  - `verify` has `permissions: {}`. It starts the lanes' own service by the newest kept digest, holds its
    `server_version_num` by host and port, and reads every kept entry's index and listed manifests with
    `skopeo inspect --raw --no-creds`, the proof the package is public.
- **The lane proof,** the `postgres-lane-proof` job of `ci.yml`, calls `ci-python-integration.yml` by a local
  reference, installs and migrates nothing, and holds the service's `server_version_num` to the kept entry the lanes'
  digest names. It runs on every pull request here that changes code, a fork's too since it names no secret, and a
  docs only pull request skips it with every lane (D-075). It is not a required check. The three lanes' service blocks differ by the database's name alone, so the integration lane stands for them.
- **The login.** A hosted runner logs in to GitHub's registry with the job's own token before it pulls a service from
  there, so a lane's log shows a `docker ... login ghcr.io` line in "Initialize containers" before the pull. It names
  no secret and the token is the job's own, so D-035's secretless lanes hold.

## 3. The test that holds it

`scripts/tests/test_workflow_service_images.py`.

- **The lanes.** One constant, `LANE_IMAGE`, names the lanes' image, now the mirror. Every lane's service line names
  it by a digest, and every other way of naming or pulling an image in a workflow is refused, D-064's rule on the
  text. Every lane names the same digest, one the copier keeps.
- **The copier.** Read by a strict rule of its own. Its triggers, its `main` guard, each job's declared permissions,
  its `needs`, its concurrency, `verify`'s service, its target and its sources are each held whole, a key's line and
  every line below it. It holds no action, its kept entries each a digest, a tag and a version, and its every line
  that names an image or a pull one the test knows. `verify` names the newest kept entry.
- **Everywhere.** No workflow names a `credentials` key, `persist-credentials` apart, and a declared grant that can
  write a package, in any quoting, a flow mapping or an escaped key, appears in the copier's `copy` job alone.
- **The proof.** `postgres-lane-proof` calls the integration lane, takes the skip expression, names no secret, and
  expects the version of the kept entry the lanes name.

## 4. A Postgres patch, a rollback and a way back

A patch is ordered, so no lane names an image the mirror does not hold.

1. A pull request appends the new entry to `KEPT` and moves `verify`'s service line to it, the lanes unchanged. Its
   merge runs the copier, which copies and proves it.
2. Then the pull requests that move the lanes, each lane's digest and the version `postgres-lane-proof` expects moving
   together, cicd's proven by its own `postgres-lane-proof`, each other repo's that starts the same service by its own
   run. A pull request that appended an entry and moved a lane to it at once would fail its `postgres-lane-proof` on
   the missing image.

The old entry stays kept, so a rollback is a lanes' pull request naming it again with its version. Moving the lanes
back to ECR Public's gallery is their service lines and the test's `LANE_IMAGE` together.

## 5. Never delete a version

**No version of the package, tagged or untagged, is ever deleted.** The index's platform and attestation manifests
show on GitHub as untagged versions, which a tidy of untagged versions would remove, and every Postgres lane in every
repo then fails before a test runs. GitHub restores a deleted package within 30 days while its name is not reused, and
a dispatch of the copier copies the same digest again while a source still serves it.

## 6. Reading a failure

- **A lane fails in "Initialize containers" on its pull from `ghcr.io`.** Read the error. A rate limit or an outage of
  GitHub's registry is not the code under test. The owner decides between a fix and moving the lanes back to ECR
  Public's gallery, section 4.
- **The copier's `copy` fails.** Each source's refusal is a warning in its log. All three refusing fails the job, and
  a dispatch on a new runner tries again. A hash that does not match fails the job, and the next run repairs the copy.
- **The copier's `verify` fails** on "cannot be read with no credentials". The package is not public, so set it public
  on its page and dispatch the copier again.

## 7. Files

| File | Role |
| --- | --- |
| `.github/workflows/mirror-ci-images.yml` | The copier, `copy` and `verify` |
| `.github/workflows/ci-python-integration.yml`, `ci-python-mutation.yml`, `ci-python-system.yml` | The lanes, each service on the mirror |
| `.github/workflows/ci.yml` | `postgres-lane-proof` |
| `scripts/tests/test_workflow_service_images.py` | The rules of section 3 |
| `docs/reference/WORKFLOWS.md` | The lanes' paragraph and the section "CI's Postgres mirror" |
