"""
E2E gate for the KriegerDataForge CD workflows, a release deploys to PROD only after its full release
test suite passed on that release, unit, integration, mutation where the repo has it, and E2E last.

Every repo with a deploy owns one E2E journey (`.github/workflows/e2e.yml`, the `run-e2e` action). A
release dispatch of that workflow (the `version` input, D-021) runs the repo's unit and integration
lanes, and its mutation lane where one exists, ahead of the E2E job itself, each gated so the E2E job
only runs once they all passed (D-024). This gate asks GitHub whether that workflow has a successful
run for the exact commit the release tag names, `v<version>`, the commit the deploy job checks out, and
whose own E2E job ran and passed. Since the E2E job depends on the earlier lanes, its pass already
certifies the rest of the suite passed too, one lookup answers for the whole release. The `verify-e2e`
job in `cd-nextjs-vercel.yml` and `cd-python-vercel.yml` runs it after the deployer authorization and
before the deploy job, the same place and the same shape as `check_deployer.py`, so a PROD deploy of an
untested or partially tested release fails closed with the reason, and a deploy of a tested one records
which run tested it in the step summary.

Decision, for `prod`:
  - no tag v<version>                              -> DENY  (exit 1, fail closed)
  - the repo has no E2E workflow                   -> DENY  (exit 1)
  - no successful release dispatch for the version -> DENY  (exit 1)
  - the run's `E2E v<version>` job did not pass    -> DENY  (exit 1)
  - a successful run whose `E2E v<version>` passed -> ALLOW (exit 0), the run named in the summary
For `dev` the same lookup runs and its result is reported, and the deploy is never denied, DEV is the
soak that comes before the E2E dispatch on the release.

A run counts only when GitHub reports it `success` and its passed job is named `E2E v<version>`, the name
a run dispatched with the workflow's `version` input gives its job after checking the tag out (D-021).
That input is the one that runs the unit, integration and mutation lanes as jobs the e2e job needs
(D-024), so the name is the proof the whole suite ran. A failure in any lane fails the run, GitHub never
reports it `success`, and this check denies without needing to know those lanes' job names. A run with
the input empty names its job `E2E` and skips every lane, so it does not count, not on the tag's own
commit either, which D-019 and D-021 counted (D-024). A run whose e2e job was skipped (the dormant
modes, RUN_E2E_GATE and RUN_E2E_CD unset) reports `skipped`, not `success`, and does not count.

The workflow a run ran is the one on the ref it was dispatched on, so the ref is held too. A run counts
when its head is the tag's commit, the release's own workflow, or when it was dispatched on the
repository's default branch, which the branch rules protect. A dispatch on any other branch does not
count, that branch's copy of the workflow may have dropped a lane and kept the job's name.

Inputs (CLI flags take precedence over environment variables):
  --repo         / DEPLOY_REPO        / GITHUB_REPOSITORY            e.g. "Needless2Say/fitness-app-frontend"
  --version      / DEPLOY_VERSION                                    e.g. "1.2.0", the tag is v1.2.0
  --environment  / DEPLOY_ENVIRONMENT                                "dev" or "prod"
  --workflow     / E2E_WORKFLOW                                      the workflow file, default e2e.yml
  GH_TOKEN / GITHUB_TOKEN                                            a token with actions: read on the repo
  GITHUB_API_URL                                                     default https://api.github.com

Usage:
    python3 check_e2e.py
    python3 check_e2e.py --repo Needless2Say/tiffanys-space --version 0.3.7 --environment prod

Requirements: standard library only (no pip install).
"""

from __future__ import annotations

# standard imports
import argparse
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable

# ======================================================================================================================
# Configuration
# ======================================================================================================================

DEFAULT_WORKFLOW: str = "e2e.yml"
DEFAULT_API_URL:  str = "https://api.github.com"
API_TIMEOUT:      int = 30

# the job name a release dispatch gives itself, the E2E workflow's `version` input (D-021)
RELEASE_JOB_NAME: str = "E2E v{version}"

# how many dispatched runs are searched for that job name, newest first
DISPATCHED_RUNS_SEARCHED: int = 30

# the states a deploy names, the gate denies on the second alone
ENVIRONMENT_DEV:  str = "dev"
ENVIRONMENT_PROD: str = "prod"

# a fetch answers the parsed JSON body, or raises ApiError with the status
Fetch = Callable[[str], dict]

# the CLI's help tail, the variables each flag falls back to
EPILOG: str = "\n".join((
    "Values fall back to environment variables when flags are omitted:",
    "  --repo         <- DEPLOY_REPO / GITHUB_REPOSITORY",
    "  --version      <- DEPLOY_VERSION",
    "  --environment  <- DEPLOY_ENVIRONMENT",
    "  --workflow     <- E2E_WORKFLOW (default e2e.yml)",
))

# ======================================================================================================================
# The API
# ======================================================================================================================

class ApiError(Exception):
    """
    GitHub answered something other than 200, the status rides along.
    """
    def __init__(self, status: int, message: str) -> None:
        """
        Keep the status beside the message, a 404 is a decision and any other status is a failure to ask.

        Args:
            status: The HTTP status, 0 when GitHub could not be reached
            message: What happened, for the log line
        """
        super().__init__(message)
        self.status = status


def github_fetch(url: str) -> dict:
    """
    GET one GitHub API URL with the job's token and parse its JSON answer.

    Args:
        url: The full URL

    Returns:
        The parsed body

    Raises:
        ApiError: On any status but 200, or when GitHub cannot be reached
    """
    token   = os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN") or ""
    headers = {"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    request = urllib.request.Request(url, headers = headers)
    try:
        with urllib.request.urlopen(request, timeout = API_TIMEOUT) as answer:
            return json.loads(answer.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        raise ApiError(exc.code, f"GitHub answered {exc.code} for {url}") from exc
    except (urllib.error.URLError, TimeoutError) as exc:
        raise ApiError(0, f"GitHub could not be reached for {url}: {exc}") from exc

# ======================================================================================================================
# The lookup
# ======================================================================================================================

def tag_commit(fetch: Fetch, api_url: str, repo: str, tag: str) -> str | None:
    """
    Resolve a tag to the commit it names, through an annotated tag object when there is one.

    Args:
        fetch: The API reader
        api_url: The API base
        repo: owner/name
        tag: The tag name, v1.2.0

    Returns:
        The commit sha, or None when the tag does not exist
    """
    try:
        ref = fetch(f"{api_url}/repos/{repo}/git/ref/tags/{urllib.parse.quote(tag)}")
    except ApiError as exc:
        if exc.status == 404:
            return None
        raise
    target = ref.get("object") or {}
    if target.get("type") == "tag":
        tag_object = fetch(f"{api_url}/repos/{repo}/git/tags/{target['sha']}")
        target     = tag_object.get("object") or {}
    return target.get("sha") or None


def default_branch(fetch: Fetch, api_url: str, repo: str) -> str | None:
    """
    The repository's default branch, the one ref besides the tag whose workflow a release dispatch may run.

    Args:
        fetch: The API reader
        api_url: The API base
        repo: owner/name

    Returns:
        The branch name, or None when GitHub names none

    Raises:
        ApiError: With status 0 when the repository cannot be read, a 404 here is never a missing workflow
    """
    try:
        return fetch(f"{api_url}/repos/{repo}").get("default_branch") or None
    except ApiError as exc:
        if exc.status == 404:
            raise ApiError(0, f"GitHub answered 404 for the repository {repo} itself") from exc
        raise


def _passed_jobs(fetch: Fetch, api_url: str, repo: str, run: dict) -> list[dict]:
    """
    The jobs of one successful run that ran and passed.

    Args:
        fetch: The API reader
        api_url: The API base
        repo: owner/name
        run: The run, as the runs listing returned it

    Returns:
        The jobs whose conclusion is success, empty when every job was skipped
    """
    if run.get("conclusion") != "success":
        return []
    jobs = fetch(f"{api_url}/repos/{repo}/actions/runs/{run['id']}/jobs?per_page=100").get("jobs") or []
    # the workflow can only be success when no job failed, but every job may have been skipped, which
    # GitHub reports as a skipped workflow, so this keeps the jobs that actually ran and passed
    return [job for job in jobs if job.get("conclusion") == "success"]


def successful_run(
    fetch: Fetch,
    api_url: str,
    repo: str,
    workflow: str,
    sha: str,
    version: str,
) -> tuple[dict, str] | None:
    """
    Find the newest successful release dispatch of the E2E workflow for one release, and say how it was found.

    A run counts when its passed job is named after the release, ``E2E v<version>``, the name the workflow's
    ``version`` input gives it (D-021), the same input that runs the rest of the suite ahead of it (D-024).
    The workflow it ran must be one to trust, the release's own, its head the tag's commit, or the default
    branch's.

    Args:
        fetch: The API reader
        api_url: The API base
        repo: owner/name
        workflow: The workflow file name
        sha: The tag's commit
        version: The release version, without the v

    Returns:
        ``(run, how)``, ``how`` a phrase for the verdict, or None when there is none

    Raises:
        ApiError: With status 404 when the repo has no such workflow
    """
    runs_url = f"{api_url}/repos/{repo}/actions/workflows/{urllib.parse.quote(workflow)}/runs"
    wanted   = RELEASE_JOB_NAME.format(version = version)


    def tested_the_release(run: dict) -> bool:
        """
        Whether a run's passed jobs hold the one named after the release.

        Args:
            run: The run, as the runs listing returned it

        Returns:
            True when the job ran and passed
        """
        return any(job.get("name") == wanted for job in _passed_jobs(fetch, api_url, repo, run))


    # a run on the tag's commit ran the workflow the release itself carries. one with the version input empty
    # is on that commit too, a push to the default branch or a dispatch on the tag, and ran no lane but the
    # journey, so the name is asked of it as well
    query = urllib.parse.urlencode({"head_sha": sha, "status": "success", "per_page": 20})
    for run in fetch(f"{runs_url}?{query}").get("workflow_runs") or []:
        if tested_the_release(run):
            return run, f"on its commit, its job named {wanted}"

    # a release dispatched once the default branch moved on has another head. the name is what the workflow
    # gave itself from the same input that chose the checkout, so the job that passed is the one that tested
    # the tag. the ref it ran on is the default branch alone, another branch's workflow is anyone's to write
    query      = urllib.parse.urlencode({
        "event": "workflow_dispatch", "status": "success", "per_page": DISPATCHED_RUNS_SEARCHED,
    })
    dispatched = fetch(f"{runs_url}?{query}").get("workflow_runs") or []
    if not dispatched:
        return None
    trusted = default_branch(fetch, api_url, repo)
    for run in dispatched:
        if trusted and run.get("head_branch") == trusted and tested_the_release(run):
            return run, f"dispatched for the release on {trusted}, its job named {wanted}"
    return None


def decide(
    fetch: Fetch,
    *,
    api_url: str,
    repo: str,
    version: str,
    environment: str,
    workflow: str,
) -> tuple[bool, str]:
    """
    Decide whether the deploy may proceed, and say why in one sentence.

    Fails closed on PROD. On DEV the lookup's result is reported and the deploy is allowed, unless GitHub could
    not be asked at all, which denies everywhere since nothing is known.

    Args:
        fetch: The API reader, ``github_fetch`` in the job and a map in the tests
        api_url: The API base, GitHub's own or the enterprise one the runner names
        repo: owner/name of the repo being deployed
        version: The release version, without the v
        environment: The target, dev or prod
        workflow: The E2E workflow file name

    Returns:
        ``(allowed, reason)``
    """
    tag     = f"v{version}"
    gated   = environment.strip().lower() == ENVIRONMENT_PROD
    verdict = "denied" if gated else "noted, the gate applies to prod"
    try:
        sha = tag_commit(fetch, api_url, repo, tag)
        if sha is None:
            return (not gated), (
                f"There is no tag {tag} in {repo}, so no E2E run can have tested it ({verdict}). "
                f"The release workflow creates the tag when VERSION lands on main."
            )
        try:
            found = successful_run(fetch, api_url, repo, workflow, sha, version)
        except ApiError as exc:
            if exc.status == 404:
                return (not gated), (
                    f"{repo} has no workflow {workflow}, so its releases carry no E2E run ({verdict}). "
                    f"Every repo that deploys owns one, see kriegerdataforge-cicd/docs/guides/E2E_TESTING.md."
                )
            raise
    except ApiError as exc:
        return False, (
            f"The E2E gate could not ask GitHub ({exc}). The token needs actions: read on {repo}, "
            f"the calling cd.yml grants it on its deploy job (denied, nothing is known)."
        )
    if found is None:
        return (not gated), (
            f"No successful E2E run of {workflow} exists for {tag} (commit {sha[:12]}) in {repo} ({verdict}). "
            f"Dispatch it for the release, Actions, E2E, Run workflow, on the default branch, version {version}, "
            f"and deploy again once it is green. A run with the version left empty ran no lane but the journey "
            f"and does not count, nor does one dispatched on another branch, nor one whose job was skipped."
        )
    run, how = found
    when = run.get("updated_at") or run.get("created_at") or ""
    return True, (
        f"{tag} (commit {sha[:12]}) passed E2E in {repo}, run #{run.get('run_number')} of {workflow} ({how}), "
        f"{when}, {run.get('html_url')}."
    )

# ======================================================================================================================
# Output helpers
# ======================================================================================================================

def _emit(message: str, *, ok: bool, environment: str) -> None:
    """
    Print the result and append it to the GitHub Actions step summary if available.

    Args:
        message: The reason, one sentence
        ok: Whether the deploy may proceed
        environment: The target, named in the summary heading
    """
    # Plain-ASCII prefixes (no emoji) so output is safe on every console encoding,
    # matching the house style of the other scripts.
    line = f"{'OK' if ok else 'DENIED'}: {message}"
    print(line)

    summary_path = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary_path:
        try:
            with open(summary_path, "a", encoding = "utf-8") as summary:
                summary.write(f"### E2E gate ({environment})\n\n{line}\n")
        except OSError:
            pass

# ======================================================================================================================
# CLI
# ======================================================================================================================

def parse_cli_args(argv: list[str] | None = None) -> argparse.Namespace:
    """
    Parse the flags, each optional since the environment variables stand in for them in the job.

    Args:
        argv: The CLI arguments, None for the process's own

    Returns:
        The parsed namespace
    """
    parser = argparse.ArgumentParser(
        description = "Verify the release being deployed has a successful E2E run for its tag's commit.",
        formatter_class = argparse.RawDescriptionHelpFormatter,
        epilog = EPILOG,
    )
    parser.add_argument("--repo", default = None, help = "owner/repo, e.g. Needless2Say/tiffanys-space")
    parser.add_argument("--version", default = None, help = "the release version being deployed, e.g. 0.3.7")
    parser.add_argument("--environment", default = None, help = "target environment, dev or prod")
    parser.add_argument("--workflow", default = None, help = "the E2E workflow file name, default e2e.yml")
    return parser.parse_args(argv)


def _resolve(value: str | None, *env_names: str) -> str:
    """
    Return the CLI value if set, else the first non-empty environment variable.

    Args:
        value: The CLI flag's value, None when the flag was omitted
        env_names: The environment variables to read in order

    Returns:
        The first non-empty value, or an empty string
    """
    if value:
        return value
    for name in env_names:
        candidate = os.environ.get(name, "")
        if candidate:
            return candidate
    return ""


def main(argv: list[str] | None = None) -> int:
    """
    Read the inputs, ask GitHub, print the verdict and answer the exit code the job fails on.

    Args:
        argv: The CLI arguments, None for the process's own

    Returns:
        0 when the deploy may proceed, 1 when it may not
    """
    args        = parse_cli_args(argv)
    repo        = _resolve(args.repo, "DEPLOY_REPO", "GITHUB_REPOSITORY")
    version     = _resolve(args.version, "DEPLOY_VERSION").strip().lstrip("v")
    environment = _resolve(args.environment, "DEPLOY_ENVIRONMENT").strip().lower()
    workflow    = _resolve(args.workflow, "E2E_WORKFLOW") or DEFAULT_WORKFLOW
    api_url     = os.environ.get("GITHUB_API_URL", "").rstrip("/") or DEFAULT_API_URL

    inputs  = (("repo", repo), ("version", version), ("environment", environment))
    missing = [name for name, value in inputs if not value]
    if missing:
        _emit(
            f"missing {', '.join(missing)}, the gate cannot decide (denied)",
            ok = False,
            environment = environment or "?",
        )
        return 1

    allowed, reason = decide(
        github_fetch,
        api_url = api_url,
        repo = repo,
        version = version,
        environment = environment,
        workflow = workflow,
    )
    _emit(reason, ok = allowed, environment = environment)
    return 0 if allowed else 1


if __name__ == "__main__":
    sys.exit(main())
