"""
Tests for kdf-preflight.sh (D-072), the one way a session runs a Linux pre-flight of a repo's lanes, and its image.

The image's tests read `tools/claude-code/preflight/Dockerfile` as text and hold its pins, the run id in the step that
runs the lanes, the lane stage's fixed environment and a last stage that is not root, and ask git whether
`.gitattributes` gives the Dockerfile and the lane script LF.
"""

from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT       = Path(__file__).resolve().parents[2]
PREFLIGHT  = ROOT / "tools" / "claude-code" / "preflight"
DOCKERFILE = PREFLIGHT / "Dockerfile"
LANES      = PREFLIGHT / "lanes.sh"
CI_YML     = ROOT / ".github" / "workflows" / "ci.yml"
GIT        = shutil.which("git")

DIGEST = re.compile(r"^[a-z0-9.-]+(/[a-z0-9._-]+)+@sha256:[0-9a-f]{64}$")


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
    lanes = next(index for index, (keyword, rest) in enumerate(last) if keyword == "RUN" and "lanes.sh" in rest)
    first_user = next(index for index, (keyword, _) in enumerate(last) if keyword == "USER")
    assert first_user < lanes, "the lanes run as runner"


def test_the_run_id_is_used_in_the_step_that_runs_the_lanes_and_in_the_marker_step() -> None:
    last = _stages()[-1]
    args = [rest.split("=")[0] for keyword, rest in last if keyword == "ARG"]
    assert "RUN_ID" in args, "the run id is a build argument of the last stage"
    runs   = [rest for keyword, rest in last if keyword == "RUN"]
    lanes  = [rest for rest in runs if "lanes.sh" in rest]
    marker = [rest for rest in runs if "KDF-PREFLIGHT-RESULT" in rest]
    used   = re.compile(r"\$\{?RUN_ID\b")
    assert len(lanes) == 1 and used.search(lanes[0]), "so the step that runs the lanes is never taken from the cache"
    assert len(marker) == 1 and used.search(marker[0]) and "KDF-PREFLIGHT-END" in marker[0]
    assert runs[-1] == marker[0], "the marker step is the last"
    assert runs.index(lanes[0]) < runs.index(marker[0])


def test_the_lane_stage_fixes_its_environment_and_takes_the_three_files_alone() -> None:
    last = _stages()[-1]
    env  = " ".join(rest for keyword, rest in last if keyword == "ENV").split()
    assert "ENVIRONMENT=local" in env and "GIT_TERMINAL_PROMPT=0" in env
    copies = [rest.split() for keyword, rest in last if keyword in ("COPY", "ADD")]
    assert len(copies) == 1, "one COPY into the lane stage"
    sources = [word for word in copies[0] if not word.startswith("--")][:-1]
    assert sorted(sources) == ["lanes.sh", "repo.tar"] and "--chown=runner:runner" in copies[0]


def test_the_lane_stage_unpacks_the_tar_and_makes_a_repo_of_one_commit() -> None:
    runs  = [rest for keyword, rest in _stages()[-1] if keyword == "RUN"]
    setup = next(rest for rest in runs if "repo.tar" in rest)
    order = [setup.find(words) for words in ("id -u", "tar -xf", "init -q", "add -A", "commit -q")]
    assert -1 not in order and order == sorted(order), "id -u, unpack, init, add, then commit, as runner"


@pytest.mark.skipif(GIT is None, reason = "git reads the attributes")
def test_gitattributes_gives_the_dockerfile_and_the_lane_script_lf() -> None:
    done = subprocess.run(
        [str(GIT), "-C", str(ROOT), "check-attr", "eol", "--",
         "tools/claude-code/preflight/Dockerfile", "tools/claude-code/preflight/lanes.sh"],
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


def test_the_base_installs_shellcheck_and_fails_without_it() -> None:
    # actionlint runs ShellCheck over every run: script only when it is on the PATH, as on GitHub's runner, and skips
    # that check without a word when it is not (Round Table 29)
    apt = [rest for keyword, rest in _stages()[0] if keyword == "RUN" and "apt-get install" in rest]
    assert len(apt) == 1 and "shellcheck" in apt[0].split(), "ShellCheck beside git and make, from Debian"
    assert "&& shellcheck --version" in apt[0], "its version printed, so a base without it fails to build"


def test_the_actionlint_lane_is_red_when_no_shellcheck_is_on_the_path() -> None:
    text  = LANES.read_text(encoding = "utf-8")
    guard = text.find("command -v shellcheck")
    run   = text.find('"$limit" actionlint')
    assert -1 < guard < run, "the guard comes before actionlint runs"
    assert re.search(r"\(exit 127\)", text[guard:run]), "the lane's status is 127, red"
