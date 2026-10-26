# The local code scan's image (D-088, design 5.1), built by .github/workflows/publish-scan-image.yml on main and by
# `make scan-image` from a branch, its context scripts/common and its allowlist Dockerfile.dockerignore beside this file,
# so nothing else of cicd can enter a layer.
#
# The fetch stage alone has the network. It runs fetch.py, which reads every pin from the wrapper, refuses an empty
# one, downloads cosign, Opengrep's Linux asset and zizmor's Linux wheel by their pinned addresses, checks each by its
# SHA-256, verifies Opengrep's signature against OPENGREP_IDENTITY exactly, and takes zizmor's program out of its
# wheel. The last stage takes the two programs and the wrapper's own files, git from the base's Debian at a pinned
# snapshot, and a user that is not root, and runs the wrapper as its entrypoint with -I, -S and -B. Semgrep's rules
# never enter it, which the build's layer inspection holds. No syntax line, so BuildKit's own frontend reads this file
# and nothing is fetched from Docker Hub (D-065).

# python 3.14.9-slim as cicd's mirror keeps it, the digest its 3.14-slim held on 2026-10-26 (D-077)
FROM ghcr.io/needless2say/python@sha256:35caba83af2fe6da9a5d922f9b0156f21d1246a48278c58a08bd253303ba42e8 AS fetch

COPY kdf_scan.py scan_build/fetch.py /build/
RUN python3 -I -S -B /build/fetch.py /build/out

FROM ghcr.io/needless2say/python@sha256:35caba83af2fe6da9a5d922f9b0156f21d1246a48278c58a08bd253303ba42e8

# git from the base's Debian release at a dated snapshot, so a rebuild gets the same packages, its version printed
ARG DEBIAN_SNAPSHOT=20261022T000000Z
RUN . /etc/os-release \
    && rm -f /etc/apt/sources.list.d/debian.sources \
    && echo "deb [check-valid-until=no] http://snapshot.debian.org/archive/debian/${DEBIAN_SNAPSHOT}/ ${VERSION_CODENAME} main" \
       > /etc/apt/sources.list \
    && apt-get update \
    && apt-get install --yes --no-install-recommends git \
    && rm -rf /var/lib/apt/lists/* \
    && echo "Debian $VERSION_ID $VERSION_CODENAME, snapshot ${DEBIAN_SNAPSHOT}" && git --version

# the two programs, root's and read only to the scan's user, and the wrapper's own files beside it
COPY --from=fetch /build/out/opengrep /build/out/zizmor /opt/kdf-scan/bin/
COPY kdf_scan.py ci_paths.py kdf_zizmor.yml /opt/kdf-scan/
COPY scan_rules/ /opt/kdf-scan/scan_rules/

# the cicd commit the image is built from, which the wrapper names in every last line, and the run folder the
# container's tmpfs replaces at run time
ARG KDF_SCAN_COMMIT=local
LABEL org.opencontainers.image.revision="${KDF_SCAN_COMMIT}" \
      org.opencontainers.image.source="https://github.com/Needless2Say/kriegerdataforge-cicd" \
      org.opencontainers.image.description="The KDF local code scan, Opengrep and zizmor, cicd D-085"
RUN echo "${KDF_SCAN_COMMIT}" > /opt/kdf-scan/COMMIT \
    && useradd --uid 65532 --no-create-home --home-dir /nonexistent --shell /usr/sbin/nologin kdfscan \
    && mkdir -p /run/kdf-scan \
    && chmod -R a+rX,go-w /opt/kdf-scan \
    && /opt/kdf-scan/bin/zizmor --version

# whether Opengrep's Linux build unpacks a runtime at run time, and where, measured as the scan's user with a home of
# its own, its answer printed for OPENGREP_UNPACKS, the probe of Round Table 66's L8
RUN probe="$(mktemp -d)" \
    && chown 65532:65532 "$probe" \
    && su -s /bin/sh kdfscan -c "HOME=$probe XDG_CACHE_HOME=$probe/.cache /opt/kdf-scan/bin/opengrep --version" \
    && echo "opengrep unpacked under its home:" && (cd "$probe" && find . -maxdepth 3 | head -20) \
    && rm -rf "$probe"

USER 65532:65532
WORKDIR /run/kdf-scan
ENTRYPOINT ["python3", "-I", "-S", "-B", "/opt/kdf-scan/kdf_scan.py"]
