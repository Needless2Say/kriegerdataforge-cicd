# Feature. Every CI image from the owner's mirror

_Last updated: 2026-10-19 (the shared E2E stack moved to the mirror, ADR D-080) · Status: live_

## 1. Overview

Every image a runner pulls to build, start or scan with comes from the owner's mirror on GitHub's registry,
`ghcr.io/needless2say/<name>`, copied and proven public by `mirror-ci-images.yml` (ADR **D-080**, which grows
**D-077**'s Postgres mirror, see [`../CHANGELOG_AND_DECISION_LOG.md`](../CHANGELOG_AND_DECISION_LOG.md)).

| Package | What pulls it | How it is kept |
| --- | --- | --- |
| `postgres:16.15` | The three Postgres lanes here, by digest | `KEPT`, by its index digest (D-077, [ci-postgres-mirror.md](./ci-postgres-mirror.md)) |
| `postgres:16.15-alpine` | The shared E2E stack's database and each tenant's E2E stack, by digest | `PINNED`, by its index digest |
| `caddy:2.10.2-alpine` | The shared E2E stack's two edges, by digest | `PINNED` |
| `mailpit:v1.31.2` | The shared E2E stack's mail sink, by digest | `PINNED` |
| `checkov:3.3.6` | The terraform repository's security scan, by digest | `PINNED` |
| `node:24-alpine` | The base of every Next.js app's Dockerfile, by tag | `FOLLOWED`, the digest Docker Hub names for the tag, once a day |
| `python:3.14-slim` | The base of every FastAPI app's Dockerfile, by tag | `FOLLOWED` |

It exists because a hosted runner shares its address with other tenants, and the registries CI used before count
their allowance by address. Docker Hub's anonymous limit failed whole jobs (D-064), and then AWS ECR Public's data
cap did, until it refused even a tag's manifest of a few kilobytes, `429 Too Many Requests ... toomanyrequests: Data
limit exceeded`, before a layer was built. No build cache, retry or rerun on the same pool of addresses avoids that.
GitHub documents anonymous pulls and free bandwidth for a public package, and the owner decides how long each image is
kept.

No job that builds a pull request's code gains a secret, a credential or a permission. Every consumer pulls the
public packages anonymously, as it pulled ECR Public before. No reusable workflow's input, output or secret changed.

## 2. How it fits together

```
  Docker Hub, HEAD of a followed tag                    ECR Public / Docker Hub / Google's mirror,
  (the one answer that names a followed digest)          a publisher's own registry (bytes by digest)
                     │                                              │
                     └──────────────┬───────────────────────────────┘
                                    │  skopeo copy --all --preserve-digests --src-no-creds
                                    ▼                     mirror-ci-images.yml, job copy (main alone)
                     ghcr.io/needless2say/<name>          gate, holds, kept, pinned, followed, tamper check
                                    │
       ┌──────────────┬─────────────┼─────────────────┬────────────────────────┐
       ▼              ▼             ▼                 ▼                        ▼
  job verify    job verify-images  the Postgres   the E2E stacks         each Dockerfile's FROM
  (D-077's      (no permissions,   lanes          (shared here, and      and the terraform scan
   service)      reads and pulls                   one in each tenant)    (in their own repos)
                 every entry with
                 no credentials)
```

- **The copier,** `.github/workflows/mirror-ci-images.yml`, runs on `main` alone, at a push that changes its own
  file, at the owner's dispatch, which takes no input, and once a day at 06:23 UTC. Its env names every entry in its
  own text, `SOURCES`, `KEPT`, `PINNED`, `FOLLOWED`, and `WATCH`, which only the weekly ecosystem watch reads.
- **Its gate.** A run compares the copier's blob at its own commit with `main`'s, fetched anonymously with no blob.
  The same blob runs as current. Another blob applies no hold and moves no followed tag, green on a first attempt and
  red on a rerun, which a dispatch from `main` answers.
- **A followed tag** is decided by Docker Hub alone, by an uncounted `HEAD` asking for an index. Before it moves, the
  digest the mirror's tag holds is asked the same way, the tamper check. A 404 records that digest, repairs the tag
  and ends the run red.
- **A hold** writes a digest the package already holds after a followed tag, set from the mirror's own copy and never
  sent to Docker Hub, with a warning at every run naming the held digest and Docker Hub's current one.
- **Every copy** is by a digest, from each source in turn with no credentials, so the job's write token reaches none.
  An entry is left as it is only when its index, an index by its own `mediaType`, every manifest it lists and the
  runner's platform's layers are present and its tag hashes to its digest.
- **The proofs** have no permissions and run on `main` after a copy that succeeded or failed. `verify` starts D-077's
  Postgres service. `verify-images` reads every entry and pulls each followed tag and pinned entry with no credentials,
  so a package still private fails closed, and holds each followed tag to the digest the copy chose.

## 3. The shared E2E stack

`e2e/docker-compose.shared.yml` names the mirror for its four image lines, the database, both Caddy edges and Mailpit,
each by the digest its `PINNED` entry holds. A release's journey starts it on a runner, so a release no longer waits on
a registry's cap. Its comment says the order of a new service digest. The tenants' own E2E stacks name the same
Postgres digest on the mirror in their repositories.

## 4. The test that holds it

`scripts/tests/copier_rule.py` holds the copier's text, read by `test_workflow_service_images.py` and
`test_mirror_ci_images.py`.

- **The copier.** Its blocks held whole, every entry in its exact shape, every source on one of seven known hosts and
  paths, every destination tag unique, its gate's and tamper check's lines as written, both proofs' condition and the
  copy job's outputs, and every other line that names an image or a pull one the rule knows. A target or a source set
  in a step's env or by a script's assignment, `continue-on-error`, `shell`, `working-directory` or a step's `if` is
  refused.
- **Its behaviour.** The copy step's and the proof's scripts, taken from the workflow's text, run under bash with stub
  `skopeo`, `curl` and `git`, one case for each kind of red and green.
- **The stack.** One constant, `STACK_MODE`, names the mirror or upstream, apart from the lanes' `LANE_IMAGE`. On the
  mirror every image line is `ghcr.io/needless2say/<name>@sha256:<digest>`, ECR Public, Mailpit's publisher and any
  other namespace refused. Each line's package and digest together are a pair the copier pins, so a line never names
  a digest the mirror lacks. Both modes are tested.

## 5. Changes, ordered

- **A new followed tag**, `node 26-alpine` one day. A pull request appends it to `FOLLOWED`, its merge copies it, then
  the Dockerfiles' pull requests name it.
- **A new service digest.** A pull request appends its `PINNED` entry and its `WATCH` line, its merge copies and proves
  it, then pull requests move the stacks.
- **A bad upstream image.** A hold, one pull request, in force once its own run's placement proof is green. Never
  rerun an old run to apply it, dispatch from `main`.
- **A failing mirror.** Each consumer's line back on an upstream that serves that day. For the shared stack, its four
  lines on their upstream references by the same digests and `STACK_MODE` set to `upstream`, in one pull request.

## 6. Never delete a version

**No version of any package, tagged or untagged, is ever deleted.** Index platform and attestation manifests and a
followed tag's old indexes show as untagged versions, and a build, a stack or a rollback names them. GitHub restores a
deleted package within 30 days while its name is not reused, and a dispatch copies a pinned digest again while a
source serves it.

## 7. Reading a failure

- **The copier ends red.** Its last line names each kind. `refused`, Docker Hub did not name a followed tag, asks
  nothing, every tag still serving its last image. `stale-rerun`, a dispatch from `main`. `tamper`, a look at the
  digest the log recorded and at the package's access settings. `docs/reference/WORKFLOWS.md` has the full table.
- **`verify-images` fails on "cannot be read whole with no credentials".** A package is not public. Set it public on
  its page and dispatch the copier.
- **A consumer fails on its pull from `ghcr.io`.** A stale local sign in to `ghcr.io` sends its credential for a
  public package too, so `docker logout ghcr.io` there. On a runner, read the error, and the owner decides between a
  fix and that consumer's line back on its upstream.

## 8. Files

| File | Role |
| --- | --- |
| `.github/workflows/mirror-ci-images.yml` | The copier, `copy`, `verify` and `verify-images` |
| `e2e/docker-compose.shared.yml` | The shared E2E stack, on the mirror |
| `scripts/tests/copier_rule.py` | The copier's rule |
| `scripts/tests/test_workflow_service_images.py` | Every workflow's rule, the lanes and the stack's mode |
| `scripts/tests/test_mirror_ci_images.py` | The cases the rule refuses, the stack's pairs and the scripts under stubs |
| `docs/reference/WORKFLOWS.md` | The section "CI's image mirror", each kind of red and every order |
