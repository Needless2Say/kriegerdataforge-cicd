# The Linux pre-flight's image (D-072), built by kdf-preflight.sh alone and never pushed to a registry.
#
# The base stage holds CI's tools. Python 3.14.7 slim from AWS ECR Public's gallery of Docker's official images by its
# index digest (D-064), Node from its official tarball checked against its sum, at the major every Node lane of cicd's
# installs by default (D-087), and actionlint at the version and sha256 that ci.yml pins. git, make, ShellCheck and
# curl come unpinned from the digest's own Debian release, since its mirror keeps only the current package. The wrapper
# builds this stage first and alone, by --target base, so a failure here is the tool's, and tags it
# kdf-preflight-base:<this file's hash>.
#
# The lanes stage takes the commit's tar and the lane script as root's, and the owner's private mirrors the wrapper
# fetched and the private npm packages it served as runner's, the context's only other files. It unpacks the tar as
# runner, an unprivileged user as on GitHub's runner, and makes it a repo of one commit. The run id and the setup
# target are used in the step that runs setup and the lanes, so that step is never taken from the cache (D-078). The
# last step prints each lane's status after a marker that holds the run id, then setup's status from a file of its own
# when setup ran, then the end marker, small enough that BuildKit never clips them, and only then, on stderr and within
# a byte budget, an excerpt of a red setup's and of each failed lane's own output, since BuildKit drops the rest of a
# step's stdout once it clips a noisy lane. No syntax line, so BuildKit's own frontend reads this file and nothing is
# fetched from Docker Hub (D-065).

# python 3.14.7-slim, the index digest the tag held on 2026-10-14
FROM public.ecr.aws/docker/library/python@sha256:51dafde81dbdb6ebde285137a295cf18a47ca95234fe388a343719cb97305b3d \
    AS base

# ShellCheck too, since actionlint runs it over every run: script when it is on the PATH, as on GitHub's runner, and
# skips that check without a word when it is not. Debian 13's is 0.10.0 where the runner's is 0.9.0 (D-072).
# curl as on GitHub's runner, since the local code scan's install tests fetch with it and skip without it (D-085).
# Each version is printed, so a base without one fails here
RUN apt-get update \
    && apt-get install --yes --no-install-recommends git make shellcheck curl \
    && rm -rf /var/lib/apt/lists/* \
    && . /etc/os-release && echo "Debian $VERSION_ID $VERSION_CODENAME" && git --version && make --version | head -1 \
    && shellcheck --version && curl --version | head -1

# Node 24, the major every Node lane of cicd's installs by its node_version input's default, "24" in each workflow of
# .github/workflows that takes one, which a test holds equal, since no such lane runs the runner's own Node (D-087).
# The newest 24 release on nodejs.org on 2026-10-25, its sum the line nodejs.org's SHASUMS256.txt for v24.22.1 gives
# node-v24.22.1-linux-x64.tar.gz
ADD --checksum=sha256:eb6728e77c576a35162c122c45ccadf224d89ff00abc8dae46cc2897c6002d7c \
    https://nodejs.org/dist/v24.22.1/node-v24.22.1-linux-x64.tar.gz /tmp/node.tar.gz
RUN tar -xzf /tmp/node.tar.gz -C /usr/local --strip-components=1 --no-same-owner \
    && rm /tmp/node.tar.gz \
    && node --version

# actionlint at ci.yml's ACTIONLINT_VERSION and ACTIONLINT_SHA256, which a test holds equal
ADD --checksum=sha256:8aca8db96f1b94770f1b0d72b6dddcb1ebb8123cb3712530b08cc387b349a3d8 \
    https://github.com/rhysd/actionlint/releases/download/v1.7.12/actionlint_1.7.12_linux_amd64.tar.gz \
    /tmp/actionlint.tar.gz
RUN tar -xzf /tmp/actionlint.tar.gz -C /usr/local/bin --no-same-owner actionlint \
    && rm /tmp/actionlint.tar.gz \
    && actionlint -version

RUN useradd --create-home --uid 1001 --shell /bin/bash runner

FROM base AS lanes

ENV ENVIRONMENT=local GIT_TERMINAL_PROMPT=0
USER runner
WORKDIR /home/runner
# root's, so no lane can change the script the last step runs
COPY repo.tar lanes.sh /opt/kdf/
# the owner's private mirrors the wrapper fetched, an empty folder when it fetched none, by an instruction of their own
# so the folder's contents land in /home/runner/mirrors, runner's, and git's ownership check passes as on GitHub's
# runner (D-078)
COPY --chown=runner:runner mirrors /home/runner/mirrors/
# the owner's private npm packages the wrapper served, each tarball by its digest in npm's cache layout, an empty folder
# when it served none, by an instruction of their own so the folder's contents land in npm's own folder for runner,
# runner's, and setup's install reads each from the cache by its lock's integrity with no token and no request (D-087)
COPY --chown=runner:runner npm /home/runner/.npm/
RUN id -u \
    && mkdir work \
    && tar -xf /opt/kdf/repo.tar -C work \
    && git -C work init -q -b main \
    && git -C work add -A \
    && git -C work -c user.name=kdf-preflight -c user.email=kdf-preflight@localhost commit -q -m preflight

ARG RUN_ID
ARG LANE_TIMEOUT
ARG LANES
ARG SETUP
RUN echo "kdf-preflight run $RUN_ID" \
    && bash /opt/kdf/lanes.sh --setup "$SETUP" --mirrors /home/runner/mirrors work out/results "$LANE_TIMEOUT" $LANES
RUN sed "s/^/KDF-PREFLIGHT-RESULT $RUN_ID /" out/results \
    && if [ -e out/setup ]; then sed "s/^/KDF-PREFLIGHT-SETUP $RUN_ID /" out/setup; fi \
    && echo "KDF-PREFLIGHT-END $RUN_ID" \
    && bash /opt/kdf/lanes.sh --tails out/results "$RUN_ID"
