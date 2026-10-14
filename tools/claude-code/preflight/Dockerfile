# The Linux pre-flight's image (D-072), built by kdf-preflight.sh alone and never pushed to a registry.
#
# The base stage holds CI's tools. Python 3.14.7 slim from AWS ECR Public's gallery of Docker's official images by its
# index digest (D-064), Node from its official tarball checked against its sum, and actionlint at the version and
# sha256 that ci.yml pins. git, make and ShellCheck come unpinned from the digest's own Debian release, since its
# mirror keeps only the current package. The wrapper builds this stage first and alone, by --target base, so a failure
# here is the tool's, and tags it kdf-preflight-base:<this file's hash>.
#
# The lanes stage takes the commit's tar and the lane script, the context's only other files, as root's, unpacks the
# tar as runner, an unprivileged user as on GitHub's runner, and makes it a repo of one commit. The run id is used in
# the step that runs the lanes, so that step is never taken from the cache. The last step prints each lane's status
# after a marker that holds the run id and the end marker, small enough that BuildKit never clips them, and only then,
# on stderr and within a byte budget, an excerpt of each failed lane's own output, since BuildKit drops the rest of a
# step's stdout once it clips a noisy lane. No syntax line, so BuildKit's own frontend reads this file and nothing is
# fetched from Docker Hub (D-065).

# python 3.14.7-slim, the index digest the tag held on 2026-10-14
FROM public.ecr.aws/docker/library/python@sha256:51dafde81dbdb6ebde285137a295cf18a47ca95234fe388a343719cb97305b3d \
    AS base

# ShellCheck too, since actionlint runs it over every run: script when it is on the PATH, as on GitHub's runner, and
# skips that check without a word when it is not. Debian 13's is 0.10.0 where the runner's is 0.9.0 (D-072).
# Its version is printed, so a base without it fails here
RUN apt-get update \
    && apt-get install --yes --no-install-recommends git make shellcheck \
    && rm -rf /var/lib/apt/lists/* \
    && . /etc/os-release && echo "Debian $VERSION_ID $VERSION_CODENAME" && git --version && make --version | head -1 \
    && shellcheck --version

# Node 22, the major ubuntu-latest runs by default, "Node.js 22.23.3" in actions/runner-images'
# images/ubuntu/Ubuntu2404-Readme.md for image 20261004.327.1, read on 2026-10-14. Its sum is the line nodejs.org's
# SHASUMS256.txt for v22.23.3 gives node-v22.23.3-linux-x64.tar.gz
ADD --checksum=sha256:1084aa36196bba4c3a5e69a1ee388a6e4ff729dad09445fbcd434b28fe3c24af \
    https://nodejs.org/dist/v22.23.3/node-v22.23.3-linux-x64.tar.gz /tmp/node.tar.gz
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
RUN id -u \
    && mkdir work \
    && tar -xf /opt/kdf/repo.tar -C work \
    && git -C work init -q -b main \
    && git -C work add -A \
    && git -C work -c user.name=kdf-preflight -c user.email=kdf-preflight@localhost commit -q -m preflight

ARG RUN_ID
ARG LANE_TIMEOUT
ARG LANES
RUN echo "kdf-preflight run $RUN_ID" && bash /opt/kdf/lanes.sh work out/results "$LANE_TIMEOUT" $LANES
RUN sed "s/^/KDF-PREFLIGHT-RESULT $RUN_ID /" out/results && echo "KDF-PREFLIGHT-END $RUN_ID" \
    && bash /opt/kdf/lanes.sh --tails out/results "$RUN_ID"
