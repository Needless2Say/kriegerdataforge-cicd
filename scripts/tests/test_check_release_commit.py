"""
Tests for the release check, `scripts/check_release_commit.py`, against real git repositories made in a temp folder.

A release's tag resolves to a commit, an annotated tag peeled to its commit, and the release deploys only when that
commit is on `origin/main`, whose every commit the owner merged. A tag off `main`, a missing tag, a version that is no
version and a history too shallow to judge are refused. The deploy jobs check out the commit the check printed and
compare their checkout with it, so a tag moved after the check changes nothing they deploy, and the compare's own
shell runs here too.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import check_release_commit as release
import pytest
import yaml

ROOT      = Path(__file__).resolve().parents[2]
WORKFLOWS = ROOT / ".github" / "workflows"
DEPLOYS   = ("cd-python-vercel.yml", "cd-nextjs-vercel.yml")
GIT_ENV   = {
    "GIT_AUTHOR_NAME": "Release Test",
    "GIT_AUTHOR_EMAIL": "release-test@example.invalid",
    "GIT_COMMITTER_NAME": "Release Test",
    "GIT_COMMITTER_EMAIL": "release-test@example.invalid",
    "GIT_CONFIG_NOSYSTEM": "1",
}


def _git(repo: Path, *args: str) -> str:
    run = subprocess.run(
        ["git", "-c", "init.defaultBranch=main", "-c", "tag.gpgSign=false", "-c", "commit.gpgSign=false", *args],
        cwd = repo,
        env = {**os.environ, **GIT_ENV},
        capture_output = True,
        text = True,
        check = True,
    )
    return run.stdout.strip()


def _commit(repo: Path, name: str) -> str:
    (repo / name).write_text(name, encoding = "utf-8")
    _git(repo, "add", name)
    _git(repo, "commit", "-q", "-m", name)
    return _git(repo, "rev-parse", "HEAD")


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    """
    A repository whose `main` holds two commits, with `origin/main` at its tip, and a branch `side` off it.
    """
    path = tmp_path / "repo"
    path.mkdir()
    _git(path, "init", "-q")
    _commit(path, "first")
    _commit(path, "second")
    _git(path, "update-ref", "refs/remotes/origin/main", "HEAD")
    _git(path, "checkout", "-q", "-b", "side")
    _commit(path, "side-only")
    _git(path, "checkout", "-q", "main")
    return path


def _check(repo: Path, version: str) -> tuple[bool, str, str | None]:
    return release.check(repo, version, "origin/main")


def test_a_lightweight_tag_on_main_is_allowed_and_names_its_commit(repo):
    head = _git(repo, "rev-parse", "main")
    _git(repo, "tag", "v1.2.0", head)
    ok, reason, sha = _check(repo, "1.2.0")
    assert ok, reason
    assert sha == head


def test_an_annotated_tag_on_main_is_peeled_to_its_commit(repo):
    first = _git(repo, "rev-parse", "main~1")
    _git(repo, "tag", "-a", "v1.1.0", "-m", "release", first)
    ok, reason, sha = _check(repo, "1.1.0")
    assert ok, reason
    assert sha == first
    assert sha != _git(repo, "rev-parse", "refs/tags/v1.1.0"), "the tag object is not the commit"


def test_a_version_given_with_its_v_reads_the_same_tag(repo):
    _git(repo, "tag", "v1.2.0", "main")
    assert _check(repo, "v1.2.0")[0]


def test_a_tag_off_main_is_refused(repo):
    _git(repo, "tag", "v9.9.9", "side")
    ok, reason, sha = _check(repo, "9.9.9")
    assert not ok
    assert sha is None
    assert "not on origin/main" in reason


def test_a_missing_tag_is_refused(repo):
    ok, reason, sha = _check(repo, "3.0.0")
    assert not ok and sha is None
    assert "no tag v3.0.0" in reason


@pytest.mark.parametrize("version", ["", "1.2", "1.2.0.1", "1.2.0^", "main", "1.2.0 ", "-1.2.0", "1.2.0..main"])
def test_a_version_that_is_no_version_is_refused_before_git_is_asked(repo, version):
    ok, reason, sha = _check(repo, version)
    assert not ok and sha is None
    assert "not a release version" in reason


def test_a_missing_main_is_refused(repo):
    _git(repo, "tag", "v1.2.0", "main")
    _git(repo, "update-ref", "-d", "refs/remotes/origin/main")
    ok, reason, _ = _check(repo, "1.2.0")
    assert not ok
    assert "history" in reason


def test_a_shallow_history_is_refused(repo, tmp_path):
    _git(repo, "tag", "v1.2.0", "main")
    shallow = tmp_path / "shallow"
    _git(tmp_path, "clone", "-q", "--depth", "1", "--no-single-branch", repo.as_uri(), str(shallow))
    _git(shallow, "fetch", "-q", "--depth", "1", "origin", "refs/tags/v1.2.0:refs/tags/v1.2.0")
    ok, reason, _ = _check(shallow, "1.2.0")
    assert not ok
    assert "shallow" in reason


def test_main_writes_the_commit_to_the_step_output(repo, tmp_path, monkeypatch):
    head = _git(repo, "rev-parse", "main")
    _git(repo, "tag", "v1.2.0", head)
    output = tmp_path / "output"
    monkeypatch.setenv("GITHUB_OUTPUT", str(output))
    monkeypatch.delenv("GITHUB_STEP_SUMMARY", raising = False)
    assert release.main(["--version", "1.2.0", "--repo-dir", str(repo)]) == 0
    assert output.read_text(encoding = "utf-8") == f"sha={head}\n"


def test_main_writes_no_commit_when_it_refuses(repo, tmp_path, monkeypatch):
    _git(repo, "tag", "v9.9.9", "side")
    output = tmp_path / "output"
    monkeypatch.setenv("GITHUB_OUTPUT", str(output))
    assert release.main(["--version", "9.9.9", "--repo-dir", str(repo)]) == 1
    assert not output.exists() or "sha=" not in output.read_text(encoding = "utf-8")

# ======================================================================================================================
# The deploy workflows
# ======================================================================================================================

def _jobs(workflow: str) -> dict:
    return yaml.safe_load((WORKFLOWS / workflow).read_bytes().decode("utf-8"))["jobs"]


def _release_job(jobs: dict) -> str:
    names = [
        name
        for name, job in jobs.items()
        if any("check_release_commit.py" in str(step.get("run", "")) for step in job.get("steps", []))
    ]
    assert len(names) == 1
    return names[0]


def _needs(job: dict) -> list[str]:
    needs = job.get("needs") or []
    return [needs] if isinstance(needs, str) else list(needs)


@pytest.mark.parametrize("workflow", DEPLOYS)
def test_the_release_check_precedes_every_job_that_names_an_environment(workflow):
    jobs = _jobs(workflow)
    name = _release_job(jobs)
    assert "environment" not in jobs[name]
    checkout = jobs[name]["steps"][0]["with"]
    assert checkout["fetch-depth"] == 0 and checkout["fetch-tags"] is True
    for other, job in jobs.items():
        if "environment" in job:
            assert name in _needs(job), f"{workflow} job {other} must need the release check"


@pytest.mark.parametrize("workflow", DEPLOYS)
def test_every_job_that_checks_out_the_caller_checks_out_the_release_commit_and_compares_it(workflow):
    jobs = _jobs(workflow)
    name = _release_job(jobs)
    for other, job in jobs.items():
        if other == name:
            continue
        steps     = job.get("steps", [])
        checkouts = [
            step
            for step in steps
            if str(step.get("uses", "")).startswith("actions/checkout@") and "repository" not in step.get("with", {})
        ]
        for checkout in checkouts:
            assert checkout["with"]["ref"] == "${{ needs.%s.outputs.sha }}" % name, f"{workflow} job {other}"
            after = steps[steps.index(checkout) + 1]
            assert after["env"]["RELEASE_SHA"] == "${{ needs.%s.outputs.sha }}" % name
            assert 'git rev-parse HEAD' in after["run"]
        assert "v${{ inputs.version }}" not in str([step.get("with", {}).get("ref") for step in steps])


@pytest.mark.parametrize("workflow", (*DEPLOYS, "cd-terraform.yml"))
def test_every_job_after_the_deployer_check_runs_only_for_the_login_that_started_the_run(workflow):
    # a rerun of failed jobs alone keeps the deployer check's passed result, so a rerun by another login never runs
    for name, job in _jobs(workflow).items():
        if name == "authorize":
            continue
        assert "github.actor == github.triggering_actor" in str(job.get("if", "")), f"{workflow} job {name}"


def test_no_workflow_checks_out_a_release_by_a_name_a_branch_could_take():
    # an unqualified `v1.2.3` checks out a branch of that name before the tag, and a tag ruleset guards no branch
    for path in sorted(WORKFLOWS.glob("*.yml")):
        for name, job in (yaml.safe_load(path.read_bytes().decode("utf-8")).get("jobs") or {}).items():
            for step in job.get("steps", []):
                ref = str(step.get("with", {}).get("ref", ""))
                if str(step.get("uses", "")).startswith("actions/checkout@") and ref.startswith("v"):
                    raise AssertionError(f"{path.name} job {name} checks out {ref}, name it refs/tags/{ref}")


def _bash() -> str | None:
    git_bash = Path("C:/Program Files/Git/bin/bash.exe")
    if git_bash.exists():
        return str(git_bash)
    return None if os.name == "nt" else shutil.which("bash")


def _compare_shell(workflow: str) -> str:
    jobs  = _jobs(workflow)
    steps = jobs["deploy"]["steps"]
    for index, step in enumerate(steps):
        if str(step.get("uses", "")).startswith("actions/checkout@"):
            return steps[index + 1]["run"]
    raise AssertionError("no checkout")


@pytest.mark.parametrize("workflow", DEPLOYS)
def test_a_tag_moved_after_the_check_is_caught_by_the_compare(repo, tmp_path, workflow):
    bash = _bash()
    if bash is None:
        pytest.skip("no bash to run the compare's shell")
    _git(repo, "tag", "v1.2.0", "main~1")
    ok, _, resolved = _check(repo, "1.2.0")
    assert ok
    _git(repo, "tag", "-f", "v1.2.0", "main")
    script = tmp_path / "compare.sh"
    script.write_text(_compare_shell(workflow), encoding = "utf-8", newline = "\n")
    # a checkout of the moved tag differs from the commit the check resolved, and the compare refuses it
    _git(repo, "checkout", "-q", "--detach", "v1.2.0")
    run = subprocess.run(
        [bash, "-e", script.as_posix()],
        cwd = repo,
        env = {**os.environ, "RELEASE_SHA": resolved},
        capture_output = True,
        text = True,
    )
    assert run.returncode != 0
    # a checkout of the resolved commit, what the job does, passes it
    _git(repo, "checkout", "-q", "--detach", resolved)
    run = subprocess.run(
        [bash, "-e", script.as_posix()],
        cwd = repo,
        env = {**os.environ, "RELEASE_SHA": resolved},
        capture_output = True,
        text = True,
    )
    assert run.returncode == 0, run.stdout + run.stderr
