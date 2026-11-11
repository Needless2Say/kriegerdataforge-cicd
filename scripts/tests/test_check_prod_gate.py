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

# a repo's tag ruleset date, and the start times of a gate run before and after it
RULESET_DATE = "2026-11-10T12:00:00Z"
BEFORE       = "2026-11-09T08:00:00Z"
AFTER        = "2026-11-11T08:00:00Z"

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

# ======================================================================================================================
# The gate's evidence bound to the commit and the tag ruleset's date
# ======================================================================================================================

def _started(run: dict, when: str) -> dict:
    return {**run, "run_started_at": when, "created_at": when}


def _bound(answers: dict[str, object], expected: str | None, date: str | None, environment: str = "prod"):
    return decide(
        _fetch(answers),
        api_url = API,
        repo = REPO,
        version = "0.3.7",
        environment = environment,
        workflow = WORKFLOW,
        expected_commit = expected,
        ruleset_date = date,
    )


class TestEvidence:
    """
    The expected commit and the ruleset date, each lookup held to a run begun after it.
    """
    def test_an_expected_commit_the_tag_names_keeps_todays_rule_until_the_repo_has_a_date(self):
        ok, reason = _bound(_github(runs = [_started(_run(7), BEFORE)]), SHA, None)
        assert ok, reason


    def test_a_tag_that_moved_from_the_expected_commit_is_denied(self):
        ok, reason = _bound(_github(tag_sha = OTHER, runs = [_run(7)]), SHA, None)
        assert not ok
        assert "moved" in reason


    def test_a_tag_that_moved_is_only_noted_on_dev(self):
        assert _bound(_github(tag_sha = OTHER, runs = [_run(7)]), SHA, None, environment = "dev")[0]


    def test_codexs_counterexample_a_run_found_by_its_head_before_the_ruleset_is_refused(self):
        """
        A dispatch on main whose head was A while the tag named B tested B. Once the tag moved to A, a deploy expecting
        A finds that run by its head A. It began before the tag ruleset was read back, so it proves nothing.
        """
        ok, reason = _bound(_github(runs = [_started(_run(7), BEFORE)]), SHA, RULESET_DATE)
        assert not ok
        assert RULESET_DATE in reason


    def test_a_dispatched_run_on_main_before_the_ruleset_is_refused(self):
        answers = _github(runs = [], dispatched = [_started(_run(9), BEFORE)])
        assert not _bound(answers, SHA, RULESET_DATE)[0]


    @pytest.mark.parametrize("lookup", ["head", "dispatched"])
    def test_a_run_begun_after_the_ruleset_is_accepted_by_either_lookup(self, lookup):
        run     = _started(_run(9), AFTER)
        answers = _github(runs = [run]) if lookup == "head" else _github(runs = [], dispatched = [run])
        ok, reason = _bound(answers, SHA, RULESET_DATE)
        assert ok, reason


    @pytest.mark.parametrize("lookup", ["head", "dispatched"])
    def test_a_run_created_before_the_ruleset_and_rerun_after_it_is_refused(self, lookup):
        """
        Codex's second counterexample. A rerun of the verdict job alone after the date keeps the lanes' results from
        the first attempt, which tested whatever the tag named then, so the latest attempt's start proves nothing.
        """
        run     = {**_run(7), "created_at": BEFORE, "run_started_at": AFTER, "run_attempt": 2}
        answers = _github(runs = [run]) if lookup == "head" else _github(runs = [], dispatched = [run])
        assert not _bound(answers, SHA, RULESET_DATE)[0]


    def test_a_newer_run_is_found_past_an_older_one(self):
        answers = _github(runs = [_started(_run(7), BEFORE), _started(_run(8), AFTER)])
        ok, reason = _bound(answers, SHA, RULESET_DATE)
        assert ok and "run #41" in reason


    def test_a_run_with_no_start_time_is_refused_once_a_date_binds(self):
        assert not _bound(_github(runs = [_run(7)]), SHA, RULESET_DATE)[0]


    def test_without_an_expected_commit_a_date_binds_nothing(self):
        assert _bound(_github(runs = [_started(_run(7), BEFORE)]), None, RULESET_DATE)[0]


    @pytest.mark.parametrize("expected", ["abc", SHA.upper() + "0", "not-a-sha"])
    def test_an_expected_commit_that_is_no_commit_is_denied(self, expected):
        assert not _bound(_github(runs = [_run(7)]), expected, None)[0]


class TestRulesetDates:
    """
    The dates file the fence fills, read by main for the repo it deploys.
    """
    def test_the_shipped_file_reads(self):
        dates = gate.load_ruleset_dates()
        assert isinstance(dates, dict)
        for repo, when in dates.items():
            assert "/" in repo and gate.parse_time(when) is not None


    @pytest.mark.parametrize("repo", [
        "kriegerdataforge",
        "kriegerdataforge-auth-ui",
        "fitness-app-backend",
        "fitness-app-frontend",
        "tiffanys-space",
        "tiffanys-space-backend",
    ])
    def test_each_repo_that_runs_a_prod_gate_holds_its_date_from_the_settings_read_back(self, repo):
        # the secrets fence's step 4 set both rulesets and read them back, 2026-11-06 from 14:15:40 UTC
        when = gate.parse_time(gate.load_ruleset_dates()[f"Needless2Say/{repo}"])
        assert when is not None and when >= gate.parse_time("2026-11-06T14:15:40+00:00")


    def test_a_repo_with_no_date_reads_none(self, tmp_path):
        path = tmp_path / "dates.json"
        path.write_text('{"dates": {"Needless2Say/other": "' + RULESET_DATE + '"}}', encoding = "utf-8")
        assert gate.load_ruleset_dates(path).get(REPO) is None
        assert gate.load_ruleset_dates(path)["Needless2Say/other"] == RULESET_DATE


    def test_main_reads_the_expected_commit_and_the_repos_date(self, monkeypatch, tmp_path):
        path = tmp_path / "dates.json"
        path.write_text('{"dates": {"' + REPO + '": "' + RULESET_DATE + '"}}', encoding = "utf-8")
        monkeypatch.setattr(gate, "RULESET_DATES_FILE", path)
        monkeypatch.delenv("GITHUB_STEP_SUMMARY", raising = False)
        monkeypatch.delenv("PROD_GATE_WORKFLOW", raising = False)
        monkeypatch.setenv("EXPECTED_COMMIT", SHA)
        monkeypatch.setattr(gate, "github_fetch", _fetch(_github(runs = [_started(_run(7), BEFORE)])))
        arguments = ["--repo", REPO, "--version", "0.3.7", "--environment", "prod"]
        assert main(arguments) == 1
        monkeypatch.setattr(gate, "github_fetch", _fetch(_github(runs = [_started(_run(7), AFTER)])))
        assert main(arguments) == 0


    def test_an_unreadable_dates_file_denies(self, monkeypatch, tmp_path, capsys):
        path = tmp_path / "dates.json"
        path.write_text("{not json", encoding = "utf-8")
        monkeypatch.setattr(gate, "RULESET_DATES_FILE", path)
        monkeypatch.delenv("GITHUB_STEP_SUMMARY", raising = False)
        monkeypatch.setenv("EXPECTED_COMMIT", SHA)
        monkeypatch.setattr(gate, "github_fetch", _fetch(_github(runs = [_run(7)])))
        assert main(["--repo", REPO, "--version", "0.3.7", "--environment", "prod"]) == 1
        assert "ruleset dates" in capsys.readouterr().out

# ======================================================================================================================
# The named gate run, and the structured output (terraform in Actions, design 5.7, Round Table 81, L6)
# ======================================================================================================================

def _named(
    run: dict,
    *,
    jobs: list[dict] | None = None,
    runs: list[dict] | None = None,
    path: str = f".github/workflows/{WORKFLOW}",
) -> dict[str, object]:
    """
    GitHub answering for one named run, its jobs registered before the run itself, since the run's URL is a prefix of
    its jobs' and the fetch answers the first prefix that matches.
    """
    answers = _github(runs = runs or [])
    answers[f"{API}/repos/{REPO}/actions/runs/{run['id']}/jobs"] = {"jobs": jobs if jobs is not None else RELEASE_JOBS}
    answers[f"{API}/repos/{REPO}/actions/runs/{run['id']}"] = {"path": path, "run_attempt": 1, **run}
    return answers


def _decide_run(answers: dict[str, object], gate_run: str | None, environment: str = "prod", **kwargs):
    return gate.decide_run(
        _fetch(answers),
        api_url = API,
        repo = REPO,
        version = "0.3.7",
        environment = environment,
        workflow = WORKFLOW,
        gate_run = gate_run,
        **kwargs,
    )


class TestTheNamedGateRun:
    """
    With a named run the checker judges that run alone by the same rules, today's rule kept when none is named.
    """
    def test_a_named_run_on_the_tags_commit_is_allowed_and_described(self):
        ok, reason, run = _decide_run(_named({**_run(9), "head_sha": SHA}), "9")
        assert ok is True
        assert "run #41" in reason
        assert run == {"run_id": "9", "run_attempt": "1", "commit": SHA}


    def test_a_later_gate_dispatched_after_main_moved_is_named_and_allowed(self):
        # an earlier gate on the tag's commit passed too, and today's pick would return it, the named one is judged
        named   = {**_run(12), "head_sha": OTHER, "event": "workflow_dispatch"}
        answers = _named(named, runs = [_run(7)])
        ok, _, run = _decide_run(answers, "12")
        assert ok is True
        assert run["run_id"] == "12"


    def test_a_named_run_whose_release_job_did_not_pass_is_denied(self):
        failed = [{"name": "PROD Gate v0.3.7", "conclusion": "failure"}]
        ok, reason, run = _decide_run(_named({**_run(9), "head_sha": SHA}, jobs = failed), "9")
        assert ok is False
        assert run is None
        assert "PROD Gate v0.3.7" in reason


    def test_a_named_run_that_did_not_succeed_is_denied(self):
        ok, _, _ = _decide_run(_named({**_run(9, conclusion = "failure"), "head_sha": SHA}), "9")
        assert ok is False


    def test_a_named_run_of_another_workflow_is_denied(self):
        answers = _named({**_run(9), "head_sha": SHA}, path = ".github/workflows/e2e.yml")
        ok, reason, _ = _decide_run(answers, "9")
        assert ok is False
        assert "e2e.yml" in reason


    def test_a_named_run_on_another_branch_with_another_head_is_denied(self):
        answers = _named({**_run(9, head_branch = "feature/x"), "head_sha": OTHER})
        ok, reason, _ = _decide_run(answers, "9")
        assert ok is False
        assert "feature/x" in reason


    def test_a_named_run_begun_before_the_ruleset_date_is_denied(self):
        named = {**_run(9), "head_sha": SHA, "created_at": BEFORE}
        ok, _, _ = _decide_run(_named(named), "9", expected_commit = SHA, ruleset_date = RULESET_DATE)
        assert ok is False
        later = {**_run(9), "head_sha": SHA, "created_at": AFTER}
        ok, _, _ = _decide_run(_named(later), "9", expected_commit = SHA, ruleset_date = RULESET_DATE)
        assert ok is True


    def test_a_named_run_github_does_not_know_is_denied(self):
        ok, reason, _ = _decide_run(_github(runs = []), "9")
        assert ok is False
        assert "run 9" in reason


    def test_a_named_run_that_is_no_number_is_denied(self):
        ok, reason, _ = _decide_run(_named({**_run(9), "head_sha": SHA}), "9; rm")
        assert ok is False
        assert "no run id" in reason


    def test_the_tag_moved_since_the_resolution_is_denied_with_a_named_run(self):
        ok, _, _ = _decide_run(_named({**_run(9), "head_sha": SHA}), "9", expected_commit = OTHER)
        assert ok is False


    def test_on_dev_a_failed_named_run_is_noted_and_allowed(self):
        failed = [{"name": "PROD Gate v0.3.7", "conclusion": "failure"}]
        ok, _, run = _decide_run(_named({**_run(9), "head_sha": SHA}, jobs = failed), "9", environment = "dev")
        assert ok is True
        assert run is None


    def test_without_a_named_run_todays_rule_is_kept_and_its_run_described(self):
        ok, _, run = _decide_run(_github(runs = [{**_run(7), "run_attempt": 2}]), None)
        assert ok is True
        assert run == {"run_id": "7", "run_attempt": "2", "commit": SHA}


    def test_decide_keeps_its_two_part_answer(self):
        ok, reason = _decide(_github(runs = [_run(7)]))
        assert ok is True
        assert isinstance(reason, str)


class TestTheStructuredOutput:
    """
    main writes the run, its attempt and its commit to the step's outputs when the deploy may proceed on a run.
    """
    def _main(self, monkeypatch, tmp_path, answers, *extra):
        out = tmp_path / "out"
        out.write_text("", encoding = "utf-8")
        monkeypatch.setenv("GITHUB_OUTPUT", str(out))
        monkeypatch.delenv("GITHUB_STEP_SUMMARY", raising = False)
        monkeypatch.delenv("PROD_GATE_WORKFLOW", raising = False)
        monkeypatch.delenv("GATE_RUN_ID", raising = False)
        monkeypatch.delenv("EXPECTED_COMMIT", raising = False)
        monkeypatch.setattr(gate, "github_fetch", _fetch(answers))
        code = main(["--repo", REPO, "--version", "0.3.7", "--environment", "prod", *extra])
        return code, out.read_text(encoding = "utf-8")


    def test_an_allowed_named_run_writes_its_id_attempt_and_commit(self, monkeypatch, tmp_path):
        code, out = self._main(monkeypatch, tmp_path, _named({**_run(9), "head_sha": SHA}), "--gate-run", "9")
        assert code == 0
        assert out.splitlines() == ["gate_run_id=9", "gate_run_attempt=1", "gate_commit=" + SHA]


    def test_the_named_run_falls_back_to_its_variable(self, monkeypatch, tmp_path):
        answers = _named({**_run(9), "head_sha": SHA})
        out     = tmp_path / "out"
        out.write_text("", encoding = "utf-8")
        monkeypatch.setenv("GITHUB_OUTPUT", str(out))
        monkeypatch.delenv("GITHUB_STEP_SUMMARY", raising = False)
        monkeypatch.delenv("PROD_GATE_WORKFLOW", raising = False)
        monkeypatch.delenv("EXPECTED_COMMIT", raising = False)
        monkeypatch.setenv("GATE_RUN_ID", "9")
        monkeypatch.setattr(gate, "github_fetch", _fetch(answers))
        assert main(["--repo", REPO, "--version", "0.3.7", "--environment", "prod"]) == 0
        assert "gate_run_id=9" in out.read_text(encoding = "utf-8")


    def test_a_denial_writes_no_output(self, monkeypatch, tmp_path):
        failed = [{"name": "PROD Gate v0.3.7", "conclusion": "failure"}]
        code, out = self._main(
            monkeypatch,
            tmp_path,
            _named({**_run(9), "head_sha": SHA}, jobs = failed),
            "--gate-run",
            "9",
        )
        assert code == 1
        assert out == ""
