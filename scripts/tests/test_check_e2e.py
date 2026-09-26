"""
Unit tests for scripts/check_e2e.py.

GitHub is a dict of URL to answer, handed in as the fetch, so no network and no token. The shapes are the
ones the REST API returns for a tag ref, an annotated tag object, a workflow's runs and a run's jobs.
"""

from __future__ import annotations

import check_e2e as ce
import pytest
from check_e2e import ApiError, decide, main

API   = "https://api.github.com"
REPO  = "Needless2Say/tiffanys-space"
SHA   = "0123456789abcdef0123456789abcdef01234567"
OTHER = "fedcba9876543210fedcba9876543210fedcba98"


def _ref(sha: str, kind: str = "commit") -> dict:
    return {"ref": "refs/tags/v0.3.7", "object": {"sha": sha, "type": kind}}


def _run(run_id: int, conclusion: str = "success") -> dict:
    return {
        "id": run_id,
        "run_number": 41,
        "conclusion": conclusion,
        "html_url": f"https://github.com/{REPO}/actions/runs/{run_id}",
        "updated_at": "2026-09-26T20:00:00Z",
    }


def _fetch(answers: dict[str, object]):
    """
    A fetch that answers from the map, raising ApiError for a status the map names.
    """
    def fetch(url: str) -> dict:
        for prefix, answer in answers.items():
            if url.startswith(prefix):
                if isinstance(answer, ApiError):
                    raise answer
                return answer
        raise ApiError(404, f"GitHub answered 404 for {url}")


    return fetch


def _github(
    *,
    tag_sha: str | None = SHA,
    runs: list[dict] | None = None,
    jobs: list[dict] | None = None,
    annotated: bool = False,
    workflow_missing: bool = False,
) -> dict[str, object]:
    answers: dict[str, object] = {}
    if tag_sha is not None:
        if annotated:
            answers[f"{API}/repos/{REPO}/git/ref/tags/v0.3.7"] = _ref("tagobject", "tag")
            answers[f"{API}/repos/{REPO}/git/tags/tagobject"] = {"object": {"sha": tag_sha, "type": "commit"}}
        else:
            answers[f"{API}/repos/{REPO}/git/ref/tags/v0.3.7"] = _ref(tag_sha)
    runs_url = f"{API}/repos/{REPO}/actions/workflows/e2e.yml/runs"
    if workflow_missing:
        answers[runs_url] = ApiError(404, "GitHub answered 404 for the workflow")
    else:
        answers[runs_url] = {"workflow_runs": runs or []}
    for run in runs or []:
        answers[
            f"{API}/repos/{REPO}/actions/runs/{run['id']}/jobs"
        ] = {"jobs": jobs if jobs is not None else [{"name": "e2e", "conclusion": "success"}]}
    return answers


def _decide(answers: dict[str, object], environment: str = "prod") -> tuple[bool, str]:
    return decide(
        _fetch(answers),
        api_url = API,
        repo = REPO,
        version = "0.3.7",
        environment = environment,
        workflow = "e2e.yml",
    )

# ======================================================================================================================
# Prod, the gate
# ======================================================================================================================

class TestProdIsGated:
    """
    On prod the gate denies whatever it cannot prove and names the run when it can.
    """
    def test_a_green_run_on_the_tags_commit_allows_and_names_the_run(self):
        ok, reason = _decide(_github(runs = [_run(7)]))
        assert ok is True
        assert "v0.3.7" in reason and "run #41" in reason and f"actions/runs/7" in reason


    def test_an_annotated_tag_is_followed_to_its_commit(self):
        ok, reason = _decide(_github(runs = [_run(7)], annotated = True))
        assert ok is True
        assert SHA[:12] in reason


    def test_no_tag_denies(self):
        ok, reason = _decide(_github(tag_sha = None))
        assert ok is False
        assert "no tag v0.3.7" in reason


    def test_no_workflow_denies(self):
        ok, reason = _decide(_github(workflow_missing = True))
        assert ok is False
        assert "has no workflow e2e.yml" in reason


    def test_no_run_for_the_commit_denies_and_says_how_to_get_one(self):
        ok, reason = _decide(_github(runs = []))
        assert ok is False
        assert "No successful E2E run" in reason and "ref v0.3.7" in reason


    def test_a_run_whose_every_job_was_skipped_does_not_count(self):
        """
        The dormant modes skip the job, GitHub then reports the run skipped, and a success filter never
        returns it, but a run answered as success with no job that ran is refused here too.
        """
        ok, reason = _decide(_github(runs = [_run(7)], jobs = [{"name": "e2e", "conclusion": "skipped"}]))
        assert ok is False
        assert "No successful E2E run" in reason


    def test_a_run_not_reported_success_does_not_count(self):
        ok, _ = _decide(_github(runs = [_run(7, conclusion = "failure")]))
        assert ok is False


    def test_an_api_failure_denies_and_names_the_permission(self):
        answers = _github(runs = [_run(7)])
        answers[f"{API}/repos/{REPO}/git/ref/tags/v0.3.7"] = ApiError(403, "GitHub answered 403")
        ok, reason = _decide(answers)
        assert ok is False
        assert "actions: read" in reason

# ======================================================================================================================
# Dev, reported and never denied
# ======================================================================================================================

class TestDevIsReported:
    """
    On dev the same lookup is reported and never denies, only an API failure does.
    """
    @pytest.mark.parametrize("answers", [
        _github(tag_sha = None),
        _github(workflow_missing = True),
        _github(runs = []),
    ], ids = ["no-tag", "no-workflow", "no-run"])
    def test_dev_is_allowed_and_told(self, answers):
        ok, reason = _decide(answers, environment = "dev")
        assert ok is True
        assert "the gate applies to prod" in reason


    def test_dev_with_a_green_run_says_so(self):
        ok, reason = _decide(_github(runs = [_run(7)]), environment = "dev")
        assert ok is True
        assert "passed E2E" in reason


    def test_an_api_failure_denies_dev_too(self):
        answers = _github()
        answers[f"{API}/repos/{REPO}/git/ref/tags/v0.3.7"] = ApiError(0, "GitHub could not be reached")
        ok, _ = _decide(answers, environment = "dev")
        assert ok is False

# ======================================================================================================================
# The CLI
# ======================================================================================================================

class TestMain:
    """
    The CLI, its inputs, its exit code and the step summary line.
    """
    def test_missing_inputs_deny(self, monkeypatch, capsys):
        for name in ("DEPLOY_REPO", "GITHUB_REPOSITORY", "DEPLOY_VERSION", "DEPLOY_ENVIRONMENT", "GITHUB_STEP_SUMMARY"):
            monkeypatch.delenv(name, raising = False)
        assert main([]) == 1
        assert "DENIED: missing repo, version, environment" in capsys.readouterr().out


    def test_the_verdict_reaches_the_step_summary(self, monkeypatch, tmp_path, capsys):
        summary = tmp_path / "summary.md"
        monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(summary))
        monkeypatch.setattr(ce, "github_fetch", _fetch(_github(runs = [_run(7)])))
        assert main(["--repo", REPO, "--version", "v0.3.7", "--environment", "prod"]) == 0
        out = capsys.readouterr().out
        assert out.startswith("OK: v0.3.7")
        assert summary.read_text(encoding = "utf-8").startswith("### E2E gate (prod)\n\nOK: v0.3.7")


    def test_a_denial_exits_one(self, monkeypatch):
        monkeypatch.delenv("GITHUB_STEP_SUMMARY", raising = False)
        monkeypatch.setattr(ce, "github_fetch", _fetch(_github(runs = [])))
        assert main(["--repo", REPO, "--version", "0.3.7", "--environment", "prod"]) == 1
