"""
Tests for D-035, untrusted code runs in a job that names no secret.

The fetch script's scan and rules run here on text and on a fake git, so no test touches a network or a git setting.
The workflows are read as text, as the rest of this suite reads them, and held to their one template, each lane's
install job names no secret, keeps its id and name, and fails closed. The hunt's scanner runs here on bytes. What
runs only on a GitHub runner, git reading the mirrors through the rewrite and root reading the runner's memory, is
proved by this repo's own CI on every pull request, the secretless-proof and secretless-control jobs of ci.yml.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import re
from pathlib import Path

import fetch_private_packages as fpp
import pytest
import render_fetch_job as render

ROOT      = Path(__file__).resolve().parents[2]
WORKFLOWS = ROOT / ".github" / "workflows"
HUNT_FILE = ROOT / "tests" / "fixtures" / "secretless" / "hunt.py"

JOB_B = {
    "ci-python-tests.yml": ("unit-tests", "Unit Tests"),
    "ci-python-integration.yml": ("integration-tests", "Integration Tests (Postgres)"),
    "ci-python-system.yml": ("system-tests", "System Tests (source and bundle)"),
    "ci-python-mutation.yml": ("mutation-tests", "Mutation (${{ matrix.lane }})"),
    "ci-python-security.yml": ("pip-audit", "pip-audit (CVE check)"),
    "ci-python-lint.yml": ("lint", "Lint (ruff)"),
    "ci-python-typecheck.yml": ("type-check", "Type-check (mypy)"),
}

SDK_SHA = "2f33da35c30406089a8a991be02a1891ecf73753"
SDK_URL = "git+https://github.com/Needless2Say/kriegerdataforge-sdk.git"
FMT_URL = "git+https://github.com/Needless2Say/kriegerdataforge-fmt.git"

PACKAGES = "kriegerdataforge-sdk,kriegerdataforge-reports-sdk,kriegerdataforge-fmt"

LS_REMOTE = "\n".join([
    f"{'1' * 40}\trefs/heads/main",
    f"{'2' * 40}\trefs/tags/v1.0.0",
    f"{'3' * 40}\trefs/tags/v1.0.0^{{}}",
    f"{'4' * 40}\trefs/tags/v2.0.0",
    f"{'5' * 40}\trefs/heads/both",
    f"{'6' * 40}\trefs/tags/both",
])


def _text(name: str) -> str:
    return (WORKFLOWS / name).read_bytes().decode("utf-8").replace("\r\n", "\n")


def _jobs(text: str) -> dict[str, str]:
    """
    A workflow's jobs, each by its id with its own text, the comment lines above a job left with the one before.
    """
    body = text.split("\njobs:\n", 1)[1]
    found: dict[str, str] = {}
    parts = re.split(r"^  ([a-z0-9-]+):\n", body, flags = re.MULTILINE)
    for index in range(1, len(parts), 2):
        found[parts[index]] = parts[index + 1]
    return found

# ======================================================================================================================
# The scan, requirement files read as text
# ======================================================================================================================

def test_the_scan_reads_the_shapes_the_callers_write():
    """
    The forms every caller's requirement files hold on 2026-10-02, extras before the at sign, a full commit id from
    pip-compile, a tag from a .in file, an env marker, an editable, a pyproject dependency string.
    """
    text = "\n".join([
        f"kriegerdataforge-sdk[fastapi,database] @ {SDK_URL}@{SDK_SHA}",
        "kdf-fmt @ git+https://github.com/Needless2Say/kriegerdataforge-fmt.git@v1.2.0 ; python_version >= '3.14'",
        "-e git+https://github.com/Needless2Say/kriegerdataforge-reports-sdk.git@v0.2.1#egg=kdf-reports",
        '  "kriegerdataforge-sdk @ git+https://github.com/Needless2Say/kriegerdataforge-sdk.git@v0.11.0",',
    ])
    pins, includes = fpp.scan_text(text, "requirements.txt")
    assert pins == [
        ("kriegerdataforge-sdk", SDK_SHA),
        ("kriegerdataforge-fmt", "v1.2.0"),
        ("kriegerdataforge-reports-sdk", "v0.2.1"),
        ("kriegerdataforge-sdk", "v0.11.0"),
    ]
    assert includes == []


def test_a_subdirectory_tail_is_part_of_the_url_and_not_of_the_ref():
    pins, _ = fpp.scan_text(
        "probe @ git+https://github.com/Needless2Say/kriegerdataforge-cicd.git@v0.2.99#subdirectory=tests/probe",
        "r",
    )
    assert pins == [("kriegerdataforge-cicd", "v0.2.99")]


@pytest.mark.parametrize("line", [
    "# kdf-fmt @ git+https://github.com/Needless2Say/kriegerdataforge-fmt.git@v1.2.0",
    "    # indented comment git+https://github.com/Needless2Say/kriegerdataforge-fmt.git@v1.2.0",
    "requests==2.32.3  # mirrors git+https://github.com/Needless2Say/kriegerdataforge-fmt.git@v1.2.0",
])
def test_a_commented_pin_is_not_read(line):
    assert fpp.scan_text(line, "r") == ([], [])


def test_a_continued_line_is_read_whole():
    text = ("kriegerdataforge-sdk @ git+https://github.com/Needless2Say/kriegerdataforge-sdk.git@v0.11.0 \\\n"
            "    --hash=sha256:" + "a" * 64 + "\n")
    assert fpp.scan_text(text, "r")[0] == [("kriegerdataforge-sdk", "v0.11.0")]


@pytest.mark.parametrize("line", [
    "sdk @ git+ssh://git@github.com/Needless2Say/kriegerdataforge-sdk.git@v1",
    "sdk @ git+https://github.com/Needless2Say/kriegerdataforge-sdk@v1",
    "sdk @ git+https://github.com/needless2say/kriegerdataforge-sdk.git@v1",
    "sdk @ https://github.com/Needless2Say/kriegerdataforge-sdk/archive/v1.zip",
    "--extra-index-url https://github.com/Needless2Say/kriegerdataforge-sdk",
])
def test_a_form_the_scan_cannot_read_fails_the_plan(line):
    """
    A pin the scan missed would reach the install job with no mirror, so any other mention of the owner's repos fails.
    """
    with pytest.raises(fpp.FetchError, match = "a form this lane does not read"):
        fpp.scan_text(line, "requirements.txt")


@pytest.mark.parametrize("line, path", [
    ("-r base.txt", "base.txt"),
    ("-rbase.txt", "base.txt"),
    ("--requirement=sub/base.txt", "sub/base.txt"),
    ("-c constraints.txt", "constraints.txt"),
    ("--constraint constraints.txt", "constraints.txt"),
])
def test_an_include_is_found(line, path):
    assert fpp.scan_text(line, "r")[1] == [path]


def _reader(files: dict[str, str]):
    return lambda name: files.get(name)


def test_an_include_is_followed_within_the_same_tree():
    files = {
        "requirements.txt": "-r base/common.txt\n",
        "base/common.txt": f"-c ../constraints.txt\nkdf-fmt @ {FMT_URL}@v1.2.0\n",
        "constraints.txt": f"sdk @ git+https://github.com/Needless2Say/kriegerdataforge-sdk.git@{SDK_SHA}\n",
    }
    pins  = fpp.scan_tree(_reader(files), ["requirements.txt"], "", required = False)
    assert {(pin.repo, pin.ref) for pin in pins} == {
        ("kriegerdataforge-fmt", "v1.2.0"),
        ("kriegerdataforge-sdk", SDK_SHA),
    }
    assert next(pin for pin in pins if pin.repo == "kriegerdataforge-fmt").sources == ["base/common.txt"]


@pytest.mark.parametrize(
    "include",
    ["-r ../outside.txt", "-r /etc/passwd", "-r https://example.com/r.txt", "-r C:/req.txt", "-r sub/../../out.txt"],
)
def test_an_include_that_leaves_the_tree_or_names_a_url_is_refused(include):
    with pytest.raises(fpp.FetchError, match = "not a path inside the same tree|leaves the tree"):
        fpp.scan_tree(_reader({"requirements.txt": include}), ["requirements.txt"], "", required = False)


def test_includes_that_loop_are_read_once():
    files = {"a.txt": "-r b.txt\n", "b.txt": "-r a.txt\n"}
    assert fpp.scan_tree(_reader(files), ["a.txt"], "", required = False) == []


def test_a_missing_default_file_is_skipped_and_a_missing_include_or_named_file_refused():
    assert fpp.scan_tree(_reader({}), ["requirements-dev.txt"], "", required = False) == []
    with pytest.raises(fpp.FetchError, match = "no such file"):
        fpp.scan_tree(_reader({"requirements.txt": "-r gone.txt"}), ["requirements.txt"], "", required = False)
    with pytest.raises(fpp.FetchError, match = "no such file"):
        fpp.scan_tree(_reader({}), ["requirements.txt"], "repo:", required = True)

# ======================================================================================================================
# The rules, the allowlist, the public caller, refs
# ======================================================================================================================

def test_the_allowlist_is_the_owners_private_packages_and_backends_and_this_public_repo():
    assert fpp.ALLOWLIST == {
        "kriegerdataforge-sdk": "private",
        "kriegerdataforge-reports-sdk": "private",
        "kriegerdataforge-fmt": "private",
        "kriegerdataforge": "private",
        "fitness-app-backend": "private",
        "tiffanys-space-backend": "private",
        "kriegerdataforge-cicd": "public",
    }


def test_a_repo_off_the_allowlist_is_refused():
    with pytest.raises(fpp.FetchError, match = "not on the allowlist"):
        fpp.check_repo("someone-elses-repo", True, "r")


def test_a_public_caller_mirrors_a_public_repo_alone():
    """
    A public repo's run artifacts are readable by anyone, so it has no private package to fetch.
    """
    fpp.check_repo("kriegerdataforge-cicd", False, "r")
    fpp.check_repo("kriegerdataforge-sdk", True, "r")
    with pytest.raises(fpp.FetchError, match = "the calling repo is public"):
        fpp.check_repo("kriegerdataforge-sdk", False, "r")


@pytest.mark.parametrize("event, expected", [("true", True), ("false", False), ("", False)])
def test_a_caller_whose_visibility_is_unknown_counts_as_public(event, expected):
    assert fpp.caller_is_private(event, "", "", "") is expected


@pytest.mark.parametrize("ref", ["v0.11.0", SDK_SHA, "release/2026-10", "v1.2.0-rc.1"])
def test_a_plain_ref_reads(ref):
    fpp.check_ref_text(ref, "r")


@pytest.mark.parametrize("ref", ["-v1", "v1..v2", "HEAD@{1}", "main~1", "v1.lock", "refs/", "a b"])
def test_a_ref_with_option_range_or_reflog_syntax_is_refused(ref):
    with pytest.raises(fpp.FetchError, match = "not a ref this lane reads"):
        fpp.check_ref_text(ref, "r")


@pytest.mark.parametrize("ref, allow, kind, sha", [
    ("v1.0.0", False, "tag", "3" * 40),
    ("v2.0.0", False, "tag", "4" * 40),
    (SDK_SHA, False, "sha", SDK_SHA),
    ("main", True, "branch", "1" * 40),
])
def test_a_ref_is_classified_and_an_annotated_tag_peeled(ref, allow, kind, sha):
    refs = fpp.parse_ls_remote(LS_REMOTE)
    assert fpp.classify("repo", ref, refs, allow, "r") == (kind, sha)


def test_a_branch_out_of_a_requirement_file_is_refused():
    with pytest.raises(fpp.FetchError, match = "is a branch, pin a tag or a full commit id"):
        fpp.classify("repo", "main", fpp.parse_ls_remote(LS_REMOTE), False, "requirements.txt")


@pytest.mark.parametrize("ref, message", [("both", "both a tag and a branch"), ("gone", "names no tag or branch")])
def test_an_ambiguous_or_unknown_ref_is_refused(ref, message):
    with pytest.raises(fpp.FetchError, match = message):
        fpp.classify("repo", ref, fpp.parse_ls_remote(LS_REMOTE), True, "r")


def test_a_git_error_never_prints_a_token():
    assert fpp.redact("fatal: unable to access 'https://__token__:ghs_secret@github.com/x.git/'") == \
        "fatal: unable to access 'https://***@github.com/x.git/'"

# ======================================================================================================================
# plan
# ======================================================================================================================

def _plan(tmp_path, files: dict[str, str], **env: str) -> dict:
    for name, text in files.items():
        (tmp_path / name).parent.mkdir(parents = True, exist_ok = True)
        (tmp_path / name).write_text(text, encoding = "utf-8")
    base = {"CALLER_PRIVATE": "true", "REQUIREMENT_FILES": "requirements.txt requirements-dev.txt"}
    return fpp.plan(tmp_path, {**base, **env})


def test_the_plan_names_the_pins_and_mints_for_exactly_their_repos(tmp_path):
    data = _plan(
        tmp_path,
        {"requirements.txt": f"sdk @ {SDK_URL}@{SDK_SHA}\nfmt @ {FMT_URL}@v1.2.0\n"},
    )
    assert data["repositories"] == ["kriegerdataforge-fmt", "kriegerdataforge-sdk"]
    assert {(pin["repo"], pin["ref"]) for pin in data["pins"]} == {
        ("kriegerdataforge-sdk", SDK_SHA),
        ("kriegerdataforge-fmt", "v1.2.0"),
    }


def test_a_plan_with_nothing_to_fetch_mints_nothing(tmp_path):
    assert _plan(tmp_path, {"requirements.txt": "requests==2.32.3\n"})["repositories"] == []


def test_the_plan_refuses_a_private_pin_in_a_public_caller(tmp_path):
    with pytest.raises(fpp.FetchError, match = "the calling repo is public"):
        _plan(
            tmp_path,
            {"requirements.txt": "x @ git+https://github.com/Needless2Say/kriegerdataforge-sdk.git@v1\n"},
            CALLER_PRIVATE = "false",
        )


def test_the_canary_shape_plans_a_backend_at_its_branch_with_a_narrower_token(tmp_path):
    """
    The kdf-sdk canary, a backend at main, its requirement files read inside its mirror, the token for the backend
    and the three packages alone.
    """
    data = _plan(
        tmp_path,
        {},
        EXTRA_REPOS = "fitness-app-backend@main",
        SCAN_FILES = "fitness-app-backend:requirements.txt fitness-app-backend:requirements-dev.in",
        TOKEN_REPOSITORIES = f"fitness-app-backend,{PACKAGES}",
    )
    assert data["extras"] == [{"repo": "fitness-app-backend", "ref": "main"}]
    assert data["repositories"] == [
        "fitness-app-backend",
        "kriegerdataforge-fmt",
        "kriegerdataforge-reports-sdk",
        "kriegerdataforge-sdk",
    ]


def test_a_token_list_that_leaves_out_a_cloned_repo_is_refused(tmp_path):
    with pytest.raises(fpp.FetchError, match = "leaves out fitness-app-backend"):
        _plan(tmp_path, {}, EXTRA_REPOS = "fitness-app-backend@main", TOKEN_REPOSITORIES = "kriegerdataforge-sdk")


def test_a_file_read_inside_a_mirror_needs_its_repo_listed_as_an_extra(tmp_path):
    with pytest.raises(fpp.FetchError, match = "name it in extra_repos too"):
        _plan(tmp_path, {}, SCAN_FILES = "fitness-app-backend:requirements.txt")


def test_main_writes_the_plan_and_the_repositories_output(tmp_path, monkeypatch):
    (tmp_path / "caller").mkdir()
    (tmp_path / "caller" / "requirements.txt").write_text(
        "fmt @ git+https://github.com/Needless2Say/kriegerdataforge-fmt.git@v1.2.0\n",
        encoding = "utf-8",
    )
    monkeypatch.setenv("CALLER_PRIVATE", "true")
    monkeypatch.setenv("REQUIREMENT_FILES", "requirements.txt")
    monkeypatch.setenv("GITHUB_OUTPUT", str(tmp_path / "out"))
    assert fpp.main(["plan", "--caller", str(tmp_path / "caller"), "--out", str(tmp_path / "plan.json")]) == 0
    assert (tmp_path / "out").read_text(encoding = "utf-8") == "repositories=kriegerdataforge-fmt\n"
    assert json.loads((tmp_path / "plan.json").read_text(encoding = "utf-8"))["caller_private"] is True

# ======================================================================================================================
# fetch, against a fake git
# ======================================================================================================================

class FakeGit:
    """
    Records every git call, answers ls-remote from a table and git show from files, and fails no fetch.
    """
    def __init__(self, remotes: dict[str, str], shown: dict[str, str] | None = None):
        self.remotes = remotes
        self.shown   = shown or {}
        self.calls: list[list[str]] = []


    def __call__(self, args: list[str]) -> str:
        self.calls.append(args)
        if args[0] == "ls-remote":
            return self.remotes[args[-1].rsplit("/", 1)[1].removesuffix(".git")]
        if "show" in args:
            if args[-1] not in self.shown:
                raise fpp.FetchError("git show failed: path does not exist")
            return self.shown[args[-1]]
        if args[0] == "init":
            Path(args[-1]).mkdir(parents = True)
        return ""


def test_the_fetch_clones_each_pin_whole_into_a_bare_mirror_and_records_it(tmp_path):
    git     = FakeGit({"kriegerdataforge-fmt": f"{'7' * 40}\trefs/tags/v1.2.0"})
    data    = {
        "caller_private": True,
        "repositories": ["kriegerdataforge-fmt"],
        "extras": [],
        "scan": [],
        "pins": [{"repo": "kriegerdataforge-fmt", "ref": "v1.2.0", "sources": ["requirements.txt"]}],
    }
    entries = fpp.fetch(data, tmp_path, git)
    assert entries == [{"repo": "kriegerdataforge-fmt", "ref": "v1.2.0", "kind": "tag", "sha": "7" * 40,
                        "sources": ["requirements.txt"]}]
    init = next(call for call in git.calls if call[0] == "init")
    assert "--bare" in init and init[-1].endswith("kriegerdataforge-fmt.git")
    fetch = next(call for call in git.calls if "fetch" in call)
    assert "--depth" not in " ".join(fetch), "a filtered clone of a shallow mirror fails, mirrors keep the history"
    assert f"{'7' * 40}:refs/heads/kdf-pin-777777777777" in fetch and "+refs/tags/v1.2.0:refs/tags/v1.2.0" in fetch
    assert "https://github.com/Needless2Say/kriegerdataforge-fmt.git" in fetch
    assert all("@github.com" not in part for call in git.calls for part in call), "no URL carries a credential"


def test_the_fetch_resolves_an_extra_branch_reads_its_files_and_fetches_their_pins(tmp_path):
    backend = "1" * 40
    git     = FakeGit(
        {
            "fitness-app-backend": f"{backend}\trefs/heads/main",
            "kriegerdataforge-sdk": f"{'8' * 40}\trefs/tags/v0.11.0",
        },
        {
            f"{backend}:requirements.txt": f"sdk @ {SDK_URL}@{SDK_SHA}\n",
            f"{backend}:requirements-dev.in": "-r requirements.in\n",
            f"{backend}:requirements.in": f"sdk @ {SDK_URL}@v0.11.0\n",
        },
    )
    data    = {
        "caller_private": True,
        "pins": [],
        "repositories": ["fitness-app-backend", "kriegerdataforge-sdk"],
        "extras": [{"repo": "fitness-app-backend", "ref": "main"}],
        "scan": [
            {"repo": "fitness-app-backend", "path": "requirements.txt"},
            {"repo": "fitness-app-backend", "path": "requirements-dev.in"},
        ],
    }
    entries = fpp.fetch(data, tmp_path, git)
    assert [(entry["repo"], entry["ref"], entry["kind"], entry["sha"]) for entry in entries] == [
        ("fitness-app-backend", "main", "branch", backend),
        ("kriegerdataforge-sdk", SDK_SHA, "sha", SDK_SHA),
        ("kriegerdataforge-sdk", "v0.11.0", "tag", "8" * 40),
    ]
    branch_fetch = next(call for call in git.calls if "fetch" in call and call[1].endswith("fitness-app-backend.git"))
    assert f"{backend}:refs/heads/main" in branch_fetch, "the branch in the mirror is the commit the manifest records"


def test_a_pin_read_inside_a_mirror_must_be_within_the_token(tmp_path):
    backend = "1" * 40
    git     = FakeGit(
        {"fitness-app-backend": f"{backend}\trefs/heads/main"},
        {f"{backend}:requirements.txt": "x @ git+https://github.com/Needless2Say/kriegerdataforge-fmt.git@v1\n"},
    )
    data    = {
        "caller_private": True,
        "pins": [],
        "repositories": ["fitness-app-backend"],
        "extras": [{"repo": "fitness-app-backend", "ref": "main"}],
        "scan": [{"repo": "fitness-app-backend", "path": "requirements.txt"}],
    }
    with pytest.raises(fpp.FetchError, match = "add it to token_repositories"):
        fpp.fetch(data, tmp_path, git)


def test_main_fetch_writes_the_manifest_and_publishes_only_the_tokens_hash(tmp_path, monkeypatch, capsys):
    plan_file = tmp_path / "plan.json"
    plan_file.write_text(
        json.dumps({"caller_private": True, "pins": [], "extras": [], "scan": [], "repositories": []}),
        encoding = "utf-8",
    )
    monkeypatch.setenv("KDF_FETCH_TOKEN", "ghs_" + "x" * 36)
    monkeypatch.setenv("GITHUB_OUTPUT", str(tmp_path / "out"))
    assert fpp.main(["fetch", "--plan", str(plan_file), "--dest", str(tmp_path / "dest")]) == 0
    assert json.loads((tmp_path / "dest" / "manifest.json").read_text(encoding = "utf-8")) == []
    digest = hashlib.sha256(("ghs_" + "x" * 36).encode()).hexdigest()
    assert (tmp_path / "out").read_text(encoding = "utf-8") == f"token_sha256={digest}\n"
    assert "ghs_" not in capsys.readouterr().out


def test_a_refusal_is_one_error_line_and_exit_1(tmp_path, monkeypatch, capsys):
    (tmp_path / "requirements.txt").write_text(
        "x @ git+https://github.com/Needless2Say/not-listed.git@v1\n",
        encoding = "utf-8",
    )
    monkeypatch.setenv("CALLER_PRIVATE", "true")
    monkeypatch.setenv("REQUIREMENT_FILES", "requirements.txt")
    monkeypatch.delenv("GITHUB_OUTPUT", raising = False)
    assert fpp.main(["plan", "--caller", str(tmp_path), "--out", str(tmp_path / "plan.json")]) == 1
    assert "::error::requirements.txt: Needless2Say/not-listed is not on the allowlist" in capsys.readouterr().out

# ======================================================================================================================
# The workflows
# ======================================================================================================================

def test_every_copy_of_the_fetch_job_is_the_template():
    """
    The fetch job is written into each lane and the standalone workflow by render_fetch_job.py. A hand edit to one copy,
    or an edit to the script without a render, fails here.
    """
    assert render.main(["--check"]) == 0
    assert render.LANES == tuple(JOB_B)


def test_the_script_holds_nothing_the_heredoc_or_an_expression_would_change():
    script = (ROOT / "scripts" / "fetch_private_packages.py").read_text(encoding = "utf-8")
    assert "${{" not in script and f"\n{render.DELIMITER}\n" not in script


def test_the_script_runs_git_and_nothing_else():
    """
    One subprocess call, git, with no hook and no credential helper, and the API read of the caller's visibility.
    """
    script = (ROOT / "scripts" / "fetch_private_packages.py").read_text(encoding = "utf-8")
    assert script.count("subprocess.run(") == 1
    assert '["git", "-c", "core.hooksPath=/dev/null", "-c", "credential.helper=", *args]' in script
    for forbidden in ("os.system", "exec(", "eval(", "import pip", "shell = True", "shell=True", "Popen"):
        assert forbidden not in script, forbidden
    assert script.count("urllib.request.urlopen(") == 1


@pytest.mark.parametrize("name", [*JOB_B, render.STANDALONE])
def test_the_fetch_job_alone_names_a_secret_and_runs_only_git_and_its_own_text(name):
    fetch = _jobs(_text(name))["fetch-private"]
    steps = re.sub(
        r"<<'KDF_FETCH_PRIVATE_PACKAGES'\n.*?\n          KDF_FETCH_PRIVATE_PACKAGES\n",
        "",
        fetch,
        flags = re.DOTALL,
    )
    for tool in ("pip ", "pip3", "make ", "setup-python", "npm ", "inputs.install_command", "inputs.test_command"):
        assert tool not in steps, f"the fetch job runs {tool.strip()}"
    runs = re.findall(r"run: (/usr/bin/python3[^\n]*)", fetch)
    assert len(runs) == 2 and all('"$RUNNER_TEMP/kdf-fetch/fetch_private_packages.py"' in run for run in runs)
    assert re.findall(r"persist-credentials: (\w+)", fetch) == ["false"]
    assert "    permissions:\n      contents: read\n" in fetch
    assert "secrets.KDF_APP_PRIVATE_KEY" in fetch


@pytest.mark.parametrize("name", JOB_B)
def test_the_install_job_keeps_its_id_and_name_and_names_no_secret(name):
    """
    A ruleset requires "<caller job> / <called job name>", so the job keeps both, and it names no secret at all.
    """
    job_id, title = JOB_B[name]
    jobs = _jobs(_text(name))
    assert jobs[job_id].startswith(f"    name: {title}\n")
    assert "secrets." not in jobs[job_id] and "pkg-token" not in jobs[job_id]
    assert "    permissions:\n      contents: read\n" in jobs[job_id]
    assert "GIT_CONFIG_KEY_0:" not in jobs[job_id], "the token's rewrite is gone from the install step"


@pytest.mark.parametrize("name", JOB_B)
def test_the_install_job_fails_closed_when_the_fetch_did_not_succeed(name):
    """
    A skipped required job counts as passing, so the job runs whatever the fetch did and stops at its first step.
    """
    job_id, _title = JOB_B[name]
    job = _jobs(_text(name))[job_id]
    assert "    needs: [fetch-private]\n" in job
    assert "    if: ${{ !cancelled() }}\n" in job and "always()" not in job.split("    steps:\n")[0]
    first = job.split("    steps:\n", 1)[1].split("\n      - ", 1)[0]
    assert "name: Require the private packages" in first
    assert 'FETCH_RESULT: ${{ needs.fetch-private.result }}' in first and '!= "success"' in first and "exit 1" in first


@pytest.mark.parametrize("name", JOB_B)
def test_without_package_access_the_lane_runs_as_one_job(name):
    jobs = _jobs(_text(name))
    assert "    if: ${{ inputs.needs_sdk_auth }}\n" in jobs["fetch-private"]
    job     = jobs[JOB_B[name][0]]
    private = [step for step in job.split("\n      - ")[1:] if "fetch-private" in step or "kdf-private" in step]
    assert len(private) == 3 and all("if: ${{ inputs.needs_sdk_auth }}" in step for step in private)


def test_the_private_steps_of_every_install_job_are_identical():
    def private(name: str) -> str:
        job     = _jobs(_text(name))[JOB_B[name][0]]
        start   = job.index("      - name: Require the private packages")
        end     = job.index("\n\n", start)
        mirrors = job.index("      # D-035. The private repos the fetch job cloned")
        return job[start:end] + job[mirrors:job.index("through the rewrite\"\n", mirrors)]


    copies = {private(name) for name in JOB_B}
    assert len(copies) == 1


def test_the_style_lane_stays_one_job_and_installs_only_the_pinned_formatter():
    """
    It runs no caller code, kdf-fmt never imports or executes what it formats (D-035), and this public repo's CI
    calls it.
    """
    jobs = _jobs(_text("ci-python-kdf-fmt.yml"))
    assert list(jobs) == ["style"]
    assert "kdf-fmt @ git+https://github.com/Needless2Say/kriegerdataforge-fmt.git@${{ inputs.kdf_fmt_ref }}" in \
        jobs["style"]


def test_this_repos_ci_proves_the_lane_and_controls_the_hunt():
    jobs  = _jobs(_text("ci.yml"))
    guard = "    if: ${{ github.event.pull_request.head.repo.full_name == github.repository && github.actor != " \
            "'dependabot[bot]' }}\n"
    proof, control = jobs["secretless-proof"], jobs["secretless-control"]
    assert proof.startswith(guard) and guard in control
    assert "    uses: ./.github/workflows/ci-python-tests.yml\n" in proof
    assert "      needs_sdk_auth: true\n" in proof and "hunt.py absent" in proof
    assert "extra_repos: kriegerdataforge-cicd@${{ github.head_ref }}" in proof
    assert "secrets.KDF_APP_PRIVATE_KEY" in control and "hunt.py present" in control

# ======================================================================================================================
# The hunt's scanner, on bytes
# ======================================================================================================================

def _hunt():
    spec   = importlib.util.spec_from_file_location("hunt", HUNT_FILE)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_the_hunt_finds_a_key_header_and_a_token_in_both_encodings():
    hunt   = _hunt()
    token  = "ghs_" + "A1b2" * 9
    target = hashlib.sha256(token.encode()).hexdigest()
    other  = "ghs_" + "Z9y8" * 9
    data   = (b"x" * 10 + b"-----BEGIN RSA PRIVATE KEY-----\n" + token.encode() + b" "
            + "PRIVATE KEY-----".encode("utf-16-le") + token.encode("utf-16-le") + b" " + other.encode())
    assert hunt.scan_bytes(data, target) == {"pem": 2, "tokens": 2, "matches": 1}


def test_the_hunt_counts_nothing_in_a_clean_buffer_and_matches_nothing_without_a_target():
    hunt = _hunt()
    assert hunt.scan_bytes(b"nothing secret here, ghs_short", "a" * 64) == {"pem": 0, "tokens": 0, "matches": 0}
    assert hunt.scan_bytes(("ghs_" + "q" * 36).encode(), "")["matches"] == 0
