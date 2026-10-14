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

# ======================================================================================================================
# the wrapper
# ======================================================================================================================

# the variables that point docker or buildx at another machine or another configuration, each refused
DOCKER_ENV = ("DOCKER_HOST", "DOCKER_CONTEXT", "DOCKER_CONFIG", "BUILDX_BUILDER", "BUILDX_CONFIG")

MAKEFILE = (
    ".PHONY: ci-lint ci-unit-tests\n"
    "CI_VAR := ci-hidden\n"
    "ci-lint: ## lint\n\t@echo lint\n"
    "ci-unit-tests:\n\t@echo tests\n"
    "ci-version-check:\n\t@echo version\n"
    "ci-deploy-prod:\n\t@echo deploy\n"
    "ci-dev-check:\n\t@echo dev\n"
    "ci-dev-local-check:\n\t@echo local\n"
    "ci-x := not a target\n"
)

# a stand in for docker, it records each call, lists a build's context and plays a build's log as FAKE_MODE says
FAKE = r"""#!/usr/bin/env bash
export LC_ALL=C
echo "call $*" >> "$FAKE_LOG"
[ "$1" = build ] || exit 0
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
case "$mode" in red|cred) status=2 ;; esac
end="\n"
[ "$mode" != crlf ] || end="\r\n"
for lane in $lanes; do
    printf "#14 0.1 KDF-PREFLIGHT-RESULT %s %s %s$end" "$id" "$lane" "$status" >&2
    status=0
    [ "$mode" != partial ] || break
done
[ "$mode" = noend ] || printf "#14 0.2 KDF-PREFLIGHT-END %s$end" "$id" >&2
exit 0
"""


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
    ".env.kdf", "config/.ENV.LOCAL", "keys/notes.txt", "certs/site.pem", "deploy/id_ed25519", "infra/prod.tfvars",
    "state/main.tfstate.backup", ".netrc",
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
    run, = _left(rig)
    assert (run / "build.log").is_file() and (run / "context" / "repo.tar").is_file()
    assert _calls(rig)[-1][0] == "rmi"


def test_a_private_package_failure_prints_the_skipped_preflight_hint(rig: Rig) -> None:
    done = _preflight(rig, "ci-lint", mode = "cred")
    assert done.returncode == 1 and "skipped pre-flight" in done.stdout, done.stdout


def test_marker_lines_ending_in_a_carriage_return_are_read(rig: Rig) -> None:
    assert _preflight(rig, "ci-lint", "actionlint", mode = "crlf").returncode == 0


@pytest.mark.parametrize("mode", ["nomarker", "noend", "partial", "forged", "builderror"])
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
