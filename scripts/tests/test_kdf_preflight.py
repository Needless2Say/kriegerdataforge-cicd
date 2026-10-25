"""
Tests for kdf-preflight.sh (D-072), the one way a session runs a Linux pre-flight of a repo's lanes, and its image.

The image's tests read `tools/claude-code/preflight/Dockerfile` as text and hold its pins, the run id in the step that
runs the lanes, the lane stage's fixed environment and a last stage that is not root, and ask git whether
`.gitattributes` gives the Dockerfile and the lane script LF.

The wrapper's tests run it as it ships against a throwaway repo, with a stand in for docker named by `KDF_DOCKER_BIN`
that records every call, lists the build's context and plays a build's log, the marker lines of a clean or a red run,
none, some, forged ones, a broken base or a hang. Docker's configuration is read from a home of the test's own. The
tests need bash, git and node, which GitHub's runners and the image have, and a machine without them skips them.
"""

from __future__ import annotations

import base64
import hashlib
import io
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import tarfile
import time
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

import fetch_private_packages as fpp
import pytest

ROOT       = Path(__file__).resolve().parents[2]
TOOLS      = ROOT / "tools" / "claude-code"
TOOL       = TOOLS / "kdf-preflight.sh"
GUARD      = TOOLS / "kdf-guard.js"
PREFLIGHT  = TOOLS / "preflight"
DOCKERFILE = PREFLIGHT / "Dockerfile"
LANES      = PREFLIGHT / "lanes.sh"
WORKFLOWS  = ROOT / ".github" / "workflows"
CI_YML     = WORKFLOWS / "ci.yml"
GIT        = shutil.which("git")
NODE       = shutil.which("node")
BASH       = os.environ.get("KDF_TEST_BASH") or shutil.which("bash")

DIGEST = re.compile(r"^[a-z0-9.-]+(/[a-z0-9._-]+)+@sha256:[0-9a-f]{64}$")

# the variables that point docker or buildx at another machine or another configuration, each refused
DOCKER_ENV = ("DOCKER_HOST", "DOCKER_CONTEXT", "DOCKER_CONFIG", "BUILDX_BUILDER", "BUILDX_CONFIG")

# the rig repo's Makefile, lanes a session may run and lanes it may not
MAKEFILE = (
    ".PHONY: ci-lint ci-unit-tests\n"
    "CI_VAR := ci-hidden\n"
    "ci-lint: ## lint\n\t@echo lint\n"
    "ci-unit-tests:\n\t@echo tests\n"
    "ci-version-check:\n\t@echo version\n"
    "ci-deploy-prod:\n\t@echo deploy\n"
    "ci-release-notes:\n\t@echo release\n"
    "ci-publish-docs:\n\t@echo publish\n"
    "ci-dev-check:\n\t@echo dev\n"
    "ci-dev-local-check:\n\t@echo local\n"
    "ci-x := not a target\n"
)

# the owner's repos the mirror tests pin, and the repo under test, a private one of the owner's by its origin
FMT        = "kriegerdataforge-fmt"
SDK        = "kriegerdataforge-sdk"
UNDER_TEST = "kriegerdataforge-product"
FMT_PIN    = {"requirements-dev.in": f"kdf-fmt @ git+https://github.com/Needless2Say/{FMT}.git@main\n"}

# the registry GitHub serves npm packages from, and a private npm package of the owner's scope the npm tests lock
# (D-087)
NPM_HOST = "https://npm.pkg.github.com/"
WIDGET   = "@needless2say/widget"

# a tarball member whose top folder GNU tar would read as an option that runs a command, and the file it would make
DASH_MARKER = "kdf-preflight-dash-probe"
DASH_MEMBER = f"--checkpoint-action=exec=touch${{IFS}}{DASH_MARKER};#/package.json"

# the line a missing tarball's refusal ends with, the fresh install that puts it in npm's cache (Round Table 64's L2)
FRESH_INSTALL = (
    "install the repo into a fresh tree on this machine, one with no node_modules, such as a new worktree's make"
    " setup, which puts the tarball in npm's cache, then run again"
)

# the rig's Makefile with a setup target and another a session may name
SETUP_MAKEFILE = MAKEFILE + "setup:\n\t@echo setup\ninstall:\n\t@echo install\n"

# a pin in each of the seven files CI's fetch plan reads, in the spellings pip takes
PIN_FILES = {
    "requirements.txt": "kdf-fmt @ {pin}\n",
    "requirements.in": "kdf-fmt @ {pin}\n",
    "requirements-dev.txt": "kdf-fmt @ {pin} \\\n    --hash=sha256:00\n",
    "requirements-dev.in": "pytest==9.1.1\nkdf-fmt @ {pin}  # the house style\n",
    "requirements-test.txt": "kdf-fmt@{pin}\n",
    "requirements-test.in": "kdf-fmt @ {pin}#egg=kdf-fmt\n",
    "pyproject.toml": '[project]\ndependencies = [\n    "kdf-fmt @ {pin}",\n]\n',
}

# fetch scripts whose allowlist cannot be read, none at all, another form, a value not quoted and an empty block
BROKEN_ALLOWLISTS = [
    None,
    "ALLOWLIST = dict(kriegerdataforge_fmt = 'private')\n",
    'ALLOWLIST: dict[str, str] = {\n    "kriegerdataforge-fmt": private,\n}\n',
    "ALLOWLIST: dict[str, str] = {\n}\n",
]

# lines CI's PIN reads, and the wrapper's pattern must read alike
PIN_SAMPLES = [
    "kdf-fmt @ git+https://github.com/Needless2Say/kriegerdataforge-fmt.git@main",
    "x @ git+https://github.com/Needless2Say/kriegerdataforge-sdk.git@v0.14.0#egg=x",
    "x @ git+https://github.com/Needless2Say/kriegerdataforge-sdk.git@" + "a" * 40 + " ; python_version > '3'",
    '"kdf @ git+https://github.com/Needless2Say/kriegerdataforge-reports-sdk.git@v1.2.3",',
    "[git+https://github.com/Needless2Say/a.b.git@x.y]",
    "x@git+https://github.com/Needless2Say/kriegerdataforge.git@main,y",
    "'git+https://github.com/Needless2Say/fitness-app-backend.git@v1'",
    "git+https://github.com/needless2say/kriegerdataforge-fmt.git@main",
    "git+ssh://git@github.com/Needless2Say/kriegerdataforge-fmt.git@main",
    "https://github.com/Needless2Say/kriegerdataforge-fmt",
    "two git+https://github.com/Needless2Say/a.git@1 git+https://github.com/Needless2Say/b.git@2",
]

# a stand in for docker, it records each call, lists a build's context, copies the tar, the mirrors and the npm folder
# it was handed, and plays a build's log as FAKE_MODE says, setup's status as FAKE_SETUP says, a red setup skipping
# each make lane
FAKE = r"""#!/usr/bin/env bash
export LC_ALL=C
echo "call $*" >> "$FAKE_LOG"
case "$1" in
    rmi) [ "${FAKE_RMI:-ok}" = ok ]; exit ;;
    images) [ -z "${FAKE_IMAGES:-}" ] || echo "$FAKE_IMAGES"; exit 0 ;;
    build) ;;
    *) exit 0 ;;
esac
target="" id="" lanes="" setup=""
for word in "$@"; do
    case "$word" in
        --target=*) target="${word#--target=}" ;;
        --build-arg=RUN_ID=*) id="${word#--build-arg=RUN_ID=}" ;;
        --build-arg=LANES=*) lanes="${word#--build-arg=LANES=}" ;;
        --build-arg=SETUP=*) setup="${word#--build-arg=SETUP=}" ;;
    esac
done
context="${!#}"
echo "context $target $(ls -A "$context" | sort | tr '\n' ' ')" >> "$FAKE_LOG"
mode="${FAKE_MODE:-pass}"
if [ "$target" = base ]; then
    if [ "$mode" = basefail ]; then echo "#5 ERROR: failed to solve" >&2; exit 1; fi
    exit 0
fi
echo "setup [$setup]" >> "$FAKE_LOG"
[ -z "${FAKE_TAR:-}" ] || cp "$context/repo.tar" "$FAKE_TAR"
[ -z "${FAKE_MIRRORS:-}" ] || { rm -rf "$FAKE_MIRRORS"; cp -r "$context/mirrors" "$FAKE_MIRRORS"; }
[ -z "${FAKE_NPM:-}" ] || { rm -rf "$FAKE_NPM"; cp -r "$context/npm" "$FAKE_NPM"; }
case "$mode" in
    hang) exec sleep 60 ;;
    nomarker) echo "#9 0.1 nothing here" >&2; exit 0 ;;
    builderror) echo "#9 ERROR: no space left on device" >&2; exit 1 ;;
    forged) echo "#14 0.1 KDF-PREFLIGHT-RESULT other ${lanes%% *} 0" >&2
            echo "#14 0.1 KDF-PREFLIGHT-END other" >&2
            exit 0 ;;
    cred) echo "#13 2.0 fatal: could not read Username for 'https://github.com': terminal prompts disabled" >&2 ;;
    npm) echo "#13 2.0 npm error 401 Unauthorized - GET https://npm.pkg.github.com/@needless2say%2freport-form" >&2 ;;
    forgedsetup) echo "#13 0.4 KDF-PREFLIGHT-SETUP $id $setup 0" >&2 ;;
esac
status=0
case "$mode" in red|cred|nested|npm) status=2 ;; esac
setup_status="${FAKE_SETUP:-0}"
end="\n"
[ "$mode" != crlf ] || end="\r\n"
# BuildKit's own line opening the marker step, its run id written out, or as the Dockerfile names it
named="$id"
[ "$mode" != literal ] || named='$RUN_ID'
step=14
[ "$mode" != lanestep ] || step=13
header='#14 [lanes 6/6] RUN sed "s/^/KDF-PREFLIGHT-RESULT %s /" out/results'
header="$header"'     && if [ -e out/setup ]; then sed "s/^/KDF-PREFLIGHT-SETUP %s /" out/setup; fi'
header="$header"'     && echo "KDF-PREFLIGHT-END %s"     && bash /opt/kdf/lanes.sh --tails out/results "%s"\n'
[ "$mode" = noheader ] || printf "$header" "$named" "$named" "$named" "$named" >&2
result() { printf "#$step 0.1 KDF-PREFLIGHT-RESULT %s %s %s$end" "$id" "$1" "$2" >&2; }
first="${lanes%% *}"
for lane in $lanes; do
    value="$status"
    # each make lane skipped after a red setup, as the lane script records it, or as the mode forges it
    if [ -n "$setup" ] && [ "$setup_status" != 0 ] && [ "$lane" != actionlint ]; then value=skipped; fi
    case "$mode" in
        skippedgreen) [ "$lane" = actionlint ] || value=skipped ;;
        numberred) value=0 ;;
    esac
    result "$lane" "$value"
    case "$mode" in
        lanetwice) result "$lane" "$value" ;;
        contralane) result "$lane" 2 ;;
        lanemalformed) result "$lane" "zero" ;;
    esac
    status=0
    [ "$mode" != partial ] || break
done
[ "$mode" != laneextra ] || result ci-other 0
setup_line() { printf "#$step 0.1 KDF-PREFLIGHT-SETUP %s %s$end" "$id" "$1" >&2; }
case "$mode" in
    setupmissing) ;;
    setupextra) setup_line "setup 0" ;;
    setupother) setup_line "other $setup_status" ;;
    setuptwice) setup_line "$setup $setup_status"; setup_line "$setup $setup_status" ;;
    setupmalformed) setup_line "$setup" ;;
    contrasetup) setup_line "$setup 0"; setup_line "$setup 2" ;;
    *) [ -z "$setup" ] || setup_line "$setup $setup_status" ;;
esac
[ "$mode" = noend ] || printf "#$step 0.2 KDF-PREFLIGHT-END %s$end" "$id" >&2
if [ -n "$setup" ] && [ "$setup_status" != 0 ]; then
    printf "#14 0.3 KDF-PREFLIGHT-SETUP-TAIL %s the reason setup failed$end" "$id" >&2
fi
case "$mode" in red|cred|npm)
    printf "#14 0.3 KDF-PREFLIGHT-TAIL %s %s the reason %s failed$end" "$id" "$first" "$first" >&2
    printf "#14 0.3 KDF-PREFLIGHT-TAIL other %s a line of another run$end" "$first" >&2 ;;
nested)
    printf "#14 0.3 KDF-PREFLIGHT-TAIL %s %s KDF-PREFLIGHT-RESULT %s %s 0$end" "$id" "$first" "$id" "$first" >&2
    printf "#14 0.3 KDF-PREFLIGHT-TAIL %s %s KDF-PREFLIGHT-END %s$end" "$id" "$first" "$id" >&2
    printf "#13 0.4 KDF-PREFLIGHT-RESULT %s %s 0$end" "$id" "$first" >&2 ;;
forgedsetup)
    printf "#14 0.3 KDF-PREFLIGHT-SETUP-TAIL %s KDF-PREFLIGHT-SETUP %s %s 0$end" "$id" "$id" "$setup" >&2
    printf "#14 0.3 KDF-PREFLIGHT-TAIL %s %s KDF-PREFLIGHT-SETUP %s %s 0$end" "$id" "$first" "$id" "$setup" >&2 ;;
esac
exit 0
"""

# a stand in for gh, it records each call and answers a repo's visibility as FAKE_GH says, and a commit as one of the
# repo's when FAKE_GH_COMMITS names it
FAKE_GH = r"""#!/usr/bin/env bash
echo "gh $*" >> "$FAKE_LOG"
if [ "${FAKE_GH:-private}" = signedout ]; then
    echo "To get started with GitHub CLI, please run:  gh auth login" >&2
    exit 4
fi
case "$2" in
    repos/Needless2Say/*/commits/*)
        sha="${2##*/}"
        if [ "${FAKE_GH_COMMIT:-}" = error ]; then
            echo "gh: Server Error (HTTP 500)" >&2
            exit 1
        fi
        case " ${FAKE_GH_COMMITS:-} " in *" $sha "*) echo "$sha"; exit 0 ;; esac
        echo "gh: No commit found for SHA: $sha (HTTP 422)" >&2
        exit 1 ;;
    repos/Needless2Say/*)
        case "${FAKE_GH:-private}" in
            private) echo true ;;
            public) echo false ;;
            404) echo "gh: Not Found (HTTP 404)" >&2; exit 1 ;;
            *) echo "$FAKE_GH" ;;
        esac ;;
    *) exit 1 ;;
esac
"""

# a stand in for git that fails every fetch with an error naming a URL that carries a user part, and runs the real
# git for anything else
FAKE_GIT = r"""#!/usr/bin/env bash
for word in "$@"; do
    if [ "$word" = fetch ]; then
        echo "fatal: unable to access 'https://kdf-user:s3cr3t-value@github.com/Needless2Say/x.git/': error 403" >&2
        exit 128
    fi
done
exec "$REAL_GIT" "$@"
"""

# a stand in for git that records each call and runs the real git
LOGGING_GIT = r"""#!/usr/bin/env bash
echo "git $*" >> "$KDF_TEST_GIT_LOG"
exec "$REAL_GIT" "$@"
"""

# a stand in for git that puts a stray file in the run's context npm folder as it fetches a mirror, which the npm
# packages were placed in before, and runs the real git
STRAY_GIT = r"""#!/usr/bin/env bash
dir="" fetch=0
for word in "$@"; do
    case "$word" in
        --git-dir=*) dir="${word#--git-dir=}" ;;
        fetch) fetch=1 ;;
    esac
done
case "$fetch:$dir" in 1:*/mirrors/*) echo stray > "${dir%/mirrors/*}/context/npm/stray.txt" ;; esac
exec "$REAL_GIT" "$@"
"""

# a stand in for npm first on every run's PATH, since the tool runs no npm on the host, so a call is recorded and fails
# the test (D-087)
NPM_STUB = r"""#!/usr/bin/env bash
echo "npm $*" >> "$FAKE_LOG"
exit 97
"""

# a stand in for cygpath, which Linux lacks, that records each call and answers -u with the path's slashes turned
CYGPATH_STUB = r"""#!/usr/bin/env bash
echo "cygpath $*" >> "$FAKE_LOG"
[ "$1" = -u ] || exit 1
printf '%s\n' "${2//\\//}"
"""


def _instructions(text: str) -> list[tuple[str, str]]:
    """
    The Dockerfile's instructions in order, each its keyword and its arguments, a continued line joined to the next and
    every comment left out.
    """
    found: list[tuple[str, str]] = []
    pending = ""
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if stripped.endswith("\\"):
            pending += stripped[:-1].strip() + " "
            continue
        whole   = pending + stripped
        pending = ""
        keyword, _, rest = whole.partition(" ")
        found.append((keyword.upper(), rest.strip()))
    assert not pending, "the Dockerfile ends in a continued line"
    return found


def _stages() -> list[list[tuple[str, str]]]:
    """
    The Dockerfile's stages, each its instructions from its FROM on.
    """
    stages: list[list[tuple[str, str]]] = []
    for keyword, rest in _instructions(DOCKERFILE.read_text(encoding = "utf-8")):
        if keyword == "FROM":
            stages.append([])
        assert stages, "an instruction before the first FROM"
        stages[-1].append((keyword, rest))
    return stages


def _ci_actionlint() -> tuple[str, str]:
    text    = CI_YML.read_text(encoding = "utf-8")
    version = re.search(r'ACTIONLINT_VERSION:\s*"([^"]+)"', text)
    sha256  = re.search(r'ACTIONLINT_SHA256:\s*"([0-9a-f]{64})"', text)
    assert version and sha256, "ci.yml pins actionlint's version and sha256"
    return version.group(1), sha256.group(1)

# ======================================================================================================================
# the image
# ======================================================================================================================

def test_every_from_names_a_digest_or_an_earlier_stage() -> None:
    named: set[str] = set()
    for stage in _stages():
        words = stage[0][1].split()
        assert words[0] in named or DIGEST.match(words[0]), f"FROM {words[0]} names no digest"
        if len(words) == 3 and words[1].upper() == "AS":
            named.add(words[2])
    first = _stages()[0][0][1].split()[0]
    assert first.startswith("public.ecr.aws/docker/library/python@sha256:"), "Python from ECR Public (D-064)"


def test_the_base_is_python_3_14_7_slim_by_the_digest_its_comment_names() -> None:
    text = DOCKERFILE.read_text(encoding = "utf-8")
    assert re.search(r"^# python 3\.14\.7-slim, the index digest the tag held on \d{4}-\d{2}-\d{2}$", text, re.M)


def test_actionlint_is_the_version_and_sha256_ci_yml_pins() -> None:
    version, sha256 = _ci_actionlint()
    url  = f"https://github.com/rhysd/actionlint/releases/download/v{version}/actionlint_{version}_linux_amd64.tar.gz"
    adds = [rest for keyword, rest in _stages()[0] if keyword == "ADD" and "rhysd/actionlint" in rest]
    assert len(adds) == 1, "one ADD of actionlint in the base stage"
    assert f"--checksum=sha256:{sha256}" in adds[0].split() and url in adds[0].split()


def _node_version_defaults() -> dict[str, str]:
    """
    The default of the node_version input of every workflow in .github/workflows that takes one, by its file name.
    """
    found: dict[str, str] = {}
    for path in sorted(WORKFLOWS.glob("*.y*ml")):
        text  = path.read_text(encoding = "utf-8")
        block = re.search(r"^( +)node_version:\n((?:\1 +.*\n)+)", text, re.M)
        if block:
            default = re.search(r'^ +default: "?([^"\s]+)"?$', block.group(2), re.M)
            assert default, f"{path.name} takes node_version with no default"
            found[path.name] = default.group(1)
    return found


def test_node_is_the_major_every_node_lane_defaults_to_from_its_tarball_checked_against_its_sum() -> None:
    adds = [rest for keyword, rest in _stages()[0] if keyword == "ADD" and "nodejs.org" in rest]
    assert len(adds) == 1, "one ADD of Node in the base stage"
    url = re.search(r"https://nodejs\.org/dist/v(\d+)\.(\d+)\.(\d+)/node-v\1\.\2\.\3-linux-x64\.tar\.gz", adds[0])
    assert url, "Node's own tarball, its version named twice alike"
    assert re.search(r"(^| )--checksum=sha256:[0-9a-f]{64}( |$)", adds[0]), "checked against its SHASUMS256.txt line"
    # the major every Node lane installs by its node_version default, six workflows on 2026-10-25, since none runs the
    # runner's own Node, so a change of either alone fails here (D-087)
    defaults = _node_version_defaults()
    assert defaults, "no workflow in .github/workflows takes node_version, so the image's Node has no source"
    assert set(defaults.values()) == {url.group(1)}, defaults
    # the comment names the major and its source, so a change of the default is a one line fix here
    text = DOCKERFILE.read_text(encoding = "utf-8")
    assert re.search(
        rf"^# Node {url.group(1)}, the major every Node lane of cicd's installs by its node_version",
        text,
        re.M,
    )
    assert "SHASUMS256.txt" in text


def test_the_base_stage_makes_an_unprivileged_runner_and_the_last_stage_runs_as_it() -> None:
    base, *_, last = _stages()
    assert any(keyword == "RUN" and "useradd" in rest and "--uid 1001" in rest and rest.rstrip().endswith("runner")
               for keyword, rest in base), "a user runner, uid 1001, as GitHub's runner"
    users = [rest.split()[0] for keyword, rest in last if keyword == "USER"]
    assert users and users[-1] not in ("root", "0") and not {"root", "0"} & set(users)
    lanes      = next(index for index, (keyword, rest) in enumerate(last) if keyword == "RUN" and "lanes.sh" in rest)
    first_user = next(index for index, (keyword, _) in enumerate(last) if keyword == "USER")
    assert first_user < lanes, "the lanes run as runner"


def test_the_run_id_is_used_in_the_step_that_runs_the_lanes_and_in_the_marker_step() -> None:
    last = _stages()[-1]
    args = [rest.split("=")[0] for keyword, rest in last if keyword == "ARG"]
    assert "RUN_ID" in args, "the run id is a build argument of the last stage"
    runs   = [rest for keyword, rest in last if keyword == "RUN"]
    lanes  = [rest for rest in runs if "lanes.sh" in rest and "--tails" not in rest]
    marker = [rest for rest in runs if "KDF-PREFLIGHT-RESULT" in rest]
    used   = re.compile(r"\$\{?RUN_ID\b")
    assert len(lanes) == 1 and used.search(lanes[0]), "so the step that runs the lanes is never taken from the cache"
    assert len(marker) == 1 and used.search(marker[0]) and "KDF-PREFLIGHT-END" in marker[0]
    assert runs[-1] == marker[0], "the marker step is the last"
    assert runs.index(lanes[0]) < runs.index(marker[0])
    # the results, setup's line and the end marker first, and only then an excerpt, so a clipped excerpt never takes a
    # result (D-072, D-078)
    words = ("KDF-PREFLIGHT-RESULT", "KDF-PREFLIGHT-SETUP", "KDF-PREFLIGHT-END", "lanes.sh --tails")
    order = [marker[0].find(word) for word in words]
    assert -1 not in order and order == sorted(order) and used.search(marker[0][order[3]:])


def test_setup_is_an_argument_of_the_lanes_step_and_its_line_comes_from_a_file_of_its_own() -> None:
    # the target is used in the step that runs the lanes, which is never taken from the cache, and setup's status is
    # printed from its own file, never by the sed that prints the lanes' results (D-078)
    last = _stages()[-1]
    args = [rest.split("=")[0] for keyword, rest in last if keyword == "ARG"]
    assert "SETUP" in args, "the target is a build argument of the last stage"
    runs  = [rest for keyword, rest in last if keyword == "RUN"]
    lanes = next(rest for rest in runs if "lanes.sh" in rest and "--tails" not in rest)
    assert re.search(r'lanes\.sh --setup "\$SETUP" --mirrors /home/runner/mirrors work out/results ', lanes), lanes
    marker = runs[-1]
    assert re.search(r'sed "s/\^/KDF-PREFLIGHT-RESULT \$RUN_ID /" out/results ', marker)
    assert re.search(r'sed "s/\^/KDF-PREFLIGHT-SETUP \$RUN_ID /" out/setup\b', marker), marker
    assert marker.count("out/results") == 2, "the results file read by the sed for results and by --tails alone"


def test_the_lane_stage_fixes_its_environment_and_takes_the_three_files_the_mirrors_and_npm_alone() -> None:
    last = _stages()[-1]
    env  = " ".join(rest for keyword, rest in last if keyword == "ENV").split()
    assert "ENVIRONMENT=local" in env and "GIT_TERMINAL_PROMPT=0" in env
    copies = [rest.split() for keyword, rest in last if keyword in ("COPY", "ADD")]
    assert len(copies) == 3, "three COPYs into the lane stage, root's, the mirrors' and npm's"
    root    = next(words for words in copies if "/opt/kdf/" in words)
    sources = [word for word in root if not word.startswith("--")][:-1]
    assert sorted(sources) == ["lanes.sh", "repo.tar"] and root[-1] == "/opt/kdf/"
    # root's, so no lane can change the script the last step runs (D-072)
    assert not [word for word in root if word.startswith("--chown")]
    # the mirrors by an instruction of their own, the folder named alone so it lands as itself, runner's, so git's
    # ownership check passes as on GitHub's runner (D-078)
    mirrors = next(words for words in copies if "mirrors" in words)
    assert mirrors == ["--chown=runner:runner", "mirrors", "/home/runner/mirrors/"], mirrors
    # the npm packages served by an instruction of their own, the folder named alone so its contents land in npm's own
    # folder for runner, whose parent useradd made, so npm reads each tarball from its cache by digest (D-087)
    npm = next(words for words in copies if "npm" in words)
    assert npm == ["--chown=runner:runner", "npm", "/home/runner/.npm/"], npm
    lanes = [index for index, (keyword, rest) in enumerate(last) if keyword == "RUN" and "--setup" in rest]
    for source in ("mirrors", "npm"):
        order = [index for index, (keyword, rest) in enumerate(last) if keyword == "COPY" and source in rest.split()]
        assert order and lanes and order[0] < lanes[0], f"the {source} folder is in place before setup runs"


def test_the_lane_stage_unpacks_the_tar_and_makes_a_repo_of_one_commit() -> None:
    runs  = [rest for keyword, rest in _stages()[-1] if keyword == "RUN"]
    setup = next(rest for rest in runs if "repo.tar" in rest)
    order = [setup.find(words) for words in ("id -u", "tar -xf", "init -q", "add -A", "commit -q")]
    assert -1 not in order and order == sorted(order), "id -u, unpack, init, add, then commit, as runner"


@pytest.mark.skipif(GIT is None, reason = "git reads the attributes")
def test_gitattributes_gives_the_dockerfile_and_the_lane_script_lf() -> None:
    paths = ("tools/claude-code/preflight/Dockerfile", "tools/claude-code/preflight/lanes.sh")
    done  = subprocess.run(
        [str(GIT), "-C", str(ROOT), "check-attr", "eol", "--", *paths],
        check = True,
        capture_output = True,
        text = True,
    )
    lines = done.stdout.strip().splitlines()
    assert len(lines) == 2 and all(line.endswith(": eol: lf") for line in lines), done.stdout


def test_the_lane_script_records_each_lane_under_timeout_and_exits_0() -> None:
    text = LANES.read_text(encoding = "utf-8")
    assert text.startswith("#!/usr/bin/env bash\n")
    assert re.search(r"timeout\b[^\n]*\bmake\b", text) and re.search(r"timeout\b[^\n]*\bactionlint\b", text)
    assert text.rstrip().endswith("exit 0"), "a red lane never stops the ones after it"
    assert "set -e" not in text


def test_the_lane_script_records_every_lanes_status_in_order_from_its_work_folder(tmp_path: Path) -> None:
    # step 3's first real run found the results file named from where the script started and written after it changed
    # folder, so no lane's status was recorded, which a reading of the text alone missed
    make = shutil.which("make")
    if (BASH is None or make is None) and not os.environ.get("CI"):
        pytest.skip("the lane script needs bash and make")
    work = tmp_path / "work"
    work.mkdir()
    # ci-env is green only when the base image's own PYTHON_VERSION and PYTHON_SHA256 are gone, which a runner never
    # sets, and which cicd's Makefile, PYTHON_VERSION ?= 3.14, took as python3.14.7 in step 3's cicd run
    makefile = "ci-red:\n\t@exit 2\nci-green:\n\t@echo green\nci-hang:\n\t@sleep 30\n"
    makefile += 'ci-env:\n\t@test -z "$$PYTHON_VERSION$$PYTHON_SHA256$$RUN_ID$$LANES$$LANE_TIMEOUT"\n'
    # ci-forge writes a green status for ci-red into the results file while it runs, which the statuses written only
    # once every lane has run overwrite (D-072, the step 4 Codex read)
    makefile += 'ci-forge:\n\t@echo "ci-red 0" > ../results.txt\n'
    (work / "Makefile").write_text(makefile, encoding = "utf-8", newline = "\n")
    lanes = ("ci-red", "ci-green", "ci-hang", "ci-env", "ci-forge")
    image = {
        "PYTHON_VERSION": "3.14.7",
        "PYTHON_SHA256": "0" * 64,
        "RUN_ID": "run",
        "LANES": "ci-env",
        "LANE_TIMEOUT": "9",
    }
    done  = subprocess.run(
        [str(BASH), LANES.as_posix(), work.as_posix(), "results.txt", "3", *lanes],
        capture_output = True,
        text = True,
        cwd = tmp_path,
        env = {**os.environ, **image},
        timeout = 60,
    )
    assert done.returncode == 0, "a red or a hung lane never stops the script"
    recorded = (tmp_path / "results.txt").read_text(encoding = "utf-8").splitlines()
    assert recorded == ["ci-red 2", "ci-green 0", "ci-hang 124", "ci-env 0", "ci-forge 0"], done.stdout + done.stderr
    # each lane's own output in a file of its own beside the results, written whole before the lanes changed folder,
    # and printed when the lane ends (D-072)
    outputs = tmp_path / "lanes"
    assert sorted(path.name for path in outputs.iterdir()) == [f"{lane}.log" for lane in sorted(lanes)]
    assert (outputs / "ci-green.log").read_text(encoding = "utf-8") == "green\n"
    assert "ci-red" in (outputs / "ci-red.log").read_text(encoding = "utf-8"), "make's error, from stderr"
    assert "green\n==== kdf-preflight lane ci-green exited 0" in done.stdout


def test_a_later_lanes_longer_notice_still_fits_the_budget(tmp_path: Path) -> None:
    # the room kept for the notice is the longest failed lane's, so a lane with a longer name after the budget is
    # nearly spent still leaves every excerpt within 64 KiB (D-072, the second Codex read)
    if BASH is None and not os.environ.get("CI"):
        pytest.skip("the lane script needs bash")
    outputs = tmp_path / "lanes"
    outputs.mkdir()
    # with the run id r, four lanes of 50 full lines leave 136 bytes and ci-5's one short line 99, under the 109 bytes
    # the long lane's notice needs, which a room kept for each lane's own notice alone would overshoot by 11
    lanes = [f"ci-{number}" for number in range(1, 6)] + ["ci-this-is-a-slightly-longer-lane-name"]
    (tmp_path / "results.txt").write_text("".join(f"{lane} 2\n" for lane in lanes), encoding = "utf-8")
    for lane in lanes:
        lines = "".join(f"{index:03d}{'p' * 400}\n" for index in range(80))
        if lane == "ci-5":
            lines = "x" * 10 + "\n"
        (outputs / f"{lane}.log").write_text(lines, encoding = "utf-8", newline = "\n")
    done = subprocess.run(
        [str(BASH), LANES.as_posix(), "--tails", "results.txt", "r"],
        capture_output = True,
        text = True,
        cwd = tmp_path,
        timeout = 60,
    )
    assert done.returncode == 0 and len(done.stderr.encode("utf-8")) <= 65536, len(done.stderr.encode("utf-8"))
    assert done.stderr.splitlines()[-1].endswith("[the excerpts stop here, their 65536 bytes spent]")


@pytest.mark.skipif(sys.platform == "win32", reason = "a file's and a folder's modes lock them on Linux alone")
def test_a_lane_that_locks_a_forged_status_in_place_never_keeps_it(tmp_path: Path) -> None:
    # a lane runs as the same user as the lane script, so it may write green statuses and lock the file and its folder,
    # which the script makes its own again before it writes the true ones (D-072, the second Codex read)
    if (BASH is None or shutil.which("make") is None) and not os.environ.get("CI"):
        pytest.skip("the lane script needs bash and make")
    work = tmp_path / "work"
    work.mkdir()
    makefile = "ci-red:\n\t@exit 2\n"
    makefile += "ci-lock:\n\t@printf 'ci-red 0\\nci-lock 0\\n' > ../results.txt\n"
    makefile += "\t@chmod 444 ../results.txt\n\t@chmod 555 ..\n"
    (work / "Makefile").write_text(makefile, encoding = "utf-8", newline = "\n")
    done = subprocess.run(
        [str(BASH), LANES.as_posix(), work.as_posix(), "results.txt", "30", "ci-red", "ci-lock"],
        capture_output = True,
        text = True,
        cwd = tmp_path,
        timeout = 60,
    )
    tmp_path.chmod(0o755)
    assert done.returncode == 0, done.stdout + done.stderr
    assert (tmp_path / "results.txt").read_text(encoding = "utf-8").splitlines() == ["ci-red 2", "ci-lock 0"]


def test_the_lane_script_prints_a_bounded_excerpt_of_each_failed_lane_after_its_run(tmp_path: Path) -> None:
    # once BuildKit clips a noisy lane it drops the rest of the step's stdout, so the image's last step prints each
    # failed lane's own last lines, on stderr, at most 50 of 300 bytes each and 64 KiB in all (D-072)
    if BASH is None and not os.environ.get("CI"):
        pytest.skip("the lane script needs bash")
    outputs = tmp_path / "lanes"
    outputs.mkdir()
    lanes = {"ci-green": 0, "ci-wide": 2, **{f"ci-loud-{number}": 3 for number in range(1, 7)}}
    (tmp_path / "results.txt").write_text(
        "".join(f"{lane} {status}\n" for lane, status in lanes.items()),
        encoding = "utf-8",
        newline = "\n",
    )
    (outputs / "ci-green.log").write_text("green\n", encoding = "utf-8", newline = "\n")
    (outputs / "ci-wide.log").write_text("start\n" + "w" * 1000 + "\nthe reason\n", encoding = "utf-8", newline = "\n")
    for number in range(1, 7):
        lines = "".join(f"{number}-{index}-{'l' * 400}\n" for index in range(80))
        (outputs / f"ci-loud-{number}.log").write_text(lines, encoding = "utf-8", newline = "\n")
    done = subprocess.run(
        [str(BASH), LANES.as_posix(), "--tails", "results.txt", "run-1"],
        capture_output = True,
        text = True,
        cwd = tmp_path,
        timeout = 60,
    )
    assert done.returncode == 0 and not done.stdout, "the excerpts go to stderr alone"
    lines = done.stderr.splitlines()
    assert all(line.startswith("KDF-PREFLIGHT-TAIL run-1 ") for line in lines)
    assert not [line for line in lines if " ci-green " in line], "a green lane has no excerpt"
    wide = [line.removeprefix("KDF-PREFLIGHT-TAIL run-1 ci-wide ") for line in lines if " ci-wide " in line]
    assert wide == ["start", "w" * 300, "the reason"], "each line cut to 300 bytes"
    loud = [line for line in lines if " ci-loud-1 " in line]
    assert len(loud) == 50 and loud[-1].endswith("1-79-" + "l" * 295), "the last 50 lines"
    assert lines[-1].endswith("[the excerpts stop here, their 65536 bytes spent]"), "a visible notice"
    assert len(done.stderr.encode("utf-8")) <= 65536, "the budget bounds every excerpt, markers and notice counted"
    assert not [line for line in lines if " ci-loud-6 " in line and "stop here" not in line]


def test_the_base_installs_shellcheck_and_fails_without_it() -> None:
    # actionlint runs ShellCheck over every run: script only when it is on the PATH, as on GitHub's runner, and skips
    # that check without a word when it is not (D-072)
    apt = [rest for keyword, rest in _stages()[0] if keyword == "RUN" and "apt-get install" in rest]
    assert len(apt) == 1 and "shellcheck" in apt[0].split(), "ShellCheck beside git and make, from Debian"
    assert "&& shellcheck --version" in apt[0], "its version printed, so a base without it fails to build"


def test_the_base_installs_curl_as_on_githubs_runner_and_fails_without_it() -> None:
    # the local code scan's install tests fetch with curl and skip without it, so the pre-flight runs them as CI does
    # (D-085)
    apt = [rest for keyword, rest in _stages()[0] if keyword == "RUN" and "apt-get install" in rest]
    assert len(apt) == 1 and "curl" in apt[0].split(), "curl beside git, make and ShellCheck, from Debian"
    assert "&& curl --version" in apt[0], "its version printed, so a base without it fails to build"


def test_the_actionlint_lane_is_red_when_no_shellcheck_is_on_the_path() -> None:
    text  = LANES.read_text(encoding = "utf-8")
    guard = text.find("command -v shellcheck")
    run   = text.find('"$limit" actionlint')
    assert -1 < guard < run, "the guard comes before actionlint runs"
    assert re.search(r"\bstatus=127\b", text[guard:run]), "the lane's status is 127, red"


# ----------------------------------------------------------------------------------------------------------------------
# setup first, in the lane script (D-078)
# ----------------------------------------------------------------------------------------------------------------------
def _work(tmp_path: Path, makefile: str, files: dict[str, str] | None = None) -> Path:
    """
    A work tree as the image makes it, the Makefile and the files committed in a repo of one commit.
    """
    if (BASH is None or GIT is None or shutil.which("make") is None) and not os.environ.get("CI"):
        pytest.skip("the lane script needs bash, git and make")
    work = tmp_path / "work"
    work.mkdir()
    for name, text in {"Makefile": makefile, **(files or {})}.items():
        (work / name).parent.mkdir(parents = True, exist_ok = True)
        (work / name).write_text(text, encoding = "utf-8", newline = "\n")
    _git(work, "init", "-q", "-b", "main")
    _git(work, "config", "core.autocrlf", "false")
    _git(work, "add", "-A")
    _git(work, "-c", "user.name=kdf-preflight", "-c", "user.email=kdf-preflight@localhost", "commit", "-q", "-m", "w")
    return work


def _lane_script(tmp_path: Path, *args: str, timeout: int = 60) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [str(BASH), LANES.as_posix(), *args],
        capture_output = True,
        text = True,
        cwd = tmp_path,
        timeout = timeout,
    )


def _lines(path: Path) -> list[str]:
    return path.read_text(encoding = "utf-8").splitlines()


def _lf(path: Path, text: str) -> None:
    """
    A file as the lane script writes it in the image, LF on any machine.
    """
    path.write_text(text, encoding = "utf-8", newline = "\n")


def test_a_green_setup_runs_first_then_every_lane_in_order(tmp_path: Path) -> None:
    makefile = "setup:\n\t@echo set up\n\t@echo setup > ../order.txt\n"
    makefile += "ci-a:\n\t@echo a >> ../order.txt\nci-b:\n\t@echo b >> ../order.txt\n"
    work = _work(tmp_path, makefile)
    done = _lane_script(
        tmp_path,
        "--setup",
        "setup",
        "--mirrors",
        (tmp_path / "none").as_posix(),
        work.as_posix(),
        "results.txt",
        "30",
        "ci-a",
        "ci-b",
    )
    assert done.returncode == 0, done.stdout + done.stderr
    assert _lines(tmp_path / "order.txt") == ["setup", "a", "b"]
    assert _lines(tmp_path / "results.txt") == ["ci-a 0", "ci-b 0"]
    # setup's status in a file of its own beside the results, its output in its own log, printed when it ends
    assert _lines(tmp_path / "setup") == ["setup 0"]
    assert _lines(tmp_path / "setup.log") == ["set up"]
    assert "set up\n==== kdf-preflight setup setup exited 0" in done.stdout


def test_a_red_setup_skips_each_make_lane_and_still_runs_actionlint(tmp_path: Path) -> None:
    makefile = "setup-red:\n\t@echo the reason setup failed\n\t@exit 2\nci-a:\n\t@echo ran > ../ran.txt\n"
    work     = _work(tmp_path, makefile)
    done = _lane_script(tmp_path, "--setup", "setup-red", work.as_posix(), "results.txt", "30", "ci-a", "actionlint")
    assert done.returncode == 0, done.stdout + done.stderr
    assert not (tmp_path / "ran.txt").exists(), "no make lane runs after a red setup"
    recorded = _lines(tmp_path / "results.txt")
    assert recorded[0] == "ci-a skipped" and re.fullmatch(r"actionlint \d+", recorded[1]), recorded
    assert _lines(tmp_path / "setup") == ["setup-red 2"]
    assert "the reason setup failed" in (tmp_path / "setup.log").read_text(encoding = "utf-8")
    assert not (tmp_path / "lanes" / "ci-a.log").exists()


def test_a_setup_past_its_timeout_is_recorded_124_and_red(tmp_path: Path) -> None:
    work = _work(tmp_path, "setup:\n\t@sleep 30\nci-a:\n\t@echo a\n")
    done = _lane_script(tmp_path, "--setup", "setup", work.as_posix(), "results.txt", "2", "ci-a")
    assert done.returncode == 0, done.stdout + done.stderr
    assert _lines(tmp_path / "setup") == ["setup 124"] and _lines(tmp_path / "results.txt") == ["ci-a skipped"]


def test_no_setup_runs_none_and_leaves_no_setup_file(tmp_path: Path) -> None:
    work = _work(tmp_path, "setup:\n\t@echo setup > ../ran.txt\nci-a:\n\t@echo a\n")
    done = _lane_script(tmp_path, "--setup", "", work.as_posix(), "results.txt", "30", "ci-a")
    assert done.returncode == 0, done.stdout + done.stderr
    assert not (tmp_path / "ran.txt").exists() and not (tmp_path / "setup").exists()
    assert _lines(tmp_path / "results.txt") == ["ci-a 0"]


def test_the_env_files_a_green_setup_leaves_are_removed_and_named_before_the_first_lane(tmp_path: Path) -> None:
    # the checkout CI makes has no .env file, so one a setup copies from its example is removed before the lanes, an
    # example and a tracked file kept (D-078)
    makefile = "setup:\n\t@cp .env.local.example .env.local\n\t@echo X= > .env.kdf\n"
    makefile += "\t@mkdir -p sub && echo Y= > sub/.ENV.prod && cp .env.local.example sub/.env.extra.example\n"
    makefile += "\t@echo kept > notes.txt\n"
    makefile += "ci-green:\n\t@test ! -e .env.local && test ! -e .env.kdf && test ! -e sub/.ENV.prod\n"
    makefile += "\t@test -e .env.local.example && test -e sub/.env.extra.example && test -e notes.txt\n"
    files = {".env.local.example": "# A=\n", ".gitignore": ".env.local\n.env.kdf\nsub/\n"}
    work  = _work(tmp_path, makefile, files)
    done  = _lane_script(tmp_path, "--setup", "setup", work.as_posix(), "results.txt", "30", "ci-green")
    assert done.returncode == 0, done.stdout + done.stderr
    assert _lines(tmp_path / "setup") == ["setup 0"] and _lines(tmp_path / "results.txt") == ["ci-green 0"]
    for name in (".env.kdf", ".env.local", "sub/.ENV.prod"):
        assert f"kdf-preflight: removed {name}, which setup left and git does not track" in done.stdout, done.stdout
    assert "removed .env.local.example" not in done.stdout and "removed sub/.env.extra.example" not in done.stdout


@pytest.mark.skipif(sys.platform == "win32", reason = "a folder's mode locks a file in it on Linux alone")
def test_an_env_file_the_script_cannot_remove_records_setup_red_and_names_it(tmp_path: Path) -> None:
    makefile = "setup:\n\t@mkdir locked && echo X= > locked/.env.local && chmod 555 locked\nci-a:\n\t@echo a\n"
    work     = _work(tmp_path, makefile, {".gitignore": "locked/\n"})
    done     = _lane_script(tmp_path, "--setup", "setup", work.as_posix(), "results.txt", "30", "ci-a")
    (work / "locked").chmod(0o755)
    assert done.returncode == 0, done.stdout + done.stderr
    assert _lines(tmp_path / "setup") == ["setup 1"] and _lines(tmp_path / "results.txt") == ["ci-a skipped"]
    assert "locked/.env.local could not be removed" in (tmp_path / "setup.log").read_text(encoding = "utf-8")


@pytest.mark.parametrize("names", [("kriegerdataforge-fmt", "kriegerdataforge-sdk"), ()])
def test_the_rewrite_to_each_mirror_is_set_for_setup_and_every_lane(tmp_path: Path, names: tuple[str, ...]) -> None:
    # the lines CI's step "Point git at the private mirrors" writes, one rewrite a mirror, and none with no mirror
    mirrors = tmp_path / "mirrors"
    mirrors.mkdir()
    for name in names:
        (mirrors / f"{name}.git").mkdir()
    (mirrors / "notes.txt").write_text("no mirror\n", encoding = "utf-8")
    dump     = "@env | grep '^GIT_CONFIG' | LC_ALL=C sort > ../{0}.txt || true\n"
    makefile = "setup:\n\t" + dump.format("setup-env") + "ci-a:\n\t" + dump.format("lane-env")
    work     = _work(tmp_path, makefile)
    done     = _lane_script(
        tmp_path,
        "--setup",
        "setup",
        "--mirrors",
        mirrors.as_posix(),
        work.as_posix(),
        "results.txt",
        "30",
        "ci-a",
    )
    assert done.returncode == 0, done.stdout + done.stderr
    expected = [f"GIT_CONFIG_COUNT={len(names)}"] if names else []
    expected += [f"GIT_CONFIG_KEY_{index}=url.file://{mirrors.as_posix()}/{name}.git.insteadOf"
                 for index, name in enumerate(names)]
    expected += [
        f"GIT_CONFIG_VALUE_{index}=https://github.com/Needless2Say/{name}.git" for index, name in enumerate(names)
    ]
    assert _lines(tmp_path / "setup-env.txt") == sorted(expected)
    assert _lines(tmp_path / "lane-env.txt") == sorted(expected)


@pytest.mark.parametrize("setup", ["setup", ""])
def test_a_lane_forging_setups_status_never_keeps_it(tmp_path: Path, setup: str) -> None:
    # setup's status is written once every lane has run, by the same remove, write and read back as the lanes', so a
    # lane's write there is gone, and with no setup no file is left (D-078)
    makefile = "setup:\n\t@echo set\nci-forge:\n\t@printf 'setup 0\\nsetup 0\\n' > ../setup\n\t@exit 3\n"
    work     = _work(tmp_path, makefile)
    done     = _lane_script(tmp_path, "--setup", setup, work.as_posix(), "results.txt", "30", "ci-forge")
    assert done.returncode == 0, done.stdout + done.stderr
    assert _lines(tmp_path / "results.txt") == ["ci-forge 2"], "make reports a failed recipe as 2"
    if setup:
        assert _lines(tmp_path / "setup") == ["setup 0"]
    else:
        assert not (tmp_path / "setup").exists()


def test_a_red_setups_excerpt_comes_first_and_stays_within_the_budget(tmp_path: Path) -> None:
    if BASH is None and not os.environ.get("CI"):
        pytest.skip("the lane script needs bash")
    outputs = tmp_path / "lanes"
    outputs.mkdir()
    _lf(tmp_path / "results.txt", "ci-a skipped\nci-b skipped\nactionlint 1\n")
    _lf(tmp_path / "setup", "setup 2\n")
    lines = "".join(f"{index:03d}{'s' * 400}\n" for index in range(80)) + "the reason setup failed\n"
    _lf(tmp_path / "setup.log", lines)
    _lf(outputs / "actionlint.log", "a workflow is wrong\n")
    done = _lane_script(tmp_path, "--tails", "results.txt", "r")
    assert done.returncode == 0 and not done.stdout
    printed = done.stderr.splitlines()
    setup   = [line for line in printed if line.startswith("KDF-PREFLIGHT-SETUP-TAIL r ")]
    assert printed[:len(setup)] == setup and len(setup) == 50, "setup's excerpt first, its last 50 lines"
    assert setup[-1] == "KDF-PREFLIGHT-SETUP-TAIL r the reason setup failed"
    assert setup[0] == "KDF-PREFLIGHT-SETUP-TAIL r 031" + "s" * 297, "each line cut to 300 bytes"
    assert printed[len(setup):] == ["KDF-PREFLIGHT-TAIL r actionlint a workflow is wrong"], "a skipped lane has none"
    assert len(done.stderr.encode("utf-8")) <= 65536


def test_a_green_setup_has_no_excerpt_and_a_long_one_keeps_the_budget(tmp_path: Path) -> None:
    if BASH is None and not os.environ.get("CI"):
        pytest.skip("the lane script needs bash")
    outputs = tmp_path / "lanes"
    outputs.mkdir()
    _lf(tmp_path / "setup", "setup 0\n")
    _lf(tmp_path / "setup.log", "fine\n")
    _lf(tmp_path / "results.txt", "ci-a 2\n")
    _lf(outputs / "ci-a.log", "the reason\n")
    done = _lane_script(tmp_path, "--tails", "results.txt", "r")
    assert done.stderr.splitlines() == ["KDF-PREFLIGHT-TAIL r ci-a the reason"]
    # a red setup and every lane red, setup's notice keeping its room, all of it within 64 KiB
    _lf(tmp_path / "setup", "setup 2\n")
    _lf(tmp_path / "setup.log", "".join(f"{'s' * 400}\n" for _ in range(80)))
    lanes = [f"ci-{number}" for number in range(1, 8)]
    _lf(tmp_path / "results.txt", "".join(f"{lane} 2\n" for lane in lanes))
    for lane in lanes:
        _lf(outputs / f"{lane}.log", "".join(f"{'l' * 400}\n" for _ in range(80)))
    done = _lane_script(tmp_path, "--tails", "results.txt", "r")
    assert done.returncode == 0 and len(done.stderr.encode("utf-8")) <= 65536
    assert done.stderr.splitlines()[0].startswith("KDF-PREFLIGHT-SETUP-TAIL r ")
    assert done.stderr.splitlines()[-1].endswith("[the excerpts stop here, their 65536 bytes spent]")

# ======================================================================================================================
# the wrapper
# ======================================================================================================================

@dataclass
class Rig:
    """
    A repo with two commits, a home for docker's and git's configuration, the runs folder, the stand ins for docker and
    gh, the folder of bare remotes the wrapper fetches from, where the stand in for docker copies the mirrors and the
    npm folder, the test's own npm cache and LOCALAPPDATA, and the folder of stand ins first on the PATH.
    """
    repo:      Path
    home:      Path
    runs:      Path
    fake:      Path
    log:       Path
    tar:       Path
    gh:        Path
    remotes:   Path
    mirrors:   Path
    npm_seen:  Path
    npm_cache: Path
    local:     Path
    stubs:     Path


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(repo), *args],
        check = True,
        capture_output = True,
        text = True,
    ).stdout.strip()


def _commit(repo: Path, files: dict[str, str], message: str) -> None:
    for name, text in files.items():
        (repo / name).parent.mkdir(parents = True, exist_ok = True)
        (repo / name).write_text(text, encoding = "utf-8", newline = "\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", message)


def _long(path: Path) -> Path:
    """
    The path as Windows reads one past 260 characters whatever its long paths setting, by its extended length prefix,
    and the path itself elsewhere, since a tarball's digest path in npm's cache layout runs past that limit under
    pytest's temp folder. The tool's own copies run in Git Bash, whose runtime reads such a path either way.
    """
    if sys.platform != "win32":
        return path
    return Path("\\\\?\\" + os.path.abspath(path))


@pytest.fixture()
def rig(tmp_path: Path) -> Iterator[Rig]:
    if (BASH is None or GIT is None or NODE is None) and not os.environ.get("CI"):
        pytest.skip("kdf-preflight.sh needs bash, git and node")
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q", "-b", "main")
    _git(repo, "config", "user.email", "dev@example.com")
    _git(repo, "config", "user.name", "Dev")
    _git(repo, "config", "core.autocrlf", "false")
    _commit(repo, {
        "Makefile": MAKEFILE,
        ".github/workflows/ci.yml": "name: CI\n",
        ".gitignore": "ignored.txt\n",
        "a.txt": "first\n",
    }, "first")
    _commit(repo, {"b.txt": "second\n"}, "second")
    home = tmp_path / "home"
    home.mkdir()
    local = tmp_path / "local"
    local.mkdir()
    stubs = tmp_path / "stubs"
    stubs.mkdir()
    _program(stubs / "npm", NPM_STUB)
    _program(stubs / "cygpath", CYGPATH_STUB)
    made = Rig(
        repo = repo,
        home = home,
        runs = tmp_path / "runs",
        fake = _program(tmp_path / "fake-docker", FAKE),
        log = tmp_path / "docker.log",
        tar = tmp_path / "seen.tar",
        gh = _program(tmp_path / "fake-gh", FAKE_GH),
        remotes = tmp_path / "remotes",
        mirrors = tmp_path / "seen-mirrors",
        npm_seen = tmp_path / "seen-npm",
        npm_cache = tmp_path / "npm-cache",
        local = local,
        stubs = stubs,
    )
    yield made
    # the npm folders hold digest paths past 260 characters, which pytest's later removal of an old temp folder may not
    # reach on a Windows machine whose long paths setting is off, so they are removed here
    for folder in (made.npm_cache, made.npm_seen, local / "npm-cache", home / ".npm"):
        shutil.rmtree(_long(folder), ignore_errors = True)


def _program(path: Path, text: str) -> Path:
    path.write_text(text, encoding = "utf-8", newline = "\n")
    path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    return path


def _run(
    rig: Rig,
    *args: str,
    mode: str = "pass",
    env: dict[str, str | None] | None = None,
) -> subprocess.CompletedProcess[str]:
    """
    Run the tool with exactly these arguments, the stand ins playing docker in the given mode, gh, npm and cygpath, git
    fetching from the rig's remotes, with no docker or git variable of this machine's, a home and a LOCALAPPDATA of the
    rig's own, and the rig's npm cache, so no test reads the owner's (D-087). A variable given as None is unset.
    """
    environment: dict[str, str | None] = {
        key: value for key, value in os.environ.items()
        if key not in DOCKER_ENV and not key.startswith("GIT_") and key != "KDF_NPM_CACHE"
    }
    environment.update({
        "KDF_DOCKER_BIN": rig.fake.as_posix(),
        "KDF_GH_BIN": rig.gh.as_posix(),
        "KDF_PREFLIGHT_DIR": rig.runs.as_posix(),
        "KDF_PREFLIGHT_GIT_BASE": rig.remotes.as_uri(),
        "KDF_NPM_CACHE": rig.npm_cache.as_posix(),
        "HOME": rig.home.as_posix(),
        "USERPROFILE": str(rig.home),
        "LOCALAPPDATA": str(rig.local),
        "FAKE_MODE": mode,
        "FAKE_LOG": rig.log.as_posix(),
        "FAKE_TAR": rig.tar.as_posix(),
        "FAKE_MIRRORS": rig.mirrors.as_posix(),
        "FAKE_NPM": rig.npm_seen.as_posix(),
    })
    environment.update(env or {})
    # the stand ins for npm and cygpath first, before any PATH a test gives
    environment["PATH"] = f"{rig.stubs.as_posix()}{os.pathsep}{environment['PATH']}"
    done = subprocess.run(
        [str(BASH), str(TOOL), *args],
        capture_output = True,
        text = True,
        env = {key: value for key, value in environment.items() if value is not None},
        timeout = 120,
    )
    assert not [line for line in _logged(rig) if line.startswith("npm ")], "the tool ran npm on the host"
    return done


def _preflight(
    rig: Rig,
    *lanes: str,
    extra: tuple[str, ...] = (),
    mode: str = "pass",
    env: dict[str, str | None] | None = None,
) -> subprocess.CompletedProcess[str]:
    args = ["--repo", rig.repo.as_posix()]
    for lane in lanes:
        args += ["--lane", lane]
    return _run(rig, *args, *extra, mode = mode, env = env)


def _logged(rig: Rig) -> list[str]:
    return rig.log.read_text(encoding = "utf-8").splitlines() if rig.log.exists() else []


def _calls(rig: Rig) -> list[list[str]]:
    return [line.split()[1:] for line in _logged(rig) if line.startswith("call ")]


def _run_ids(rig: Rig) -> list[str]:
    return re.findall(r"--build-arg=RUN_ID=(\S+)", "\n".join(_logged(rig)))


def _left(rig: Rig) -> list[Path]:
    return sorted(rig.runs.iterdir()) if rig.runs.exists() else []


def _guard_options(sub: str) -> set[str]:
    """
    The options the guard's approved list takes for docker <sub>, from DOCKER_SUBS in kdf-guard.js (D-068).
    """
    text  = GUARD.read_text(encoding = "utf-8")
    block = text[text.index("const DOCKER_SUBS = {"):]
    block = block[:block.index("};")]
    entry = re.search(rf"\b{sub}: ((?:'[^']*'\s*\+?\s*)+)", block)
    assert entry, f"the guard lists docker {sub}"
    return set(" ".join(re.findall(r"'([^']*)'", entry.group(1))).split())


def _refused(done: subprocess.CompletedProcess[str], rig: Rig, says: str) -> None:
    assert done.returncode == 2 and says in done.stderr, done.stderr
    assert not _calls(rig), "nothing reached docker"
    assert not _left(rig), "a refused run leaves no folder"


# ----------------------------------------------------------------------------------------------------------------------
# what a session may ask
# ----------------------------------------------------------------------------------------------------------------------
@pytest.mark.parametrize("args, says", [
    ([], "--repo is required"),
    (["--lane", "ci-lint"], "--repo is required"),
    (["--repo", "."], "at least one --lane"),
    (["--repo", ".", "--lane"], "--lane needs a value"),
    (["--repo", ".", "--lane", "ci-lint", "--bogus"], "unknown argument --bogus"),
    *[(["--repo", ".", "--lane", "ci-lint", "--timeout", value], "--timeout is a whole number")
      for value in ("0", "-5", "abc", "", "1.5", "9999999")],
])
def test_bad_arguments_are_refused(rig: Rig, args: list[str], says: str) -> None:
    _refused(_run(rig, *args), rig, says)


@pytest.mark.parametrize("variable", DOCKER_ENV)
def test_a_docker_pointed_elsewhere_by_its_environment_is_refused(rig: Rig, variable: str) -> None:
    _refused(_preflight(rig, "ci-lint", env = {variable: "elsewhere"}), rig, f"{variable} is set")


@pytest.mark.parametrize("files, says", [
    ({"config.json": '{"currentContext": "remote-box"}'}, "current context is remote-box"),
    ({"config.json": "{not json"}, "could not be read"),
    ({"buildx/current": '{"Key":"desktop-linux","Name":"cloud-builder","Global":false}'}, "builder is cloud-builder"),
    ({"buildx/current": '{"Key":"tcp-elsewhere","Name":"","Global":true}'}, "endpoint is tcp-elsewhere"),
    ({"buildx/current": "nope"}, "could not be read"),
])
def test_a_docker_pointed_elsewhere_by_its_files_is_refused(rig: Rig, files: dict[str, str], says: str) -> None:
    for name, text in files.items():
        (rig.home / ".docker" / name).parent.mkdir(parents = True, exist_ok = True)
        (rig.home / ".docker" / name).write_text(text, encoding = "utf-8")
    _refused(_preflight(rig, "ci-lint"), rig, says)


@pytest.mark.parametrize("files", [
    {},
    {"config.json": '{"currentContext": "desktop-linux", "credsStore": "desktop"}'},
    {"config.json": '{"currentContext": "default"}', "buildx/current": '{"Key":"desktop-linux","Name":""}'},
    {"buildx/current": '{"Key":"default","Name":"default","Global":false}'},
])
def test_the_local_engine_and_its_own_builder_pass(rig: Rig, files: dict[str, str]) -> None:
    for name, text in files.items():
        (rig.home / ".docker" / name).parent.mkdir(parents = True, exist_ok = True)
        (rig.home / ".docker" / name).write_text(text, encoding = "utf-8")
    done = _preflight(rig, "ci-lint")
    assert done.returncode == 0, done.stderr


def test_a_folder_that_is_not_a_repo_or_a_commit_it_lacks_is_refused(rig: Rig, tmp_path: Path) -> None:
    plain = tmp_path / "plain"
    plain.mkdir()
    _refused(_run(rig, "--repo", (tmp_path / "nothing").as_posix(), "--lane", "ci-lint"), rig, "is not a folder")
    _refused(_run(rig, "--repo", plain.as_posix(), "--lane", "ci-lint"), rig, "is not a git repository")
    _refused(_preflight(rig, "ci-lint", extra = ("--at", "no-such-ref")), rig, "has no commit no-such-ref")


@pytest.mark.parametrize("change", ["modified", "staged", "untracked"])
def test_a_tree_with_changes_or_new_files_and_no_at_is_refused(rig: Rig, change: str) -> None:
    if change == "untracked":
        (rig.repo / "new.txt").write_text("new\n", encoding = "utf-8")
    else:
        (rig.repo / "a.txt").write_text("changed\n", encoding = "utf-8")
    if change == "staged":
        _git(rig.repo, "add", "a.txt")
    _refused(_preflight(rig, "ci-lint"), rig, "commit them, or pass --at")


def test_an_ignored_file_leaves_the_tree_clean(rig: Rig) -> None:
    (rig.repo / "ignored.txt").write_text("local\n", encoding = "utf-8")
    assert _preflight(rig, "ci-lint").returncode == 0


def test_at_runs_the_commit_as_it_stands_and_prints_its_full_hash(rig: Rig) -> None:
    (rig.repo / "new.txt").write_text("new\n", encoding = "utf-8")
    first = _git(rig.repo, "rev-parse", "HEAD~1")
    done  = _preflight(rig, "ci-lint", extra = ("--at", "HEAD~1"))
    assert done.returncode == 0, done.stderr
    assert first in done.stdout.splitlines()[0] and first in done.stdout.splitlines()[-1]
    with tarfile.open(rig.tar) as archive:
        names = archive.getnames()
    assert "a.txt" in names and "b.txt" not in names and "new.txt" not in names


@pytest.mark.parametrize("name", [
    ".env.kdf", "config/.ENV.LOCAL", "keys/notes.txt", "certs/site.pem", "certs/server.key", "deploy/id_ed25519",
    "infra/prod.tfvars", "state/main.tfstate.backup", ".netrc",
])
def test_a_tracked_secret_file_is_refused_before_anything_is_exported(rig: Rig, name: str) -> None:
    _commit(rig.repo, {name: "X=1\n"}, "a secret")
    _refused(_preflight(rig, "ci-lint"), rig, f"{name}, named like a secret file")


@pytest.mark.parametrize("name", [".env.example", "app/.env.kdf.example"])
def test_an_env_example_is_no_secret(rig: Rig, name: str) -> None:
    _commit(rig.repo, {name: "# X=\n"}, "an example")
    assert _preflight(rig, "ci-lint").returncode == 0


@pytest.mark.parametrize("lane, says", [
    ("ci-deploy-prod", "the owner's"),
    ("ci-release-notes", "the owner's"),
    ("ci-publish-docs", "the owner's"),
    ("ci-dev-check", "the owner's"),
    ("ci-version-check", "origin/main"),
    ("ci-missing", "no target"),
    ("ci-x", "no target"),
    ("ci-hidden", "no target"),
    ("lint", "no lane"),
    ("CI-LINT", "no lane"),
    ("ci_lint", "no lane"),
    ("ci-lint;true", "no lane"),
    ("ci-", "no lane"),
])
def test_a_lane_that_is_not_the_sessions_to_run_is_refused(rig: Rig, lane: str, says: str) -> None:
    _refused(_preflight(rig, lane), rig, says)


def test_a_dev_lane_that_names_local_runs_and_a_lane_named_twice_is_refused(rig: Rig) -> None:
    assert _preflight(rig, "ci-dev-local-check").returncode == 0
    rig.log.unlink()
    _refused(_preflight(rig, "ci-lint", "ci-lint"), rig, "named twice")


def test_actionlint_needs_workflows_at_the_commit(rig: Rig) -> None:
    assert _preflight(rig, "actionlint").returncode == 0
    rig.log.unlink()
    _git(rig.repo, "rm", "-q", ".github/workflows/ci.yml")
    _git(rig.repo, "commit", "-q", "-m", "no workflows")
    _refused(_preflight(rig, "actionlint"), rig, "no workflows")


# ----------------------------------------------------------------------------------------------------------------------
# what reaches docker
# ----------------------------------------------------------------------------------------------------------------------
def test_a_clean_run_builds_the_base_then_the_lanes_and_reads_every_lane_green(rig: Rig) -> None:
    done = _preflight(rig, "ci-lint", "ci-unit-tests", "actionlint")
    assert done.returncode == 0, done.stderr
    head = _git(rig.repo, "rev-parse", "HEAD")
    assert head in done.stdout and all(f"{lane} passed" in done.stdout for lane in ("ci-lint", "ci-unit-tests"))
    builds = [call for call in _calls(rig) if call[0] == "build"]
    assert len(builds) == 2 and "--target=base" in builds[0] and "--target=lanes" in builds[1]
    base = hashlib.sha256(DOCKERFILE.read_bytes()).hexdigest()[:16]
    assert f"--tag=kdf-preflight-base:{base}" in builds[0], "the base tagged by the Dockerfile's hash"
    run_id, = _run_ids(rig)
    assert f"--tag=kdf-preflight-run:{run_id}" in builds[1]
    assert "--build-arg=LANES=ci-lint ci-unit-tests actionlint" in rig.log.read_text(encoding = "utf-8")
    assert _calls(rig)[-1] == ["rmi", f"kdf-preflight-run:{run_id}"], "the run's image removed at the end"
    assert not _left(rig), "a green run's folder removed"


def test_the_context_holds_the_tar_the_dockerfile_the_lane_script_the_mirrors_and_npm_alone(rig: Rig) -> None:
    # the mirrors and npm folders are always made, empty when nothing is mirrored or served, since the lane stage copies
    # each (D-078, D-087)
    assert _preflight(rig, "ci-lint").returncode == 0
    contexts = [line.rstrip() for line in _logged(rig) if line.startswith("context ")]
    assert contexts == [
        "context base Dockerfile lanes.sh mirrors npm repo.tar",
        "context lanes Dockerfile lanes.sh mirrors npm repo.tar",
    ]
    assert rig.mirrors.is_dir() and not list(rig.mirrors.iterdir())
    assert rig.npm_seen.is_dir() and not list(rig.npm_seen.iterdir())


def test_every_docker_option_the_wrapper_passes_is_on_the_guards_list(rig: Rig) -> None:
    assert _preflight(rig, "ci-lint", "actionlint", mode = "red").returncode == 1
    for call in _calls(rig):
        allowed = _guard_options(call[0])
        for word in call[1:]:
            if word.startswith("-"):
                assert (word.split("=")[0] + "=" if "=" in word else word) in allowed, f"docker {call[0]} {word}"


def test_each_lane_runs_with_what_remains_of_the_timeout(rig: Rig) -> None:
    assert _preflight(rig, "ci-lint", extra = ("--timeout", "120")).returncode == 0
    limit = re.search(r"--build-arg=LANE_TIMEOUT=(\d+)", rig.log.read_text(encoding = "utf-8"))
    assert limit and 0 < int(limit.group(1)) <= 120


def test_the_archive_is_lf_and_keeps_modes_whatever_the_repos_settings(rig: Rig) -> None:
    _commit(rig.repo, {".gitattributes": "* text=auto\n", "run.sh": "#!/bin/sh\necho hi\n"}, "attributes")
    _git(rig.repo, "update-index", "--chmod=+x", "run.sh")
    _git(rig.repo, "commit", "-q", "-m", "a mode")
    _git(rig.repo, "config", "core.autocrlf", "true")
    done = _preflight(rig, "ci-lint", extra = ("--at", "HEAD"))
    assert done.returncode == 0, done.stderr
    with tarfile.open(rig.tar) as archive:
        script = archive.getmember("run.sh")
        assert script.mode & 0o111, "the committed mode, 100755"
        assert archive.extractfile(script).read() == b"#!/bin/sh\necho hi\n"
        assert archive.extractfile("a.txt").read() == b"first\n"


def test_git_variables_are_dropped_so_none_points_the_tool_elsewhere(rig: Rig, tmp_path: Path) -> None:
    other = tmp_path / "other"
    other.mkdir()
    _git(other, "init", "-q", "-b", "main")
    _git(other, "-c", "user.name=O", "-c", "user.email=o@example.com", "commit", "-q", "--allow-empty", "-m", "other")
    elsewhere = {"GIT_DIR": (other / ".git").as_posix(), "GIT_WORK_TREE": other.as_posix()}
    done      = _preflight(rig, "ci-lint", env = elsewhere)
    assert done.returncode == 0, done.stderr
    assert _git(rig.repo, "rev-parse", "HEAD") in done.stdout


def test_a_token_in_tracked_content_is_listed_as_a_warning_and_not_refused(rig: Rig) -> None:
    token = "gh" + "p_" + "A" * 36
    _commit(rig.repo, {"docs/notes.md": f"a fixture, {token}\n"}, "a fake token")
    done = _preflight(rig, "ci-lint")
    assert done.returncode == 0, done.stderr
    assert "WARNING" in done.stdout and "docs/notes.md" in done.stdout and token not in done.stdout + done.stderr


# ----------------------------------------------------------------------------------------------------------------------
# how the result is read, and what is left
# ----------------------------------------------------------------------------------------------------------------------
def test_a_red_lane_reads_1_names_it_and_keeps_the_log(rig: Rig) -> None:
    done = _preflight(rig, "ci-lint", "ci-unit-tests", mode = "red")
    assert done.returncode == 1, done.stderr
    assert "ci-lint failed, exit 2" in done.stdout and "ci-unit-tests passed" in done.stdout
    # the failed lane's excerpt from this run's last step, beside its name, and never a line of another run's
    excerpt = done.stdout.split("ci-lint failed, exit 2", 1)[1]
    assert "the last lines of ci-lint" in excerpt and "    the reason ci-lint failed" in excerpt
    assert "another run" not in done.stdout and "the last lines of ci-unit-tests" not in done.stdout
    run, = _left(rig)
    assert (run / "build.log").is_file() and (run / "context" / "repo.tar").is_file()
    assert _calls(rig)[-1][0] == "rmi"


def test_a_python_credential_failure_says_the_run_failed_and_never_skipped(rig: Rig) -> None:
    # git's credential failure now means a pin the scan missed or a ref a mirror lacks, a defect, so the hint says the
    # run failed and names what was mirrored, and never calls it a skipped pre-flight (D-078)
    done = _preflight(rig, "ci-lint", mode = "cred")
    assert done.returncode == 1, done.stdout
    assert "the run failed" in done.stdout and "skipped" not in done.stdout, done.stdout
    assert "mirrored nothing" in done.stdout


def test_marker_lines_ending_in_a_carriage_return_are_read(rig: Rig) -> None:
    assert _preflight(rig, "ci-lint", "actionlint", mode = "crlf").returncode == 0


def test_a_marker_step_named_by_the_dockerfiles_own_words_is_read(rig: Rig) -> None:
    # a BuildKit that names the step by its unexpanded words, $RUN_ID, still opens it with a line no lane can print
    assert _preflight(rig, "ci-lint", "actionlint", mode = "literal").returncode == 0


def test_an_excerpt_or_a_lanes_line_holding_a_result_never_counts_as_one(rig: Rig) -> None:
    # a lane that learns the run id, from a shell above it that keeps it, prints a result or an end marker in its own
    # output, which reaches the log inside an excerpt or as a line of the lanes step, and neither counts (D-072)
    done = _preflight(rig, "ci-lint", "ci-unit-tests", mode = "nested")
    assert done.returncode == 1, done.stderr
    assert "ci-lint failed, exit 2" in done.stdout and "ci-unit-tests passed" in done.stdout


def test_a_reviewer_never_runs_a_preflight(rig: Rig) -> None:
    # the guard refuses a reviewer's docker build, and it runs this script unread, so the script refuses first
    _refused(_preflight(rig, "ci-lint", env = {"KDF_ROLE": "reviewer"}), rig, "reviewer role")


@pytest.mark.parametrize("images, warned", [("sha256:abc", True), ("", False)])
def test_an_image_left_behind_is_said_and_the_result_stands(rig: Rig, images: str, warned: bool) -> None:
    done = _preflight(rig, "ci-lint", env = {"FAKE_RMI": "fail", "FAKE_IMAGES": images})
    assert done.returncode == 0, "the lanes' result stands"
    assert ("may be left behind, docker rmi it by hand" in done.stderr) == warned, done.stderr
    assert not _left(rig)


@pytest.mark.parametrize("mode", ["nomarker", "noend", "partial", "forged", "builderror", "noheader", "lanestep"])
def test_a_run_with_no_whole_result_reads_3_and_keeps_its_folder(rig: Rig, mode: str) -> None:
    done = _preflight(rig, "ci-lint", "ci-unit-tests", mode = mode)
    assert done.returncode == 3 and "could not complete" in done.stderr, done.stderr
    assert "#9" in done.stderr or "#14" in done.stderr, "the log's tail printed"
    assert len(_left(rig)) == 1 and _calls(rig)[-1][0] == "rmi"


def test_a_base_that_will_not_build_reads_3_before_any_lane(rig: Rig) -> None:
    done = _preflight(rig, "ci-lint", mode = "basefail")
    assert done.returncode == 3 and "the base would not build" in done.stderr, done.stderr
    assert [call[0] for call in _calls(rig)] == ["build"] and len(_left(rig)) == 1


def test_a_run_past_its_timeout_reads_3_and_the_next_run_works(rig: Rig) -> None:
    began = time.monotonic()
    done  = _preflight(rig, "ci-lint", extra = ("--timeout", "3"), mode = "hang")
    assert done.returncode == 3 and "timeout of 3 seconds" in done.stderr, done.stderr
    assert time.monotonic() - began < 30 and _calls(rig)[-1][0] == "rmi"
    assert _preflight(rig, "ci-lint").returncode == 0


def test_keep_keeps_a_green_runs_folder(rig: Rig) -> None:
    done = _preflight(rig, "ci-lint", extra = ("--keep",))
    assert done.returncode == 0, done.stderr
    run, = _left(rig)
    assert sorted(path.name for path in (run / "context").iterdir()) == ["Dockerfile", "lanes.sh", "repo.tar"]
    assert str(run.name) in done.stdout


def test_two_runs_take_ids_and_images_of_their_own(rig: Rig) -> None:
    assert _preflight(rig, "ci-lint").returncode == 0 and _preflight(rig, "ci-lint").returncode == 0
    first, second = _run_ids(rig)
    assert first != second
    removed = [call[1] for call in _calls(rig) if call[0] == "rmi"]
    assert removed == [f"kdf-preflight-run:{first}", f"kdf-preflight-run:{second}"]

# ======================================================================================================================
# setup first, the private mirrors and the result (D-078)
# ======================================================================================================================

def _with_setup(rig: Rig) -> None:
    _commit(rig.repo, {"Makefile": SETUP_MAKEFILE}, "setup")


def _setup_arg(rig: Rig) -> str:
    named = [line for line in _logged(rig) if line.startswith("setup [")]
    assert len(named) == 1, named
    return named[0][len("setup ["):-1]


def _pin(repo: str, ref: str) -> str:
    return f"git+https://github.com/Needless2Say/{repo}.git@{ref}"


def _gh_calls(rig: Rig) -> list[str]:
    return [line for line in _logged(rig) if line.startswith("gh ")]


def _handed(rig: Rig) -> list[str]:
    """
    The mirrors the stand in for docker was handed in the context, by name.
    """
    return sorted(path.name for path in rig.mirrors.iterdir()) if rig.mirrors.exists() else []


def _private(rig: Rig, files: dict[str, str], origin: str | None = None) -> dict[str, str]:
    """
    The rig as a clone of a private repo of the owner's, its origin on GitHub and origin/main at the commit that holds
    the files, and the variables that make the stand in for gh confirm both.
    """
    _git(rig.repo, "remote", "add", "origin", origin or f"https://github.com/Needless2Say/{UNDER_TEST}.git")
    _commit(rig.repo, files, "pins")
    head = _git(rig.repo, "rev-parse", "HEAD")
    _git(rig.repo, "update-ref", "refs/remotes/origin/main", head)
    return {"FAKE_GH": "private", "FAKE_GH_COMMITS": head}


@dataclass
class Remote:
    """
    A bare remote of the owner's under the rig's remotes, as GitHub serves one. main has two commits and the tag v1.0.0
    is on the first, side holds a commit outside main and every tag, and wip is a branch in progress.
    """
    path: Path
    main: str
    tag:  str
    side: str
    wip:  str


def _remote(
    rig: Rig,
    name: str,
    first: dict[str, str] | None = None,
    side: dict[str, str] | None = None,
    later: tuple = (),
) -> Remote:
    """
    Make the bare remote, the first commit with these files too, the side commit with these, and each step in later run
    on main after the second commit.
    """
    work = rig.remotes.parent / "remote-work" / name
    work.mkdir(parents = True)
    _git(work, "init", "-q", "-b", "main")
    _git(work, "config", "user.email", "fmt@example.com")
    _git(work, "config", "user.name", "Fmt")
    _git(work, "config", "core.autocrlf", "false")
    _commit(work, {"pkg.txt": "first\n", **(first or {})}, "first")
    _git(work, "tag", "v1.0.0")
    tag = _git(work, "rev-parse", "HEAD")
    _git(work, "checkout", "-q", "-b", "side")
    _commit(work, {"side.txt": "side\n", **(side or {})}, "side")
    side_commit = _git(work, "rev-parse", "HEAD")
    _git(work, "checkout", "-q", "main")
    _commit(work, {"pkg.txt": "second\n"}, "second")
    for step in later:
        step(work)
    main = _git(work, "rev-parse", "HEAD")
    _git(work, "checkout", "-q", "-b", "wip")
    _commit(work, {"wip.txt": "wip\n"}, "wip")
    wip = _git(work, "rev-parse", "HEAD")
    _git(work, "checkout", "-q", "main")
    rig.remotes.mkdir(exist_ok = True)
    path = rig.remotes / f"{name}.git"
    subprocess.run(["git", "clone", "-q", "--bare", str(work), str(path)], check = True, capture_output = True)
    # the remote serves a commit by its id, as GitHub does when CI's fetch script asks for a pinned one
    _git(path, "config", "uploadpack.allowAnySHA1InWant", "true")
    return Remote(path = path, main = main, tag = tag, side = side_commit, wip = wip)


def _secret_added_then_removed(work: Path) -> None:
    _commit(work, {".env.kdf": "X=1\n"}, "a secret")
    _git(work, "rm", "-q", ".env.kdf")
    _git(work, "commit", "-q", "-m", "the secret gone")


def _a_tree_holding_a_secret(work: Path) -> str:
    """
    A tree of the work repo's index with .env.kdf in it, the index left as it was.
    """
    (work / ".env.kdf").write_text("X=1\n", encoding = "utf-8")
    _git(work, "add", ".env.kdf")
    tree = _git(work, "write-tree")
    _git(work, "rm", "-q", "--cached", ".env.kdf")
    (work / ".env.kdf").unlink()
    return tree


def _one_more_tag(work: Path) -> None:
    # v1.1.0 on main's newest commit, beside the first commit's v1.0.0
    _git(work, "tag", "v1.1.0")


def _two_more_tags(work: Path) -> None:
    _git(work, "tag", "v1.1.0")
    _git(work, "tag", "v2.0.0")


def _lightweight_tag_on_a_tree(work: Path) -> None:
    # a tag may name a tree or a blob as well as a commit, and fetching a tag a pin names brings that tree's objects,
    # which no commit's diff names
    _git(work, "tag", "a-tree", _a_tree_holding_a_secret(work))


def _annotated_tag_on_a_tree(work: Path) -> None:
    _git(work, "tag", "-a", "-m", "a tree", "a-tree", _a_tree_holding_a_secret(work))


def _tag_on_a_blob(work: Path) -> None:
    (work / "loose.txt").write_text("X=1\n", encoding = "utf-8")
    blob = _git(work, "hash-object", "-w", "loose.txt")
    (work / "loose.txt").unlink()
    _git(work, "tag", "a-blob", blob)


def _tag_naming_a_tag_naming_a_tree(work: Path) -> None:
    # the inner tag's own ref removed, so the tree is reached through the outer tag's chain alone
    _git(work, "tag", "-a", "-m", "inner", "inner", _a_tree_holding_a_secret(work))
    _git(work, "tag", "-a", "-m", "outer", "outer", "inner")
    _git(work, "tag", "-d", "inner")


def _tag_naming_a_tag_naming_a_commit(work: Path) -> None:
    _git(work, "tag", "-a", "-m", "inner", "inner", "HEAD")
    _git(work, "tag", "-a", "-m", "outer", "outer", "inner")


def _secret_renamed_unchanged(work: Path) -> None:
    _commit(work, {".env.kdf": "X=1\n"}, "a secret")
    _git(work, "mv", ".env.kdf", "notes.txt")
    _git(work, "commit", "-q", "-m", "renamed")


# ----------------------------------------------------------------------------------------------------------------------
# which setup runs
# ----------------------------------------------------------------------------------------------------------------------
def test_the_repos_setup_runs_first_by_default_when_a_make_lane_is_named(rig: Rig) -> None:
    _with_setup(rig)
    done = _preflight(rig, "ci-lint", "actionlint")
    assert done.returncode == 0, done.stderr
    assert _setup_arg(rig) == "setup"
    assert done.stdout.splitlines()[1] == "kdf-preflight: setup first, make setup, then the lanes"
    assert "kdf-preflight: setup passed" in done.stdout and "ci-lint passed" in done.stdout


@pytest.mark.parametrize("lanes, extra, says", [
    (("actionlint",), (), "no setup, actionlint alone needs none"),
    (("ci-lint",), ("--no-setup",), "no setup, --no-setup was given"),
])
def test_no_setup_runs_for_actionlint_alone_or_with_no_setup(
    rig: Rig,
    lanes: tuple[str, ...],
    extra: tuple[str, ...],
    says: str,
) -> None:
    _with_setup(rig)
    done = _preflight(rig, *lanes, extra = extra)
    assert done.returncode == 0, done.stderr
    assert _setup_arg(rig) == "" and done.stdout.splitlines()[1] == f"kdf-preflight: {says}"
    assert "setup passed" not in done.stdout


def test_no_setup_runs_when_the_makefile_has_no_setup_target(rig: Rig) -> None:
    done = _preflight(rig, "ci-lint")
    assert done.returncode == 0, done.stderr
    short = _git(rig.repo, "rev-parse", "HEAD")[:12]
    assert _setup_arg(rig) == ""
    assert done.stdout.splitlines()[1] == f"kdf-preflight: no setup, the Makefile at {short} has no setup target"


def test_setup_names_another_target(rig: Rig) -> None:
    _with_setup(rig)
    done = _preflight(rig, "ci-lint", extra = ("--setup", "install"))
    assert done.returncode == 0, done.stderr
    assert _setup_arg(rig) == "install" and "setup first, make install, then the lanes" in done.stdout


@pytest.mark.parametrize("lanes, extra, says", [
    (("ci-lint",), ("--setup", "install", "--no-setup"), "cannot both be given"),
    (("ci-lint",), ("--no-setup", "--setup", "install"), "cannot both be given"),
    (("ci-lint",), ("--setup", "install", "--setup", "setup"), "--setup is named twice"),
    (("ci-lint",), ("--no-setup", "--no-setup"), "--no-setup is named twice"),
    (("actionlint",), ("--setup", "install"), "--setup needs a make lane"),
    (("actionlint",), ("--no-setup",), "--no-setup needs a make lane"),
    (("ci-lint",), ("--setup",), "--setup needs a value"),
    (("ci-lint",), ("--setup", "missing"), "missing is no target on its own line"),
    (("ci-lint",), ("--setup", "ci-x"), "ci-x is no target on its own line"),
    (("ci-lint",), ("--setup", "ci-version-check"), "ci-version-check"),
    (("ci-lint",), ("--setup", "ci-deploy-prod"), "the owner's"),
    (("ci-lint",), ("--setup", "release-notes"), "the owner's"),
    (("ci-lint",), ("--setup", "ci-lint"), "named as a lane too"),
    (("ci-lint",), ("--setup", "-x"), "no plain make target"),
    (("ci-lint",), ("--setup", "Setup"), "no plain make target"),
    (("ci-lint",), ("--setup", "set up"), "no plain make target"),
    (("ci-lint",), ("--setup", "a;b"), "no plain make target"),
])
def test_a_setup_that_is_not_the_sessions_to_run_is_refused(
    rig: Rig,
    lanes: tuple[str, ...],
    extra: tuple[str, ...],
    says: str,
) -> None:
    _with_setup(rig)
    _refused(_preflight(rig, *lanes, extra = extra), rig, says)


# ----------------------------------------------------------------------------------------------------------------------
# which repos are mirrored, and whether any are
# ----------------------------------------------------------------------------------------------------------------------
@pytest.mark.parametrize("name", sorted(PIN_FILES))
def test_the_scan_finds_a_pin_in_each_of_the_seven_files_and_mirrors_it(rig: Rig, name: str) -> None:
    remote = _remote(rig, FMT)
    env    = _private(rig, {name: PIN_FILES[name].format(pin = _pin(FMT, "main"))})
    done   = _preflight(rig, "ci-lint", env = env)
    assert done.returncode == 0, done.stderr
    assert _handed(rig) == [f"{FMT}.git"]
    assert f"kdf-preflight: {UNDER_TEST} is private on GitHub, so its private packages are served" in done.stdout
    # each mirror's cost said, the tags a pin names, none here, its size and its seconds
    said = rf"^kdf-preflight: mirroring {FMT}, main at {remote.main}, no tag, \d+ KiB fetched and screened in \d+"
    said += r" seconds$"
    assert re.search(said, done.stdout, re.M), done.stdout


@pytest.mark.parametrize("files", [
    {"Makefile": SETUP_MAKEFILE + "ci-style:\n\tpip install 'kdf-fmt @ {pin}'\n"},
    {"docs/requirements.txt": "kdf-fmt @ {pin}\n"},
    {"requirements/extra.txt": "kdf-fmt @ {pin}\n"},
    {"requirements.txt": "-r requirements/extra.txt\n", "requirements/extra.txt": "kdf-fmt @ {pin}\n"},
    {"requirements-dev.in": "# kdf-fmt @ {pin}\n"},
    {"requirements-dev.in": "    # kdf-fmt @ {pin}\n"},
    {"requirements-dev.in": "pytest==9.1.1  # kdf-fmt @ {pin}\n"},
    {"requirements.txt": "-r extra.txt\n", "extra.txt": f"x @ {_pin('not-a-repo', 'main')}\n"},
])
def test_a_pin_the_scan_does_not_read_is_not_mirrored(rig: Rig, files: dict[str, str]) -> None:
    # the Makefile, another file, an include and a comment are not read, so their pin is not fetched, and in the
    # container it fails at once, since git there asks for no login (D-078)
    _remote(rig, FMT)
    env  = _private(rig, {name: text.format(pin = _pin(FMT, "main")) for name, text in files.items()})
    done = _preflight(rig, "ci-lint", env = env)
    assert done.returncode == 0, done.stderr
    assert _handed(rig) == [] and "mirroring" not in done.stdout


def test_the_allowlist_is_read_as_cis_and_a_repo_off_it_is_refused(rig: Rig) -> None:
    # every repo on CI's allowlist passes the allowlist and meets the admission, here a repo with no origin, and any
    # other is refused, so the wrapper reads exactly the module's ALLOWLIST (D-078)
    for repo in sorted(fpp.ALLOWLIST):
        _commit(rig.repo, {"requirements.txt": f"x @ {_pin(repo, 'main')}\n"}, repo)
        done = _preflight(rig, "ci-lint")
        assert done.returncode == 2 and "is unknown" in done.stderr, done.stderr
        assert "not on CI's allowlist" not in done.stderr, done.stderr
    for repo in ("not-a-repo", "kriegerdataforge-fmt-x", "Kriegerdataforge-fmt"):
        _commit(rig.repo, {"requirements.txt": f"x @ {_pin(repo, 'main')}\n"}, repo)
        _refused(_preflight(rig, "ci-lint"), rig, f"pins Needless2Say/{repo}, which is not on CI's allowlist")


@pytest.mark.parametrize("script", BROKEN_ALLOWLISTS)
def test_an_allowlist_that_cannot_be_read_reads_3(rig: Rig, tmp_path: Path, script: str | None) -> None:
    # the wrapper reads CI's allowlist from the clone it runs from, so a copy of the tool beside a broken script
    tools = tmp_path / "copy" / "tools" / "claude-code"
    shutil.copytree(PREFLIGHT, tools / "preflight")
    shutil.copy(TOOL, tools / "kdf-preflight.sh")
    (tmp_path / "copy" / "scripts").mkdir()
    if script is not None:
        (tmp_path / "copy" / "scripts" / "fetch_private_packages.py").write_text(script, encoding = "utf-8")
    _commit(rig.repo, {"requirements.txt": f"x @ {_pin(FMT, 'main')}\n"}, "a pin")
    environment = {key: value for key, value in os.environ.items() if not key.startswith("GIT_")}
    environment.update({
        "KDF_DOCKER_BIN": rig.fake.as_posix(),
        "KDF_GH_BIN": rig.gh.as_posix(),
        "KDF_PREFLIGHT_DIR": rig.runs.as_posix(),
        "HOME": rig.home.as_posix(),
        "USERPROFILE": str(rig.home),
        "FAKE_LOG": rig.log.as_posix(),
    })
    done = subprocess.run(
        [str(BASH), str(tools / "kdf-preflight.sh"), "--repo", rig.repo.as_posix(), "--lane", "ci-lint"],
        capture_output = True,
        text = True,
        env = environment,
        timeout = 120,
    )
    assert done.returncode == 3 and "allowlist could not be read" in done.stderr, done.stderr
    assert not _calls(rig) and not _gh_calls(rig)


def test_the_wrappers_pin_pattern_finds_what_cis_pin_finds(tmp_path: Path) -> None:
    # the wrapper's pattern is CI's PIN as an extended regular expression, held to it on the same samples (D-078)
    if shutil.which("grep") is None and not os.environ.get("CI"):
        pytest.skip("the pattern runs in grep")
    raw = re.search(r'^pin_pattern="((?:[^"\\]|\\.)*)"$', TOOL.read_text(encoding = "utf-8"), re.M)
    assert raw, "the wrapper names its pattern in pin_pattern"
    # the pattern goes to grep in a file, since Windows' command line would reshape its quotes on the way
    patterns = tmp_path / "pattern.txt"
    patterns.write_text(re.sub(r'\\([\\"$`])', r"\1", raw.group(1)) + "\n", encoding = "utf-8", newline = "\n")
    samples = tmp_path / "samples.txt"
    samples.write_text("\n".join(PIN_SAMPLES) + "\n", encoding = "utf-8", newline = "\n")
    found = subprocess.run(
        ["grep", "-o", "-E", "-f", str(patterns), str(samples)],
        capture_output = True,
        text = True,
    ).stdout.splitlines()
    assert found == [match.group(0) for line in PIN_SAMPLES for match in fpp.PIN.finditer(line)]
    assert len(found) == 9


# ----------------------------------------------------------------------------------------------------------------------
# the admission, nothing private mirrored unless GitHub says the repo is private and holds the commit's base
# ----------------------------------------------------------------------------------------------------------------------
def test_a_repo_github_calls_public_mirrors_nothing_and_says_so(rig: Rig) -> None:
    # even for a commit that adds a pin to the hub, whose history a public repo's commit could otherwise reach
    _remote(rig, FMT)
    env  = _private(rig, {**FMT_PIN, "requirements.txt": f"hub @ {_pin('kriegerdataforge', 'main')}\n"})
    done = _preflight(rig, "ci-lint", env = {**env, "FAKE_GH": "public"})
    assert done.returncode == 0, done.stderr
    assert _handed(rig) == [] and "mirroring" not in done.stdout
    assert f"kdf-preflight: {UNDER_TEST} is public on GitHub, so nothing private is served" in done.stdout
    assert _gh_calls(rig) == [f"gh api repos/Needless2Say/{UNDER_TEST} --jq .private"]


@pytest.mark.parametrize("origins", [
    [],
    [f"https://github.com/Needless2Say/{UNDER_TEST}.git", f"https://github.com/Needless2Say/{FMT}.git"],
    [f"https://github.com/someone/{UNDER_TEST}.git"],
    [f"https://gitlab.com/Needless2Say/{UNDER_TEST}.git"],
    [f"https://github.com/Needless2Say/{UNDER_TEST}/"],
    [f"git@github.com:needless2say/{UNDER_TEST}.git"],
])
def test_a_repo_whose_origin_cannot_name_it_on_github_is_refused_before_any_fetch(rig: Rig, origins: list[str]) -> None:
    _remote(rig, FMT)
    for origin in origins:
        _git(rig.repo, "config", "--add", "remote.origin.url", origin)
    _commit(rig.repo, FMT_PIN, "pins")
    _refused(
        _preflight(rig, "ci-lint", env = {"FAKE_GH_COMMITS": _git(rig.repo, "rev-parse", "HEAD")}),
        rig,
        "is unknown",
    )
    assert not _gh_calls(rig)


@pytest.mark.parametrize("origin", [
    f"git@github.com:Needless2Say/{UNDER_TEST}.git",
    f"ssh://git@github.com/Needless2Say/{UNDER_TEST}",
    f"https://github.com/Needless2Say/{UNDER_TEST}",
])
def test_an_ssh_or_bare_origin_names_the_same_repo(rig: Rig, origin: str) -> None:
    _remote(rig, FMT)
    done = _preflight(rig, "ci-lint", env = _private(rig, FMT_PIN, origin = origin))
    assert done.returncode == 0, done.stderr
    assert _handed(rig) == [f"{FMT}.git"]
    assert _gh_calls(rig)[0] == f"gh api repos/Needless2Say/{UNDER_TEST} --jq .private"


def test_an_unpushed_commit_on_mains_history_is_mirrored_by_the_base_github_holds(rig: Rig) -> None:
    _remote(rig, FMT)
    env  = _private(rig, FMT_PIN)
    base = env["FAKE_GH_COMMITS"]
    _commit(rig.repo, {"c.txt": "unpushed\n"}, "unpushed")
    done = _preflight(rig, "ci-lint", env = env)
    assert done.returncode == 0, done.stderr
    assert _handed(rig) == [f"{FMT}.git"]
    assert f"gh api repos/Needless2Say/{UNDER_TEST}/commits/{base} --jq .sha" in _gh_calls(rig)


def test_a_foreign_commit_with_no_shared_history_is_refused_before_any_fetch(rig: Rig) -> None:
    _remote(rig, FMT)
    env = _private(rig, FMT_PIN)
    _git(rig.repo, "checkout", "-q", "--orphan", "foreign")
    _commit(rig.repo, {"x.txt": "foreign\n"}, "foreign")
    foreign = _git(rig.repo, "rev-parse", "HEAD")
    _git(rig.repo, "checkout", "-q", "main")
    done = _preflight(rig, "ci-lint", extra = ("--at", foreign), env = env)
    _refused(done, rig, "shares no history with origin/main")


def test_a_base_github_does_not_hold_or_no_origin_main_is_refused(rig: Rig) -> None:
    _remote(rig, FMT)
    env = _private(rig, FMT_PIN)
    _refused(_preflight(rig, "ci-lint", env = {**env, "FAKE_GH_COMMITS": "0" * 40}), rig, "GitHub does not hold")
    rig.log.unlink()
    _git(rig.repo, "update-ref", "-d", "refs/remotes/origin/main")
    _refused(_preflight(rig, "ci-lint", env = env), rig, "no origin/main")


def test_github_names_a_fresh_repo_and_its_commit_must_be_githubs(rig: Rig) -> None:
    _remote(rig, FMT)
    _commit(rig.repo, FMT_PIN, "pins")
    head = _git(rig.repo, "rev-parse", "HEAD")
    done = _preflight(rig, "ci-lint", extra = ("--github", UNDER_TEST), env = {"FAKE_GH_COMMITS": head})
    assert done.returncode == 0, done.stderr
    assert _handed(rig) == [f"{FMT}.git"]
    assert f"gh api repos/Needless2Say/{UNDER_TEST}/commits/{head} --jq .sha" in _gh_calls(rig)
    rig.log.unlink()
    _refused(_preflight(rig, "ci-lint", extra = ("--github", UNDER_TEST)), rig, "GitHub does not hold")


@pytest.mark.parametrize("extra, says", [
    (("--github", UNDER_TEST, "--github", UNDER_TEST), "--github is named twice"),
    (("--github", "a/b"), "no repo name"),
    (("--github", ".."), "no repo name"),
    (("--github",), "--github needs a value"),
])
def test_a_github_name_that_cannot_be_a_repo_is_refused(rig: Rig, extra: tuple[str, ...], says: str) -> None:
    _refused(_preflight(rig, "ci-lint", extra = extra), rig, says)


def test_github_beside_an_origin_is_refused(rig: Rig) -> None:
    env = _private(rig, FMT_PIN)
    _refused(_preflight(rig, "ci-lint", extra = ("--github", UNDER_TEST), env = env), rig, "has an origin")


@pytest.mark.parametrize("answer, says", [
    ("signedout", "gh auth login"),
    ("404", "HTTP 404"),
    ("null", "neither true nor false"),
    ("missing", "gh is not on the PATH"),
])
def test_a_visibility_github_cannot_give_reads_3_before_any_fetch(rig: Rig, answer: str, says: str) -> None:
    _remote(rig, FMT)
    env = {**_private(rig, FMT_PIN), "FAKE_GH": answer}
    if answer == "missing":
        env["KDF_GH_BIN"] = (rig.home / "no-such-gh").as_posix()
    done = _preflight(rig, "ci-lint", env = env)
    assert done.returncode == 3 and says in done.stderr, done.stderr
    assert not _calls(rig) and not _left(rig), "nothing fetched, built or kept"


def test_no_pin_and_no_origin_asks_github_nothing(rig: Rig) -> None:
    done = _preflight(rig, "ci-lint")
    assert done.returncode == 0, done.stderr
    assert not _gh_calls(rig) and "GitHub" not in done.stdout


def test_no_pin_with_a_public_origin_says_public_and_a_credential_failure_gets_the_public_hint(rig: Rig) -> None:
    env  = {**_private(rig, {"c.txt": "no pin\n"}), "FAKE_GH": "public"}
    done = _preflight(rig, "ci-lint", mode = "cred", env = env)
    assert done.returncode == 1, done.stderr
    assert f"kdf-preflight: {UNDER_TEST} is public on GitHub, so nothing private is served" in done.stdout
    assert "runs on the host" in done.stdout and "the run failed" not in done.stdout
    assert _gh_calls(rig) == [f"gh api repos/Needless2Say/{UNDER_TEST} --jq .private"], "no base is asked"


def test_no_pin_and_a_visibility_github_cannot_give_is_said_and_the_run_goes_on(rig: Rig) -> None:
    env  = {**_private(rig, {"c.txt": "no pin\n"}), "FAKE_GH": "404"}
    done = _preflight(rig, "ci-lint", env = env)
    assert done.returncode == 0, done.stderr
    assert f"whether {UNDER_TEST} is private on GitHub could not be read" in done.stdout


# ----------------------------------------------------------------------------------------------------------------------
# how a mirror is made, and what of it enters
# ----------------------------------------------------------------------------------------------------------------------
def _clone_as_pip(mirror: Path, repo: str, destination: Path) -> None:
    """
    Clone a mirror through CI's rewrite of the repo's https URL, as pip clones, with a filter and no login.
    """
    url = f"https://github.com/Needless2Say/{repo}.git"
    env = {key: value for key, value in os.environ.items() if not key.startswith("GIT_")}
    env.update({
        "GIT_CONFIG_COUNT": "1",
        "GIT_CONFIG_KEY_0": f"url.{mirror.as_uri()}.insteadOf",
        "GIT_CONFIG_VALUE_0": url,
        "GIT_TERMINAL_PROMPT": "0",
    })
    subprocess.run(
        ["git", "clone", "-q", "--filter=blob:none", url, str(destination)],
        check = True,
        capture_output = True,
        env = env,
    )


def test_a_mirror_enters_as_its_parts_alone_and_serves_main_a_tag_and_a_pinned_commit(rig: Rig, tmp_path: Path) -> None:
    remote = _remote(rig, FMT)
    pins   = f"kdf-fmt @ {_pin(FMT, 'main')}\nold @ {_pin(FMT, 'v1.0.0')}\nside @ {_pin(FMT, remote.side)}\n"
    done   = _preflight(rig, "ci-lint", env = _private(rig, {"requirements-dev.in": pins}))
    assert done.returncode == 0, done.stderr
    mirror = rig.mirrors / f"{FMT}.git"
    assert {"HEAD", "config", "objects", "refs"} <= {path.name for path in mirror.iterdir()} <= {
        "HEAD",
        "config",
        "objects",
        "refs",
        "packed-refs",
    }, "no FETCH_HEAD, hooks, info or description"
    assert (mirror / "config").read_text(encoding = "utf-8") == "[core]\n\trepositoryformatversion = 0\n\tbare = true\n"
    for path in mirror.rglob("*"):
        if path.is_file() and "objects" not in path.relative_to(mirror).parts:
            assert "url" not in path.read_text(encoding = "utf-8", errors = "replace"), path
    assert not [path for path in mirror.rglob("*") if path.name.endswith(".sample")]
    assert _git(mirror, "rev-parse", "--is-bare-repository") == "true"
    refs = _git(mirror, "for-each-ref", "--format=%(refname) %(objectname)").splitlines()
    assert sorted(refs) == sorted([
        f"refs/heads/main {remote.main}",
        f"refs/heads/kdf-pin-{remote.side[:12]} {remote.side}",
        f"refs/tags/v1.0.0 {remote.tag}",
    ]), "main, the tag a pin names and the pinned commit, and never a branch in progress"
    clone = tmp_path / "clone"
    _clone_as_pip(mirror, FMT, clone)
    for ref, commit in (("main", remote.main), ("v1.0.0", remote.tag), (remote.side, remote.side)):
        _git(clone, "checkout", "-q", ref)
        assert _git(clone, "rev-parse", "HEAD") == commit
    assert not (rig.runs.exists() and list(rig.runs.rglob("mirrors"))), "the mirrors removed when the run ends"


def _hostile_home(rig: Rig, tmp_path: Path, whole: bool = False) -> Path:
    """
    A global git configuration that would shape a mirror, run a hook during its fetch, send it elsewhere and weaken
    TLS, if the wrapper let it. Returns the file a hook writes when it runs.
    """
    template = tmp_path / "hostile-template"
    (template / "hooks").mkdir(parents = True)
    (template / "evil.txt").write_text("from the template\n", encoding = "utf-8")
    (template / "hooks" / "pre-receive").write_text("#!/bin/sh\nexit 0\n", encoding = "utf-8")
    ran   = tmp_path / "hook-ran.txt"
    hooks = tmp_path / "hostile-hooks"
    hooks.mkdir()
    _program(hooks / "reference-transaction", f"#!/bin/sh\necho ran >> '{ran.as_posix()}'\n")
    other = tmp_path / "other-remotes"
    base  = rig.remotes.as_uri()
    lines = [
        "[init]",
        f"\ttemplateDir = {template.as_posix()}",
        "\tdefaultRefFormat = reftable",
        "\tdefaultObjectFormat = sha256",
        "[core]",
        f"\thooksPath = {hooks.as_posix()}",
        f'[url "{other.as_uri()}/"]',
        f"\tinsteadOf = {base}/",
        "[http]",
        "\tsslVerify = false",
        '[http "https://github.com/"]',
        "\tsslVerify = false",
        "[log]",
        "\tshowRoot = false",
    ]
    if whole:
        lines += [f'[url "{other.as_uri()}/{FMT}.git"]', f"\tinsteadOf = {base}/{FMT}.git"]
    (rig.home / ".gitconfig").write_text("\n".join(lines) + "\n", encoding = "utf-8")
    return ran


def test_the_hosts_git_settings_never_shape_a_mirror_or_run_during_its_fetch(rig: Rig, tmp_path: Path) -> None:
    remote = _remote(rig, FMT)
    ran    = _hostile_home(rig, tmp_path)
    done   = _preflight(rig, "ci-lint", env = _private(rig, FMT_PIN))
    assert done.returncode == 0, done.stderr
    assert not ran.exists(), "no hook of the host's ran"
    mirror = rig.mirrors / f"{FMT}.git"
    assert not list(mirror.rglob("evil.txt")) and not (mirror / "hooks").exists() and not (mirror / "reftable").exists()
    assert _git(mirror, "rev-parse", "refs/heads/main") == remote.main, "the fetch reached the remote as written"
    assert _git(mirror, "rev-parse", "--show-object-format") == "sha1"
    assert (mirror / "refs" / "heads").is_dir() or (mirror / "packed-refs").is_file()


def test_a_host_rewrite_of_the_whole_url_is_refused_before_any_fetch(rig: Rig, tmp_path: Path) -> None:
    _remote(rig, FMT)
    _hostile_home(rig, tmp_path, whole = True)
    _refused(_preflight(rig, "ci-lint", env = _private(rig, FMT_PIN)), rig, f"the fetch of {FMT} would go to")


def test_the_wrapper_checks_each_fetchs_url_and_tls_and_turns_prompts_off() -> None:
    # git asks an askpass program before it reads the prompt switch, so both are off, and no host setting can reach a
    # weakened TLS check past the wrapper's most specific one, so its refusal is held by its text (D-078)
    text = TOOL.read_text(encoding = "utf-8")
    for words in (
        "GIT_TERMINAL_PROMPT=0",
        "GCM_INTERACTIVE=never",
        "core.askPass=",
        "unset SSH_ASKPASS",
        "ls-remote --get-url",
        "--get-urlmatch http.sslVerify",
        "would not check TLS",
        "--template=",
        "core.hooksPath=",
        "--object-format=sha1",
        "init.defaultRefFormat=files",
        "--no-auto-maintenance",
        "gc.auto=0",
        "maintenance.auto=false",
    ):
        assert words in text, words


@pytest.mark.parametrize("case", ["main", "renamed", "side", "root"])
def test_a_secret_files_name_anywhere_in_a_mirrors_history_is_refused_before_docker(
    rig: Rig,
    tmp_path: Path,
    case: str,
) -> None:
    if case == "main":
        _remote(rig, FMT, later = (_secret_added_then_removed,))
        says, pins = ".env.kdf", FMT_PIN
    elif case == "renamed":
        _remote(rig, FMT, later = (_secret_renamed_unchanged,))
        says, pins = ".env.kdf", FMT_PIN
    elif case == "side":
        remote = _remote(rig, FMT, side = {"config/.env.local": "X=1\n"})
        says, pins = "config/.env.local", {"requirements-dev.in": f"x @ {_pin(FMT, remote.side)}\n"}
    else:
        _hostile_home(rig, tmp_path)
        _remote(rig, FMT, first = {"deploy/id_ed25519": "key\n"})
        says, pins = "deploy/id_ed25519", FMT_PIN
    done = _preflight(rig, "ci-lint", env = _private(rig, pins))
    _refused(done, rig, f"{FMT}'s history holds {says}, named like a secret file")


@pytest.mark.parametrize("tags, ref", [
    (_lightweight_tag_on_a_tree, "refs/tags/a-tree"),
    (_annotated_tag_on_a_tree, "refs/tags/a-tree"),
    (_tag_on_a_blob, "refs/tags/a-blob"),
    (_tag_naming_a_tag_naming_a_tree, "refs/tags/outer"),
])
def test_a_mirror_ref_that_names_no_commit_is_refused_before_docker(rig: Rig, tags, ref: str) -> None:
    # the screen walks commits alone and the copy takes every object, so a ref resolved whole by ^{commit} to no commit
    # refuses the run, through any chain of tags, before the screen and the copy (D-078). A pin names the tag, since a
    # mirror takes only the tags a pin names (D-087)
    _remote(rig, FMT, later = (tags,))
    pins = {"requirements-dev.in": f"kdf-fmt @ {_pin(FMT, 'main')}\nx @ {_pin(FMT, ref.removeprefix('refs/tags/'))}\n"}
    done = _preflight(rig, "ci-lint", env = _private(rig, pins))
    _refused(done, rig, f"the mirror of {FMT} holds {ref}, which names no commit")
    assert _handed(rig) == []


def test_a_tag_naming_a_tag_naming_a_commit_is_mirrored(rig: Rig) -> None:
    _remote(rig, FMT, later = (_tag_naming_a_tag_naming_a_commit,))
    pins = "".join(f"x @ {_pin(FMT, tag)}\n" for tag in ("inner", "outer", "v1.0.0"))
    done = _preflight(rig, "ci-lint", env = _private(rig, {"requirements-dev.in": pins}))
    assert done.returncode == 0, done.stderr
    tags = _git(rig.mirrors / f"{FMT}.git", "for-each-ref", "--format=%(refname)", "refs/tags/").splitlines()
    assert sorted(tags) == ["refs/tags/inner", "refs/tags/outer", "refs/tags/v1.0.0"]


def test_a_commit_that_pins_a_private_repo_its_base_does_not_is_refused_before_any_fetch(rig: Rig) -> None:
    # a commit built on a confirmed base gets only the private repos that base already pins, so a commit made on a
    # known id of a private main reaches no other private history (D-078)
    _remote(rig, FMT)
    env = _private(rig, FMT_PIN)
    hub = f"hub @ {_pin('kriegerdataforge', 'main')}\n"
    _commit(rig.repo, {"requirements.txt": hub}, "a hub pin its base does not hold")
    base = env["FAKE_GH_COMMITS"]
    done = _preflight(rig, "ci-lint", env = env)
    _refused(done, rig, f"pins Needless2Say/kriegerdataforge, which its base {base}")
    assert _handed(rig) == [] and not done.stdout, "refused before the run's folder, so before any fetch"


def test_the_base_is_held_to_the_repos_it_pins_and_not_to_its_pins_text(rig: Rig) -> None:
    # a ref may hold any text a pin's ref allows, another repo's URL among it, so the base's pins are read as repos,
    # as the commit's are (D-078)
    _remote(rig, FMT)
    odd = f"kdf-fmt @ {_pin(FMT, 'x/github.com/Needless2Say/kriegerdataforge.git@main')}\n"
    env = _private(rig, {"requirements-dev.in": odd})
    _commit(rig.repo, {"requirements.txt": f"hub @ {_pin('kriegerdataforge', 'main')}\n"}, "a hub pin")
    done = _preflight(rig, "ci-lint", env = env)
    _refused(done, rig, "pins Needless2Say/kriegerdataforge, which its base")
    assert not done.stdout


def test_a_public_repo_of_the_allowlist_is_not_held_to_the_base(rig: Rig) -> None:
    # the limit holds back private history alone, and the allowlist marks this repo's own stand in public
    _remote(rig, FMT)
    _remote(rig, "kriegerdataforge-cicd")
    env = _private(rig, FMT_PIN)
    _commit(rig.repo, {"requirements.txt": f"x @ {_pin('kriegerdataforge-cicd', 'main')}\n"}, "a public pin")
    done = _preflight(rig, "ci-lint", env = env)
    assert done.returncode == 0, done.stderr
    assert _handed(rig) == ["kriegerdataforge-cicd.git", f"{FMT}.git"]


def test_a_base_github_cannot_answer_for_reads_3(rig: Rig) -> None:
    # gh's 422 alone says GitHub does not hold the base, and any other failure is an answer it could not give
    _remote(rig, FMT)
    done = _preflight(rig, "ci-lint", env = {**_private(rig, FMT_PIN), "FAKE_GH_COMMIT": "error"})
    assert done.returncode == 3 and "could not say whether GitHub holds" in done.stderr, done.stderr
    assert "HTTP 500" in done.stderr and not _calls(rig) and not _left(rig)


def test_a_fetch_that_fails_reads_3_names_the_repo_and_keeps_the_run_but_its_mirrors(rig: Rig) -> None:
    # fmt is fetched first and the SDK's has no remote, so one mirror was made before the other failed
    _remote(rig, FMT)
    pins = {"requirements-dev.in": f"kdf-fmt @ {_pin(FMT, 'main')}\nsdk @ {_pin(SDK, 'v1.0.0')}\n"}
    done = _preflight(rig, "ci-lint", env = _private(rig, pins))
    assert done.returncode == 3 and f"the fetch of {SDK} failed" in done.stderr, done.stderr
    assert "does not appear to be a git repository" in done.stderr, "git's own reason"
    assert "signs git in to GitHub" in done.stderr and not _calls(rig)
    run, = _left(rig)
    assert not (run / "mirrors").exists() and not (run / "context" / "mirrors").exists()


def test_a_fetch_error_naming_a_url_with_a_user_part_is_redacted(rig: Rig, tmp_path: Path) -> None:
    _remote(rig, FMT)
    programs = tmp_path / "bin"
    programs.mkdir()
    _program(programs / "git", FAKE_GIT)
    path = f"{programs.as_posix()}{os.pathsep}{os.environ['PATH']}"
    env  = {**_private(rig, FMT_PIN), "PATH": path, "REAL_GIT": Path(str(GIT)).as_posix()}
    done = _preflight(rig, "ci-lint", env = env)
    assert done.returncode == 3, done.stderr
    assert "https://***@github.com/" in done.stderr and "s3cr3t-value" not in done.stderr + done.stdout
    run, = _left(rig)
    assert "s3cr3t-value" not in (run / "build.log").read_text(encoding = "utf-8")


@pytest.mark.parametrize("mode, extra, code", [
    ("pass", ("--keep",), 0),
    ("red", (), 1),
    ("nomarker", (), 3),
])
def test_the_mirrors_are_removed_whatever_the_run_ends_with(
    rig: Rig,
    mode: str,
    extra: tuple[str, ...],
    code: int,
) -> None:
    _remote(rig, FMT)
    done = _preflight(rig, "ci-lint", extra = extra, mode = mode, env = _private(rig, FMT_PIN))
    assert done.returncode == code, done.stderr
    assert _handed(rig) == [f"{FMT}.git"], "the build was handed the mirror"
    run, = _left(rig)
    assert not (run / "mirrors").exists() and not (run / "context" / "mirrors").exists()
    assert (run / "build.log").is_file() and (run / "context" / "repo.tar").is_file()


# ----------------------------------------------------------------------------------------------------------------------
# how the result is read with setup
# ----------------------------------------------------------------------------------------------------------------------
def test_a_red_setup_reads_1_with_its_excerpt_and_each_make_lane_not_run(rig: Rig) -> None:
    _with_setup(rig)
    done = _preflight(rig, "ci-lint", "ci-unit-tests", "actionlint", env = {"FAKE_SETUP": "2"})
    assert done.returncode == 1, done.stderr
    lines = done.stdout.splitlines()
    red   = lines.index("kdf-preflight: setup failed, exit 2")
    assert lines[red + 1] == "kdf-preflight: the last lines of setup, an excerpt of its own output"
    assert lines[red + 2] == "    the reason setup failed"
    assert "kdf-preflight: ci-lint not run, setup failed" in lines
    assert "kdf-preflight: ci-unit-tests not run, setup failed" in lines
    assert "kdf-preflight: actionlint passed" in lines and "ci-lint passed" not in done.stdout


def test_a_setup_past_its_time_is_said_so(rig: Rig) -> None:
    _with_setup(rig)
    done = _preflight(rig, "ci-lint", env = {"FAKE_SETUP": "124"})
    assert done.returncode == 1 and "setup failed, it ran out of its time inside the container" in done.stdout


@pytest.mark.parametrize("mode, lanes, setup, says", [
    ("setupmissing", ("ci-lint",), True, "no single setup line"),
    ("setupextra", ("actionlint",), True, "a setup line where none was due"),
    ("setupextra", ("ci-lint",), False, "a setup line where none was due"),
    ("setupother", ("ci-lint",), True, "names other"),
    ("setuptwice", ("ci-lint",), True, "no single setup line"),
    ("setupmalformed", ("ci-lint",), True, "malformed"),
    ("contrasetup", ("ci-lint",), True, "no single setup line"),
    ("lanetwice", ("ci-lint", "actionlint"), True, "two results for ci-lint"),
    ("contralane", ("ci-lint",), True, "two results for ci-lint"),
    ("lanemalformed", ("ci-lint",), True, "malformed"),
    ("laneextra", ("ci-lint",), True, "ci-other, a lane not named"),
    ("skippedgreen", ("ci-lint",), True, "skipped after a green setup"),
    ("skippedgreen", ("ci-lint",), False, "skipped where no setup ran"),
])
def test_a_result_that_does_not_add_up_reads_3(
    rig: Rig,
    mode: str,
    lanes: tuple[str, ...],
    setup: bool,
    says: str,
) -> None:
    if setup:
        _with_setup(rig)
    done = _preflight(rig, *lanes, mode = mode)
    assert done.returncode == 3 and "could not complete" in done.stderr and says in done.stderr, done.stderr
    assert "passed" not in done.stdout


def test_a_number_after_a_red_setup_reads_3(rig: Rig) -> None:
    _with_setup(rig)
    done = _preflight(rig, "ci-lint", mode = "numberred", env = {"FAKE_SETUP": "2"})
    assert done.returncode == 3 and "a result for ci-lint after a red setup" in done.stderr, done.stderr


def test_setups_line_forged_in_a_lanes_output_or_an_excerpt_is_never_read(rig: Rig) -> None:
    _with_setup(rig)
    done = _preflight(rig, "ci-lint", mode = "forgedsetup", env = {"FAKE_SETUP": "2"})
    assert done.returncode == 1 and "setup failed, exit 2" in done.stdout, done.stdout + done.stderr


def test_a_credential_failure_names_the_repos_mirrored_and_says_the_run_failed(rig: Rig) -> None:
    _remote(rig, FMT)
    done = _preflight(rig, "ci-lint", mode = "cred", env = _private(rig, FMT_PIN))
    assert done.returncode == 1, done.stderr
    assert f"mirrored {FMT}" in done.stdout and "the run failed" in done.stdout and "skipped" not in done.stdout


def test_a_401_from_githubs_npm_registry_in_an_unnamed_repo_says_the_run_failed_and_served_none(rig: Rig) -> None:
    # a repo GitHub does not name may be private, so the hint is the private one, a defect and never a skip (D-087)
    done = _preflight(rig, "ci-lint", mode = "npm")
    assert done.returncode == 1, done.stderr
    assert "npm.pkg.github.com" in done.stdout and "the run served no private npm package" in done.stdout
    assert "the run failed" in done.stdout and "skipped" not in done.stdout, done.stdout

# ======================================================================================================================
# the owner's private npm packages, served from this machine's npm cache by the digest each lock names (D-087)
# ======================================================================================================================

@dataclass
class Tarball:
    """
    A package's tarball, its bytes, its sha512 in hex and its integrity as a lock names it.
    """
    data: bytes
    hex:  str
    sri:  str


def _as_tarball(data: bytes) -> Tarball:
    digest = hashlib.sha512(data).digest()
    return Tarball(data = data, hex = digest.hex(), sri = "sha512-" + base64.b64encode(digest).decode("ascii"))


def _manifest(name: str, version: str) -> bytes:
    return json.dumps({"name": name, "version": version}).encode("utf-8")


def _tarball(name: str = WIDGET, version: str = "1.2.3", members: dict[str, bytes] | None = None) -> Tarball:
    """
    A gzipped tar of these members, by default a package.json naming the package and version and one file beside it,
    both under package/, as npm packs a package.
    """
    if members is None:
        members = {"package/package.json": _manifest(name, version), "package/index.js": b"module.exports = 1;\n"}
    buffer = io.BytesIO()
    with tarfile.open(fileobj = buffer, mode = "w:gz") as archive:
        for path, data in members.items():
            info      = tarfile.TarInfo(path)
            info.size = len(data)
            info.mode = 0o644
            archive.addfile(info, io.BytesIO(data))
    return _as_tarball(buffer.getvalue())


def _digest_path(hex_digest: str) -> str:
    """
    Where npm's cache keeps a tarball by its sha512, cacache's content path.
    """
    return f"_cacache/content-v2/sha512/{hex_digest[:2]}/{hex_digest[2:4]}/{hex_digest[4:]}"


def _cached(cache: Path, tarball: Tarball, data: bytes | None = None) -> None:
    """
    Put the tarball, or other bytes in its place, in an npm cache at its digest's path, as a host install leaves it.
    """
    path = _long(cache) / _digest_path(tarball.hex)
    path.parent.mkdir(parents = True, exist_ok = True)
    path.write_bytes(tarball.data if data is None else data)


def _entry(tarball: Tarball, package: str = WIDGET, version: str = "1.2.3", **fields: object) -> dict[str, object]:
    """
    A lock entry resolving the tarball from GitHub's npm registry as npm writes one, any field given in its place.
    """
    entry: dict[str, object] = {
        "version": version,
        "resolved": f"{NPM_HOST}download/{package}/{version}/{tarball.hex}",
        "integrity": tarball.sri,
    }
    entry.update(fields)
    return entry


def _lock(entries: dict[str, dict[str, object]]) -> dict[str, str]:
    """
    A package-lock.json of lockfile version 3, the root package, one public package and these entries by their paths.
    """
    packages = {
        "": {"name": "app", "version": "0.1.0"},
        "node_modules/left-pad": {
            "version": "1.3.0",
            "resolved": "https://registry.npmjs.org/left-pad/-/left-pad-1.3.0.tgz",
            "integrity": _as_tarball(b"left-pad").sri,
        },
        **entries,
    }
    lock     = {"name": "app", "version": "0.1.0", "lockfileVersion": 3, "requires": True, "packages": packages}
    return {"package-lock.json": json.dumps(lock, indent = 2) + "\n"}


def _widget_lock(tarball: Tarball, **fields: object) -> dict[str, str]:
    return _lock({f"node_modules/{WIDGET}": _entry(tarball, **fields)})


def _sha1(tarball: Tarball) -> str:
    return "sha1-" + base64.b64encode(hashlib.sha1(tarball.data).digest()).decode("ascii")


def _served(rig: Rig) -> list[str]:
    """
    The files the stand in for docker was handed under the context's npm folder, by their paths there.
    """
    seen = _long(rig.npm_seen)
    if not seen.exists():
        return []
    return sorted(path.relative_to(seen).as_posix() for path in seen.rglob("*") if path.is_file())


def _git_stand_in(programs: Path, text: str) -> dict[str, str]:
    """
    A stand in for git in a folder of its own, and the variables that put it first and name the real git.
    """
    programs.mkdir(exist_ok = True)
    _program(programs / "git", text)
    return {"PATH": f"{programs.as_posix()}{os.pathsep}{os.environ['PATH']}", "REAL_GIT": Path(str(GIT)).as_posix()}


# ----------------------------------------------------------------------------------------------------------------------
# what is served
# ----------------------------------------------------------------------------------------------------------------------
def test_a_private_repos_locked_npm_package_is_served_by_its_digest_and_nothing_else(rig: Rig) -> None:
    tarball = _tarball()
    _cached(rig.npm_cache, tarball)
    env  = {**_private(rig, _widget_lock(tarball)), "GH_NPM_TOKEN": "kdf-test-token-value"}
    done = _preflight(rig, "ci-lint", env = env)
    assert done.returncode == 0, done.stderr
    assert _served(rig) == [_digest_path(tarball.hex)], "the locked tarball alone, the public package left to npm"
    assert (_long(rig.npm_seen) / _digest_path(tarball.hex)).read_bytes() == tarball.data
    lines = done.stdout.splitlines()
    assert f"kdf-preflight: {UNDER_TEST} is private on GitHub, so its private packages are served" in lines
    assert f"kdf-preflight: serving {WIDGET} 1.2.3 from this machine's npm cache, {len(tarball.data)} bytes" in lines
    contexts = [line.rstrip() for line in _logged(rig) if line.startswith("context ")]
    assert contexts[-1] == "context lanes Dockerfile lanes.sh mirrors npm repo.tar", "nothing else new"
    # no token and no npm setting reaches docker (Round Table 64's L8)
    for call in _calls(rig):
        assert not [word for word in call if re.search(r"GH_NPM_TOKEN|npm_config_|kdf-test-token-value", word, re.I)]
    assert not _left(rig)


def test_a_sha1_beside_the_sha512_and_the_same_tarball_locked_twice_serve_it_once(rig: Rig) -> None:
    # the sha512 taken from among any other hashes the integrity lists (Round Table 64's L16), and a tarball placed once
    tarball = _tarball()
    _cached(rig.npm_cache, tarball)
    entries = {
        f"node_modules/{WIDGET}": _entry(tarball, integrity = f"{_sha1(tarball)} {tarball.sri}"),
        f"node_modules/app-kit/node_modules/{WIDGET}": _entry(tarball),
    }
    done    = _preflight(rig, "ci-lint", env = _private(rig, _lock(entries)))
    assert done.returncode == 0, done.stderr
    assert _served(rig) == [_digest_path(tarball.hex)]
    assert done.stdout.count(f"serving {WIDGET} 1.2.3 ") == 1, done.stdout


def test_an_entrys_package_is_its_name_else_the_path_after_its_last_node_modules(rig: Rig) -> None:
    # an alias keeps the real package in the entry's name, which the tarball's package.json names
    tarball = _tarball()
    _cached(rig.npm_cache, tarball)
    files = _lock({"node_modules/widget": _entry(tarball, name = WIDGET)})
    done  = _preflight(rig, "ci-lint", env = _private(rig, files))
    assert done.returncode == 0, done.stderr
    assert _served(rig) == [_digest_path(tarball.hex)] and f"serving {WIDGET} 1.2.3 " in done.stdout


# ----------------------------------------------------------------------------------------------------------------------
# the fence, the mirrors' own, over pins alone, lock entries alone and both (Round Table 64's L1)
# ----------------------------------------------------------------------------------------------------------------------
def _what(rig: Rig, what: str) -> tuple[dict[str, str], Tarball]:
    """
    The files a commit holds for pins alone, a lock entry alone or both, the lock's tarball in the rig's cache and fmt
    on the rig's remotes.
    """
    _remote(rig, FMT)
    tarball = _tarball()
    _cached(rig.npm_cache, tarball)
    files = {**(FMT_PIN if what != "npm" else {}), **(_widget_lock(tarball) if what != "pins" else {})}
    return files, tarball


@pytest.mark.parametrize("what", ["pins", "npm", "both"])
@pytest.mark.parametrize("case, code, says", [
    ("no origin", 2, "is unknown"),
    ("two origins", 2, "is unknown"),
    ("foreign", 2, "shares no history with origin/main"),
    ("no origin/main", 2, "no origin/main"),
    ("not on GitHub", 2, "GitHub does not hold"),
    ("base unanswered", 3, "could not say whether GitHub holds"),
    ("visibility unknown", 3, "HTTP 404"),
])
def test_a_refused_admission_reads_no_cache_file_and_hands_nothing_to_docker(
    rig: Rig,
    what: str,
    case: str,
    code: int,
    says: str,
) -> None:
    files, _ = _what(rig, what)
    extra: tuple[str, ...] = ()
    if case in ("no origin", "two origins"):
        if case == "two origins":
            for name in (UNDER_TEST, FMT):
                _git(rig.repo, "config", "--add", "remote.origin.url", f"https://github.com/Needless2Say/{name}.git")
        _commit(rig.repo, files, "files")
        env = {"FAKE_GH_COMMITS": _git(rig.repo, "rev-parse", "HEAD")}
    else:
        env = _private(rig, files)
    if case == "foreign":
        _git(rig.repo, "checkout", "-q", "--orphan", "foreign")
        _commit(rig.repo, {"x.txt": "foreign\n"}, "foreign")
        extra = ("--at", _git(rig.repo, "rev-parse", "HEAD"))
        _git(rig.repo, "checkout", "-q", "main")
    elif case == "no origin/main":
        _git(rig.repo, "update-ref", "-d", "refs/remotes/origin/main")
    elif case == "not on GitHub":
        env["FAKE_GH_COMMITS"] = "0" * 40
    elif case == "base unanswered":
        env["FAKE_GH_COMMIT"] = "error"
    elif case == "visibility unknown":
        env["FAKE_GH"] = "404"
    done = _preflight(rig, "ci-lint", extra = extra, env = env)
    assert done.returncode == code and says in done.stderr, done.stderr
    # refused before the run's folder, whose making the first line of stdout follows, so before any cache read
    assert not done.stdout and not _calls(rig) and not _left(rig)
    assert _served(rig) == [] and _handed(rig) == []


@pytest.mark.parametrize("what", ["pins", "npm", "both"])
def test_github_admits_a_fresh_repos_commit_itself_for_pins_lock_entries_and_both(rig: Rig, what: str) -> None:
    files, tarball = _what(rig, what)
    _commit(rig.repo, files, "files")
    head = _git(rig.repo, "rev-parse", "HEAD")
    done = _preflight(rig, "ci-lint", extra = ("--github", UNDER_TEST), env = {"FAKE_GH_COMMITS": head})
    assert done.returncode == 0, done.stderr
    assert _handed(rig) == ([] if what == "npm" else [f"{FMT}.git"])
    assert _served(rig) == ([] if what == "pins" else [_digest_path(tarball.hex)])
    assert f"gh api repos/Needless2Say/{UNDER_TEST}/commits/{head} --jq .sha" in _gh_calls(rig)


def test_a_clones_commit_locking_a_package_its_base_does_not_is_refused_before_any_cache_read(rig: Rig) -> None:
    tarball = _tarball()
    _cached(rig.npm_cache, tarball)
    env  = _private(rig, {"c.txt": "no lock\n"})
    base = env["FAKE_GH_COMMITS"]
    _commit(rig.repo, _widget_lock(tarball), "a lock its base does not hold")
    done = _preflight(rig, "ci-lint", env = env)
    _refused(done, rig, f"locks {WIDGET} from npm.pkg.github.com, which its base {base} on GitHub does not lock")
    assert not done.stdout and _served(rig) == []


def test_a_clones_commit_moving_a_package_its_base_locks_to_another_version_is_served(rig: Rig) -> None:
    old, new = _tarball(version = "1.2.2"), _tarball()
    _cached(rig.npm_cache, new)
    env = _private(rig, _widget_lock(old, version = "1.2.2"))
    _commit(rig.repo, _widget_lock(new), "a new version")
    done = _preflight(rig, "ci-lint", env = env)
    assert done.returncode == 0, done.stderr
    assert _served(rig) == [_digest_path(new.hex)]


# ----------------------------------------------------------------------------------------------------------------------
# the scan's refusals, once GitHub says the repo is private, and nothing served in a public one (Round Table 64's L10)
# ----------------------------------------------------------------------------------------------------------------------
@pytest.mark.parametrize("case, says", [
    ("scope", "@someone/widget from npm.pkg.github.com, outside the owner's scope @needless2say/"),
    ("no sha512", f"{WIDGET} 1.2.3 with no sha512 in its integrity"),
    ("two sha512", f"{WIDGET} 1.2.3 with two different sha512 values in its integrity"),
    ("not json", "is not JSON"),
])
def test_a_lock_the_scan_cannot_serve_is_refused_in_a_private_repo_and_serves_nothing_in_a_public_one(
    rig: Rig,
    case: str,
    says: str,
) -> None:
    tarball = _tarball()
    _cached(rig.npm_cache, tarball)
    if case == "scope":
        files = _lock({"node_modules/@someone/widget": _entry(tarball, package = "@someone/widget")})
    elif case == "no sha512":
        files = _widget_lock(tarball, integrity = _sha1(tarball))
    elif case == "two sha512":
        files = _widget_lock(tarball, integrity = f"{tarball.sri} {_tarball(version = '9.9.9').sri}")
    else:
        files = {"package-lock.json": "{ not json\n"}
    env = _private(rig, files)
    _refused(_preflight(rig, "ci-lint", env = env), rig, says)
    assert _served(rig) == []
    done = _preflight(rig, "ci-lint", env = {**env, "FAKE_GH": "public"})
    assert done.returncode == 0, done.stderr
    assert _served(rig) == [] and "serving" not in done.stdout
    assert f"kdf-preflight: {UNDER_TEST} is public on GitHub, so nothing private is served" in done.stdout


# ----------------------------------------------------------------------------------------------------------------------
# the cache, npm's default folder or the test's, read and never written
# ----------------------------------------------------------------------------------------------------------------------
def test_a_tarball_missing_from_the_cache_is_refused_with_the_fresh_install_before_any_mirror(rig: Rig) -> None:
    _remote(rig, FMT)
    tarball = _tarball()
    done    = _preflight(rig, "ci-lint", env = _private(rig, {**FMT_PIN, **_widget_lock(tarball)}))
    _refused(done, rig, f"{WIDGET} 1.2.3 is not in this machine's npm cache, {rig.npm_cache.as_posix()}")
    assert FRESH_INSTALL in done.stderr, done.stderr
    assert "mirroring" not in done.stdout and _handed(rig) == [] and _served(rig) == []


@pytest.mark.parametrize("where", ["LOCALAPPDATA", "HOME"])
def test_the_cache_is_npms_default_folder_when_no_test_names_one(rig: Rig, where: str) -> None:
    # %LOCALAPPDATA%/npm-cache through cygpath, else $HOME/.npm (Round Table 64's L14)
    tarball = _tarball()
    if where == "LOCALAPPDATA":
        _cached(rig.local / "npm-cache", tarball)
        unset: dict[str, str | None] = {"KDF_NPM_CACHE": None}
    else:
        _cached(rig.home / ".npm", tarball)
        unset = {"KDF_NPM_CACHE": None, "LOCALAPPDATA": None}
    done = _preflight(rig, "ci-lint", env = {**_private(rig, _widget_lock(tarball)), **unset})
    assert done.returncode == 0, done.stderr
    assert _served(rig) == [_digest_path(tarball.hex)]
    asked = [line for line in _logged(rig) if line.startswith("cygpath ")]
    assert asked == ([f"cygpath -u {rig.local}"] if where == "LOCALAPPDATA" else []), asked


# ----------------------------------------------------------------------------------------------------------------------
# what of a tarball enters, judged in the run's own folder (Round Table 64's L15)
# ----------------------------------------------------------------------------------------------------------------------
@pytest.mark.parametrize("case, says", [
    ("hash", f"the tarball of {WIDGET} 1.2.3 in this machine's npm cache does not hash to the sha512 its lock names"),
    ("name", f"a package.json naming @needless2say/other 1.2.3, not {WIDGET} 1.2.3"),
    ("version", f"a package.json naming {WIDGET} 9.9.9, not {WIDGET} 1.2.3"),
    ("env", f"the tarball of {WIDGET} 1.2.3 holds package/.env.kdf, named like a secret file"),
    ("keys", f"the tarball of {WIDGET} 1.2.3 holds package/keys/notes.txt, named like a secret file"),
    ("tops", "holds other/index.js, outside the one top folder package"),
    ("loose", "holds README, outside the one top folder package"),
    ("doubled", "holds package//package.json, outside the one top folder package"),
    ("dash", f"holds {DASH_MEMBER}, whose name begins with a dash, which tar could read as an option"),
    ("listing", f"tar could not list the tarball of {WIDGET} 1.2.3"),
])
def test_bytes_that_do_not_match_their_lock_entry_are_refused_before_docker(rig: Rig, case: str, says: str) -> None:
    manifest = {"package/package.json": _manifest(WIDGET, "1.2.3")}
    if case == "name":
        tarball = _tarball(name = "@needless2say/other")
    elif case == "version":
        tarball = _tarball(version = "9.9.9")
    elif case in ("env", "keys", "tops", "loose", "doubled"):
        stray   = {
            "env": "package/.env.kdf",
            "keys": "package/keys/notes.txt",
            "tops": "other/index.js",
            "doubled": "package//package.json",
        }
        tarball = _tarball(members = {**manifest, stray.get(case, "README"): b"X=1\n"})
    elif case == "listing":
        tarball = _as_tarball(b"not a tarball\n")
    elif case == "dash":
        # a top folder GNU tar would read as an option, which runs a command at a checkpoint (the Codex read of
        # c6daba3), refused before tar is handed any member
        tarball = _tarball(members = {DASH_MEMBER: _manifest(WIDGET, "1.2.3")})
    else:
        tarball = _tarball()
    _cached(rig.npm_cache, tarball, data = _tarball(version = "1.2.4").data if case == "hash" else None)
    done = _preflight(rig, "ci-lint", env = _private(rig, _widget_lock(tarball)))
    _refused(done, rig, says)
    assert _served(rig) == []
    assert not Path(DASH_MARKER).exists() and not (rig.repo / DASH_MARKER).exists(), "no command of a member ran"


# ----------------------------------------------------------------------------------------------------------------------
# the context, read back whole, and the npm folder removed however the run ends (Round Table 64's L11)
# ----------------------------------------------------------------------------------------------------------------------
def test_a_stray_file_in_the_contexts_npm_folder_reads_3_and_nothing_is_built(rig: Rig, tmp_path: Path) -> None:
    # the stand in for git writes the stray as fmt's mirror is fetched, after the tarball was placed
    _remote(rig, FMT)
    tarball = _tarball()
    _cached(rig.npm_cache, tarball)
    env  = {**_private(rig, {**FMT_PIN, **_widget_lock(tarball)}), **_git_stand_in(tmp_path / "bin", STRAY_GIT)}
    done = _preflight(rig, "ci-lint", env = env)
    assert done.returncode == 3, done.stderr
    assert "the context holds npm/stray.txt, which is no tarball this run placed" in done.stderr, done.stderr
    assert not _calls(rig)
    run, = _left(rig)
    assert not (run / "context" / "npm").exists() and not (run / "tarballs").exists()


@pytest.mark.parametrize("mode, extra, code", [
    ("pass", ("--keep",), 0),
    ("red", (), 1),
    ("nomarker", (), 3),
    ("pass", (), 2),
])
def test_the_served_packages_are_removed_whatever_the_run_ends_with(
    rig: Rig,
    mode: str,
    extra: tuple[str, ...],
    code: int,
) -> None:
    tarball = _tarball()
    _cached(rig.npm_cache, tarball)
    entries = {f"node_modules/{WIDGET}": _entry(tarball)}
    if code == 2:
        # a second package after the first, its tarball missing, so the run is refused once the first was placed
        later = "@needless2say/zz-later"
        entries[f"node_modules/{later}"] = _entry(_tarball(name = later), package = later)
    done = _preflight(rig, "ci-lint", extra = extra, mode = mode, env = _private(rig, _lock(entries)))
    assert done.returncode == code, done.stderr
    if code == 2:
        assert "zz-later 1.2.3 is not in this machine's npm cache" in done.stderr, done.stderr
        assert not _left(rig) and not _calls(rig)
        return
    assert _served(rig) == [_digest_path(tarball.hex)], "the build was handed the package"
    run, = _left(rig)
    assert not (run / "context" / "npm").exists() and not (run / "tarballs").exists()
    assert (run / "build.log").is_file() and (run / "context" / "repo.tar").is_file()


# ----------------------------------------------------------------------------------------------------------------------
# the hints and the usage
# ----------------------------------------------------------------------------------------------------------------------
def test_a_served_runs_401_from_githubs_npm_registry_says_the_run_failed_and_names_what_it_served(rig: Rig) -> None:
    # a defect, an entry the scan does not serve, or a lock or .npmrc that sends npm to the registry (Round Table 64's
    # L6)
    tarball = _tarball()
    _cached(rig.npm_cache, tarball)
    done = _preflight(rig, "ci-lint", mode = "npm", env = _private(rig, _widget_lock(tarball)))
    assert done.returncode == 1, done.stderr
    assert f"the run served {WIDGET} 1.2.3" in done.stdout and "the run failed" in done.stdout, done.stdout
    assert "a package.json its lock does not satisfy" in done.stdout and "prefers the network" in done.stdout
    assert "skipped" not in done.stdout


def test_a_public_repos_401_from_githubs_npm_registry_says_the_lane_runs_on_the_host(rig: Rig) -> None:
    tarball = _tarball()
    _cached(rig.npm_cache, tarball)
    env  = {**_private(rig, _widget_lock(tarball)), "FAKE_GH": "public"}
    done = _preflight(rig, "ci-lint", mode = "npm", env = env)
    assert done.returncode == 1, done.stderr
    assert "nothing private is served, and a lane that needs a private npm package runs on the host" in done.stdout
    assert "the run failed" not in done.stdout and "skipped" not in done.stdout


def test_the_usage_names_kdf_npm_cache(rig: Rig) -> None:
    # the words only the new copy prints, which a session checks before it reports a Next.js run (Round Table 64's L4)
    done = _run(rig, "--help")
    assert done.returncode == 0 and "KDF_NPM_CACHE" in done.stdout, done.stdout

# ======================================================================================================================
# the tags a pin names, a mirror's only tags (D-087)
# ======================================================================================================================

def _mirror_tags(rig: Rig) -> list[str]:
    return sorted(_git(rig.mirrors / f"{FMT}.git", "for-each-ref", "--format=%(refname)", "refs/tags/").splitlines())


def test_a_pin_at_a_tag_mirrors_that_tag_alone(rig: Rig) -> None:
    remote = _remote(rig, FMT, later = (_two_more_tags,))
    done   = _preflight(rig, "ci-lint", env = _private(rig, {"requirements-dev.in": f"x @ {_pin(FMT, 'v1.1.0')}\n"}))
    assert done.returncode == 0, done.stderr
    assert _mirror_tags(rig) == ["refs/tags/v1.1.0"], "of v1.0.0, v1.1.0 and v2.0.0, the one a pin names"
    said = rf"^kdf-preflight: mirroring {FMT}, main at {remote.main}, tag v1\.1\.0, \d+ KiB"
    assert re.search(said, done.stdout, re.M), done.stdout


def test_pins_at_main_and_at_a_commit_mirror_no_tag_and_look_up_none(rig: Rig, tmp_path: Path) -> None:
    remote = _remote(rig, FMT, later = (_one_more_tag,))
    pins   = {"requirements-dev.in": f"kdf-fmt @ {_pin(FMT, 'main')}\nside @ {_pin(FMT, remote.side)}\n"}
    calls  = tmp_path / "git-calls.log"
    env    = {**_private(rig, pins), **_git_stand_in(tmp_path / "bin", LOGGING_GIT)}
    done   = _preflight(rig, "ci-lint", env = {**env, "KDF_TEST_GIT_LOG": calls.as_posix()})
    assert done.returncode == 0, done.stderr
    assert _mirror_tags(rig) == [] and f"main at {remote.main}, no tag, " in done.stdout, done.stdout
    logged = calls.read_text(encoding = "utf-8")
    assert " fetch " in logged and "ls-remote --tags" not in logged, "no tag is looked up when no pin names one"


@pytest.mark.parametrize("ref", ["v9.9.9", "v1.*", "refs/tags/v1.0.0"])
def test_a_pin_at_a_ref_no_tag_names_whole_fetches_no_tag(rig: Rig, ref: str) -> None:
    # the name after the tab of a line ls-remote prints must equal refs/tags/<ref> as a whole string, never as a
    # pattern, so a pin at v1.* fetches neither v1.0.0 nor v1.1.0 (Round Table 64's L5)
    _remote(rig, FMT, later = (_one_more_tag,))
    pins = {"requirements-dev.in": f"kdf-fmt @ {_pin(FMT, 'main')}\nold @ {_pin(FMT, ref)}\n"}
    done = _preflight(rig, "ci-lint", env = _private(rig, pins))
    assert done.returncode == 0, done.stderr
    assert _mirror_tags(rig) == [] and ", no tag, " in done.stdout, done.stdout
