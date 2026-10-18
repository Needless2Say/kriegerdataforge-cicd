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

import hashlib
import os
import re
import shutil
import stat
import subprocess
import sys
import tarfile
import time
from dataclasses import dataclass
from pathlib import Path

import pytest

ROOT       = Path(__file__).resolve().parents[2]
TOOLS      = ROOT / "tools" / "claude-code"
TOOL       = TOOLS / "kdf-preflight.sh"
GUARD      = TOOLS / "kdf-guard.js"
PREFLIGHT  = TOOLS / "preflight"
DOCKERFILE = PREFLIGHT / "Dockerfile"
LANES      = PREFLIGHT / "lanes.sh"
CI_YML     = ROOT / ".github" / "workflows" / "ci.yml"
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

# a stand in for docker, it records each call, lists a build's context and plays a build's log as FAKE_MODE says
FAKE = r"""#!/usr/bin/env bash
export LC_ALL=C
echo "call $*" >> "$FAKE_LOG"
case "$1" in
    rmi) [ "${FAKE_RMI:-ok}" = ok ]; exit ;;
    images) [ -z "${FAKE_IMAGES:-}" ] || echo "$FAKE_IMAGES"; exit 0 ;;
    build) ;;
    *) exit 0 ;;
esac
target="" id="" lanes=""
for word in "$@"; do
    case "$word" in
        --target=*) target="${word#--target=}" ;;
        --build-arg=RUN_ID=*) id="${word#--build-arg=RUN_ID=}" ;;
        --build-arg=LANES=*) lanes="${word#--build-arg=LANES=}" ;;
    esac
done
context="${!#}"
echo "context $target $(ls -A "$context" | sort | tr '\n' ' ')" >> "$FAKE_LOG"
mode="${FAKE_MODE:-pass}"
if [ "$target" = base ]; then
    if [ "$mode" = basefail ]; then echo "#5 ERROR: failed to solve" >&2; exit 1; fi
    exit 0
fi
[ -z "${FAKE_TAR:-}" ] || cp "$context/repo.tar" "$FAKE_TAR"
case "$mode" in
    hang) exec sleep 60 ;;
    nomarker) echo "#9 0.1 nothing here" >&2; exit 0 ;;
    builderror) echo "#9 ERROR: no space left on device" >&2; exit 1 ;;
    forged) echo "#14 0.1 KDF-PREFLIGHT-RESULT other ${lanes%% *} 0" >&2
            echo "#14 0.1 KDF-PREFLIGHT-END other" >&2
            exit 0 ;;
    cred) echo "#13 2.0 fatal: could not read Username for 'https://github.com': terminal prompts disabled" >&2 ;;
esac
status=0
case "$mode" in red|cred|nested) status=2 ;; esac
end="\n"
[ "$mode" != crlf ] || end="\r\n"
# BuildKit's own line opening the marker step, its run id written out, or as the Dockerfile names it
named="$id"
[ "$mode" != literal ] || named='$RUN_ID'
step=14
[ "$mode" != lanestep ] || step=13
header='#14 [lanes 5/5] RUN sed "s/^/KDF-PREFLIGHT-RESULT %s /" out/results && echo "KDF-PREFLIGHT-END %s"'
header="$header"'     && bash /opt/kdf/lanes.sh --tails out/results "%s"\n'
[ "$mode" = noheader ] || printf "$header" "$named" "$named" "$named" >&2
first="${lanes%% *}"
for lane in $lanes; do
    printf "#$step 0.1 KDF-PREFLIGHT-RESULT %s %s %s$end" "$id" "$lane" "$status" >&2
    status=0
    [ "$mode" != partial ] || break
done
[ "$mode" = noend ] || printf "#$step 0.2 KDF-PREFLIGHT-END %s$end" "$id" >&2
case "$mode" in red|cred)
    printf "#14 0.3 KDF-PREFLIGHT-TAIL %s %s the reason %s failed$end" "$id" "$first" "$first" >&2
    printf "#14 0.3 KDF-PREFLIGHT-TAIL other %s a line of another run$end" "$first" >&2 ;;
nested)
    printf "#14 0.3 KDF-PREFLIGHT-TAIL %s %s KDF-PREFLIGHT-RESULT %s %s 0$end" "$id" "$first" "$id" "$first" >&2
    printf "#14 0.3 KDF-PREFLIGHT-TAIL %s %s KDF-PREFLIGHT-END %s$end" "$id" "$first" "$id" >&2
    printf "#13 0.4 KDF-PREFLIGHT-RESULT %s %s 0$end" "$id" "$first" >&2 ;;
esac
exit 0
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


def test_node_is_its_official_tarball_checked_against_its_sum() -> None:
    adds = [rest for keyword, rest in _stages()[0] if keyword == "ADD" and "nodejs.org" in rest]
    assert len(adds) == 1, "one ADD of Node in the base stage"
    url = re.search(r"https://nodejs\.org/dist/v(\d+)\.(\d+)\.(\d+)/node-v\1\.\2\.\3-linux-x64\.tar\.gz", adds[0])
    assert url, "Node's own tarball, its version named twice alike"
    assert re.search(r"(^| )--checksum=sha256:[0-9a-f]{64}( |$)", adds[0]), "checked against its SHASUMS256.txt line"
    # the comment names the major and where it was read, so the move to a new runner image is a one line fix
    text = DOCKERFILE.read_text(encoding = "utf-8")
    assert re.search(rf"^# Node {url.group(1)}, the major ubuntu-latest", text, re.M)
    assert "actions/runner-images" in text and "SHASUMS256.txt" in text


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


def test_the_lane_stage_fixes_its_environment_and_takes_the_three_files_and_the_mirrors_alone() -> None:
    last = _stages()[-1]
    env  = " ".join(rest for keyword, rest in last if keyword == "ENV").split()
    assert "ENVIRONMENT=local" in env and "GIT_TERMINAL_PROMPT=0" in env
    copies = [rest.split() for keyword, rest in last if keyword in ("COPY", "ADD")]
    assert len(copies) == 2, "two COPYs into the lane stage, root's and the mirrors'"
    root    = next(words for words in copies if "/opt/kdf/" in words)
    sources = [word for word in root if not word.startswith("--")][:-1]
    assert sorted(sources) == ["lanes.sh", "repo.tar"] and root[-1] == "/opt/kdf/"
    # root's, so no lane can change the script the last step runs (D-072)
    assert not [word for word in root if word.startswith("--chown")]
    # the mirrors by an instruction of their own, the folder named alone so it lands as itself, runner's, so git's
    # ownership check passes as on GitHub's runner (D-078)
    mirrors = next(words for words in copies if words is not root)
    assert mirrors == ["--chown=runner:runner", "mirrors", "/home/runner/mirrors/"], mirrors
    order = [index for index, (keyword, rest) in enumerate(last) if keyword == "COPY" and "mirrors" in rest]
    lanes = [index for index, (keyword, rest) in enumerate(last) if keyword == "RUN" and "--setup" in rest]
    assert order and lanes and order[0] < lanes[0], "the mirrors are in place before setup runs"


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
    makefile  = "setup:\n\t@echo set up\n\t@echo setup > ../order.txt\n"
    makefile += "ci-a:\n\t@echo a >> ../order.txt\nci-b:\n\t@echo b >> ../order.txt\n"
    work = _work(tmp_path, makefile)
    done = _lane_script(tmp_path, "--setup", "setup", "--mirrors", (tmp_path / "none").as_posix(), work.as_posix(),
                        "results.txt", "30", "ci-a", "ci-b")
    assert done.returncode == 0, done.stdout + done.stderr
    assert _lines(tmp_path / "order.txt") == ["setup", "a", "b"]
    assert _lines(tmp_path / "results.txt") == ["ci-a 0", "ci-b 0"]
    # setup's status in a file of its own beside the results, its output in its own log, printed when it ends
    assert _lines(tmp_path / "setup") == ["setup 0"]
    assert _lines(tmp_path / "setup.log") == ["set up"]
    assert "set up\n==== kdf-preflight setup setup exited 0" in done.stdout


def test_a_red_setup_skips_each_make_lane_and_still_runs_actionlint(tmp_path: Path) -> None:
    makefile = "setup-red:\n\t@echo the reason setup failed\n\t@exit 2\nci-a:\n\t@echo ran > ../ran.txt\n"
    work = _work(tmp_path, makefile)
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
    # CI's checkout has no .env file, so one a setup copies from its example is removed before the lanes, an example
    # and a tracked file kept (D-078)
    makefile  = "setup:\n\t@cp .env.local.example .env.local\n\t@echo X= > .env.kdf\n"
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
    work = _work(tmp_path, makefile, {".gitignore": "locked/\n"})
    done = _lane_script(tmp_path, "--setup", "setup", work.as_posix(), "results.txt", "30", "ci-a")
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
    dump      = "@env | grep '^GIT_CONFIG' | LC_ALL=C sort > ../{0}.txt || true\n"
    makefile  = "setup:\n\t" + dump.format("setup-env") + "ci-a:\n\t" + dump.format("lane-env")
    work = _work(tmp_path, makefile)
    done = _lane_script(tmp_path, "--setup", "setup", "--mirrors", mirrors.as_posix(), work.as_posix(), "results.txt",
                        "30", "ci-a")
    assert done.returncode == 0, done.stdout + done.stderr
    expected = [f"GIT_CONFIG_COUNT={len(names)}"] if names else []
    expected += [f"GIT_CONFIG_KEY_{index}=url.file://{mirrors.as_posix()}/{name}.git.insteadOf"
                 for index, name in enumerate(names)]
    expected += [f"GIT_CONFIG_VALUE_{index}=https://github.com/Needless2Say/{name}.git"
                 for index, name in enumerate(names)]
    assert _lines(tmp_path / "setup-env.txt") == sorted(expected)
    assert _lines(tmp_path / "lane-env.txt") == sorted(expected)


@pytest.mark.parametrize("setup", ["setup", ""])
def test_a_lane_forging_setups_status_never_keeps_it(tmp_path: Path, setup: str) -> None:
    # setup's status is written once every lane has run, by the same remove, write and read back as the lanes', so a
    # lane's write there is gone, and with no setup no file is left (D-078)
    makefile = "setup:\n\t@echo set\nci-forge:\n\t@printf 'setup 0\\nsetup 0\\n' > ../setup\n\t@exit 3\n"
    work = _work(tmp_path, makefile)
    done = _lane_script(tmp_path, "--setup", setup, work.as_posix(), "results.txt", "30", "ci-forge")
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
    A repo with two commits, a home for docker's configuration, the runs folder and the stand in for docker.
    """
    repo: Path
    home: Path
    runs: Path
    fake: Path
    log:  Path
    tar:  Path


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


@pytest.fixture()
def rig(tmp_path: Path) -> Rig:
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
    fake = tmp_path / "fake-docker"
    fake.write_text(FAKE, encoding = "utf-8", newline = "\n")
    fake.chmod(fake.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    return Rig(
        repo = repo,
        home = home,
        runs = tmp_path / "runs",
        fake = fake,
        log = tmp_path / "docker.log",
        tar = tmp_path / "seen.tar",
    )


def _run(
    rig: Rig,
    *args: str,
    mode: str = "pass",
    env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    """
    Run the tool with exactly these arguments, the stand in playing docker in the given mode, with no docker or git
    variable of this machine's and a home of the rig's own.
    """
    environment = {
        key: value for key, value in os.environ.items() if key not in DOCKER_ENV and not key.startswith("GIT_")
    }
    environment.update({
        "KDF_DOCKER_BIN": rig.fake.as_posix(),
        "KDF_PREFLIGHT_DIR": rig.runs.as_posix(),
        "HOME": rig.home.as_posix(),
        "USERPROFILE": str(rig.home),
        "FAKE_MODE": mode,
        "FAKE_LOG": rig.log.as_posix(),
        "FAKE_TAR": rig.tar.as_posix(),
    })
    environment.update(env or {})
    return subprocess.run(
        [str(BASH), str(TOOL), *args],
        capture_output = True,
        text = True,
        env = environment,
        timeout = 120,
    )


def _preflight(
    rig: Rig,
    *lanes: str,
    extra: tuple[str, ...] = (),
    mode: str = "pass",
    env: dict[str, str] | None = None,
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


def test_the_context_holds_the_tar_the_dockerfile_and_the_lane_script_alone(rig: Rig) -> None:
    assert _preflight(rig, "ci-lint").returncode == 0
    contexts = [line.rstrip() for line in _logged(rig) if line.startswith("context ")]
    assert contexts == ["context base Dockerfile lanes.sh repo.tar", "context lanes Dockerfile lanes.sh repo.tar"]


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


def test_a_private_package_failure_prints_the_skipped_preflight_hint(rig: Rig) -> None:
    done = _preflight(rig, "ci-lint", mode = "cred")
    assert done.returncode == 1 and "skipped pre-flight" in done.stdout, done.stdout


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
