"""
Unit tests for scripts/check_prod_gate.py.

GitHub is a dict of URL to answer, handed in as the fetch, so no network and no token. The shapes are the
ones the REST API returns for a tag ref, an annotated tag object, a workflow's runs, a run's jobs and the
repository, whose default branch a release dispatch must have run on.
"""

from __future__ import annotations

import check_prod_gate as gate
import pytest
from check_prod_gate import ApiError, decide, main

API   = "https://api.github.com"
REPO  = "Needless2Say/tiffanys-space"
SHA   = "0123456789abcdef0123456789abcdef01234567"
OTHER = "fedcba9876543210fedcba9876543210fedcba98"

REPOSITORY = f"{API}/repos/{REPO}"
WORKFLOW   = "prod-gate.yml"

# a PROD Gate run's jobs, the lanes and the last job, which needs every lane and carries the release (D-027)
RELEASE_JOBS = [
    {"name": "CI / unit-tests / Unit Tests", "conclusion": "success"},
    {"name": "E2E / E2E v0.3.7", "conclusion": "success"},
    {"name": "PROD Gate v0.3.7", "conclusion": "success"},
]

# a run whose journey passed and whose last job never did, the name D-021 read opens nothing now
JOURNEY_ALONE = [
    {"name": "E2E v0.3.7", "conclusion": "success"},
    {"name": "E2E / E2E v0.3.7", "conclusion": "success"},
]


def _ref(sha: str, kind: str = "commit") -> dict:
    return {"ref": "refs/tags/v0.3.7", "object": {"sha": sha, "type": kind}}


def _run(run_id: int, conclusion: str = "success", head_branch: str = "main") -> dict:
    return {
        "id": run_id,
        "run_number": 41,
        "conclusion": conclusion,
        "head_branch": head_branch,
        "html_url": f"https://github.com/{REPO}/actions/runs/{run_id}",
        "updated_at": "2026-09-26T20:00:00Z",
    }


def _fetch(answers: dict[str, object]):
    """
    A fetch that answers from the map, raising ApiError for a status the map names.
    """
    def fetch(url: str) -> dict:
        # the repository's own URL begins every other, so it is answered by equality and never as a prefix
        if url == REPOSITORY:
            answer = answers.get(REPOSITORY, ApiError(404, f"GitHub answered 404 for {url}"))
            if isinstance(answer, ApiError):
                raise answer
            return answer
        for prefix, answer in answers.items():
            if prefix != REPOSITORY and url.startswith(prefix):
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
    dispatched: list[dict] | None = None,
    dispatched_jobs: list[dict] | None = None,
    default_branch: str | None = "main",
    workflow: str = WORKFLOW,
) -> dict[str, object]:
    """
    ``runs`` answer the listing by the tag's commit, ``dispatched`` the listing of dispatched runs, each run's jobs
    ``jobs`` or ``dispatched_jobs``, a PROD Gate run's unless the test says otherwise. The dispatched listing's
    prefix is the longer one, so it is registered first, the fetch answers the first prefix that matches.
    """
    answers: dict[str, object] = {}
    if default_branch is not None:
        answers[REPOSITORY] = {"full_name": REPO, "default_branch": default_branch}
    if dispatched is not None:
        answers[f"{API}/repos/{REPO}/actions/workflows/{workflow}/runs?event=workflow_dispatch"] = {
            "workflow_runs": dispatched,
        }
        for run in dispatched:
            answers[f"{API}/repos/{REPO}/actions/runs/{run['id']}/jobs"] = {
                "jobs": dispatched_jobs if dispatched_jobs is not None else RELEASE_JOBS,
            }
    if tag_sha is not None:
        if annotated:
            answers[f"{API}/repos/{REPO}/git/ref/tags/v0.3.7"] = _ref("tagobject", "tag")
            answers[f"{API}/repos/{REPO}/git/tags/tagobject"] = {"object": {"sha": tag_sha, "type": "commit"}}
        else:
            answers[f"{API}/repos/{REPO}/git/ref/tags/v0.3.7"] = _ref(tag_sha)
    runs_url = f"{API}/repos/{REPO}/actions/workflows/{workflow}/runs"
    if workflow_missing:
        answers[runs_url] = ApiError(404, "GitHub answered 404 for the workflow")
    else:
        answers[runs_url] = {"workflow_runs": runs or []}
    for run in runs or []:
        answers[
            f"{API}/repos/{REPO}/actions/runs/{run['id']}/jobs"
        ] = {"jobs": jobs if jobs is not None else RELEASE_JOBS}
    return answers


def _decide(answers: dict[str, object], environment: str = "prod") -> tuple[bool, str]:
    return decide(
        _fetch(answers),
        api_url = API,
        repo = REPO,
        version = "0.3.7",
        environment = environment,
        workflow = WORKFLOW,
    )

# ======================================================================================================================
# Prod, the gate
# ======================================================================================================================

class TestProdIsGated:
    """
    On prod the gate denies whatever it cannot prove and names the run when it can.
    """
    def test_a_run_on_the_tags_commit_allows_and_names_the_run(self):
        ok, reason = _decide(_github(runs = [_run(7)]))
        assert ok is True
        assert "v0.3.7" in reason and "run #41" in reason and "actions/runs/7" in reason
        assert "on its commit" in reason and "PROD Gate v0.3.7" in reason


    @pytest.mark.parametrize("where", ["on the tag's commit", "dispatched on the default branch"])
    def test_the_journeys_own_name_opens_nothing(self, where):
        """
        Until D-027 the mark was the journey's job, ``E2E v<version>``. The journey is one lane now, and a run
        whose journey passed says nothing of the checks and the suites beside it.
        """
        if where == "on the tag's commit":
            answers = _github(runs = [_run(7)], jobs = JOURNEY_ALONE)
        else:
            answers = _github(runs = [], dispatched = [_run(9)], dispatched_jobs = JOURNEY_ALONE)
        ok, reason = _decide(answers)
        assert ok is False
        assert "No successful PROD Gate run" in reason


    def test_a_run_of_the_e2e_workflow_is_never_read(self):
        """
        A repo that holds the journey's workflow and no PROD Gate has no gate run, however green the journey is.
        """
        answers = _github(runs = [_run(7)], dispatched = [_run(9)], workflow = "e2e.yml")
        ok, reason = _decide(answers)
        assert ok is False
        assert "has no workflow prod-gate.yml" in reason


    def test_a_run_dispatched_for_the_release_counts_by_its_jobs_name(self):
        """
        The PROD Gate checks the tag out on the ref it was dispatched on and names its last job
        ``PROD Gate v<version>``. Its head is that ref, not the tag's commit, so the gate finds it by the name.
        """
        answers = _github(runs = [], dispatched = [_run(9)])
        ok, reason = _decide(answers)
        assert ok is True
        assert "actions/runs/9" in reason and "dispatched for the release on main" in reason
        assert "PROD Gate v0.3.7" in reason


    def test_a_release_dispatched_on_another_branch_does_not_count(self):
        """
        A dispatch runs the workflow of the ref it names. A branch's copy may have dropped every lane and kept
        the job's name, so the default branch, which the branch rules protect, is the one ref that counts.
        """
        answers = _github(runs = [], dispatched = [_run(9, head_branch = "skip-the-lanes")])
        ok, reason = _decide(answers)
        assert ok is False
        assert "No successful PROD Gate run" in reason and "another branch" in reason


    def test_the_default_branch_is_the_repositorys_own_and_not_a_name(self):
        answers = _github(runs = [], dispatched = [_run(9, head_branch = "trunk")], default_branch = "trunk")
        ok, reason = _decide(answers)
        assert ok is True
        assert "dispatched for the release on trunk" in reason

        answers = _github(runs = [], dispatched = [_run(9, head_branch = "main")], default_branch = "trunk")
        ok, _ = _decide(answers)
        assert ok is False


    def test_the_newest_trusted_release_dispatch_is_taken_past_one_that_is_not(self):
        answers = _github(runs = [], dispatched = [_run(9, head_branch = "skip-the-lanes"), _run(8)])
        ok, reason = _decide(answers)
        assert ok is True
        assert "actions/runs/8" in reason


    def test_a_repository_that_cannot_be_read_denies_and_is_not_a_missing_workflow(self):
        answers = _github(runs = [], dispatched = [_run(9)], default_branch = None)
        ok, reason = _decide(answers)
        assert ok is False
        assert "could not ask GitHub" in reason and "has no workflow" not in reason


    def test_a_repository_without_a_default_branch_counts_no_dispatch(self):
        """
        GitHub names no head branch for some runs. No default branch and no head branch are not the same branch.
        """
        run = _run(9)
        run["head_branch"] = None
        ok, _ = _decide(_github(runs = [], dispatched = [run], default_branch = ""))
        assert ok is False


    @pytest.mark.parametrize("where", ["on the tag's commit", "dispatched on the default branch"])
    def test_a_run_for_another_release_does_not_count(self, where):
        """
        Two releases can share a commit's run listing, a dispatch for 0.3.6 made while main's head was the commit
        0.3.7 was later tagged on. The name is asked of a run on the tag's commit too.
        """
        jobs = [{"name": "PROD Gate v0.3.6", "conclusion": "success"}]
        if where == "on the tag's commit":
            answers = _github(runs = [_run(7)], jobs = jobs)
        else:
            answers = _github(runs = [], dispatched = [_run(9)], dispatched_jobs = jobs)
        ok, reason = _decide(answers)
        assert ok is False
        assert "No successful PROD Gate run" in reason


    def test_a_run_whose_last_job_was_skipped_does_not_count(self):
        answers = _github(
            runs = [],
            dispatched = [_run(9)],
            dispatched_jobs = [{"name": "PROD Gate v0.3.7", "conclusion": "skipped"}],
        )
        ok, _ = _decide(answers)
        assert ok is False


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
        assert "has no workflow prod-gate.yml" in reason


    def test_no_run_for_the_commit_denies_and_says_how_to_get_one(self):
        ok, reason = _decide(_github(runs = []))
        assert ok is False
        assert "No successful PROD Gate run" in reason and "version 0.3.7" in reason
        assert "Actions, PROD Gate, Run workflow, on the default branch" in reason


    def test_a_run_whose_every_job_was_skipped_does_not_count(self):
        """
        A run answered as success with no job that ran is refused.
        """
        jobs = [{"name": "PROD Gate v0.3.7", "conclusion": "skipped"}]
        ok, reason = _decide(_github(runs = [_run(7)], jobs = jobs))
        assert ok is False
        assert "No successful PROD Gate run" in reason


    def test_a_run_whose_lanes_passed_and_whose_last_job_did_not_run_does_not_count(self):
        jobs = [
            {"name": "CI / unit-tests / Unit Tests", "conclusion": "success"},
            {"name": "E2E / E2E v0.3.7", "conclusion": "success"},
            {"name": "PROD Gate v0.3.7", "conclusion": "skipped"},
        ]
        ok, _ = _decide(_github(runs = [_run(7)], jobs = jobs))
        assert ok is False


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
        assert "passed the PROD Gate" in reason


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
        monkeypatch.delenv("PROD_GATE_WORKFLOW", raising = False)
        monkeypatch.setattr(gate, "github_fetch", _fetch(_github(runs = [_run(7)])))
        assert main(["--repo", REPO, "--version", "v0.3.7", "--environment", "prod"]) == 0
        out = capsys.readouterr().out
        assert out.startswith("OK: v0.3.7")
        assert summary.read_text(encoding = "utf-8").startswith("### PROD gate (prod)\n\nOK: v0.3.7")


    def test_the_workflow_read_is_the_prod_gate_unless_another_is_named(self, monkeypatch):
        """
        The journey's workflow holds green release runs from before D-027, each with a job the old gate read.
        Nothing names that workflow now, so none of them opens PROD.
        """
        monkeypatch.delenv("GITHUB_STEP_SUMMARY", raising = False)
        monkeypatch.delenv("PROD_GATE_WORKFLOW", raising = False)
        monkeypatch.delenv("E2E_WORKFLOW", raising = False)
        monkeypatch.setattr(gate, "github_fetch", _fetch(_github(runs = [_run(7)], workflow = "e2e.yml")))
        arguments = ["--repo", REPO, "--version", "0.3.7", "--environment", "prod"]
        assert main(arguments) == 1
        # the variable the old gate read names nothing here
        monkeypatch.setenv("E2E_WORKFLOW", "e2e.yml")
        assert main(arguments) == 1
        monkeypatch.setenv("PROD_GATE_WORKFLOW", "e2e.yml")
        assert main(arguments) == 0, "another file is read only when the deploy names it"


    def test_a_denial_exits_one(self, monkeypatch):
        monkeypatch.delenv("GITHUB_STEP_SUMMARY", raising = False)
        monkeypatch.delenv("PROD_GATE_WORKFLOW", raising = False)
        monkeypatch.setattr(gate, "github_fetch", _fetch(_github(runs = [])))
        assert main(["--repo", REPO, "--version", "0.3.7", "--environment", "prod"]) == 1
