"""
PROD gate for the KriegerDataForge CD workflows, a release deploys to PROD only after the repo's PROD Gate
workflow passed on that release, every check and every suite the repo holds, the E2E journey last.

Every repo with a deploy owns one PROD Gate (`.github/workflows/prod-gate.yml`, D-027). It is dispatched with a
release version and runs, on the tag `v<version>`, the commit the deploy job checks out, the repo's `ci.yml`
less the jobs a pull request alone is held to, its integration, system and mutation suites, and its E2E journey.
Its last job needs every one of them, passes only when each of them passed, and is named after the release,
`PROD Gate v<version>`. This gate asks GitHub whether that workflow has a successful run whose job of that name
ran and passed. The job cannot pass unless every lane did, so one lookup answers for the whole release. The
`verify-prod-gate` job in `cd-nextjs-vercel.yml` and `cd-python-vercel.yml` runs it after the deployer
authorization and before the deploy job, the same place and the same shape as `check_deployer.py`, so a PROD
deploy of an untested or partially tested release fails closed with the reason, and a deploy of a tested one
records which run tested it in the step summary.

Decision, for `prod`:
  - no tag v<version>                                  -> DENY  (exit 1, fail closed)
  - the repo has no PROD Gate workflow                 -> DENY  (exit 1)
  - no successful run for the version                  -> DENY  (exit 1)
  - the run's `PROD Gate v<version>` job did not pass  -> DENY  (exit 1)
  - a successful run whose `PROD Gate v<version>` passed -> ALLOW (exit 0), the run named in the summary
For `dev` the same lookup runs and its result is reported, and the deploy is never denied, DEV is the soak
that comes before the PROD Gate is dispatched for the release.

A run counts only when GitHub reports it `success` and its passed job is named `PROD Gate v<version>`. A lane
that failed fails the run, GitHub never reports it `success`, and this check denies without needing to know
the lanes' names. A run of the E2E workflow does not count, whatever its job is named, the journey alone is
one lane of the suite (D-027 supersedes D-021 and D-024 there).

The workflow a run ran is the one on the ref it was dispatched on, so the ref is held too. A run counts when
its head is the tag's commit, the release's own workflow, or when it was dispatched on the repository's
default branch, which the branch rules protect. A dispatch on any other branch does not count, that branch's
copy of the workflow may have dropped a lane and kept the job's name.

Inputs (CLI flags take precedence over environment variables):
  --repo         / DEPLOY_REPO        / GITHUB_REPOSITORY            e.g. "Needless2Say/fitness-app-frontend"
  --version      / DEPLOY_VERSION                                    e.g. "1.2.0", the tag is v1.2.0
  --environment  / DEPLOY_ENVIRONMENT                                "dev" or "prod"
  --workflow     / PROD_GATE_WORKFLOW                                the workflow file, default prod-gate.yml
  GH_TOKEN / GITHUB_TOKEN                                            a token with actions: read on the repo
  GITHUB_API_URL                                                     default https://api.github.com

Usage:
    python3 check_prod_gate.py
    python3 check_prod_gate.py --repo Needless2Say/tiffanys-space --version 0.3.7 --environment prod

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

DEFAULT_WORKFLOW: str = "prod-gate.yml"
DEFAULT_API_URL:  str = "https://api.github.com"
API_TIMEOUT:      int = 30

# the name the PROD Gate's last job gives itself, the job that needs every lane (D-027)
RELEASE_JOB_NAME: str = "PROD Gate v{version}"

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
    "  --workflow     <- PROD_GATE_WORKFLOW (default prod-gate.yml)",
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
    Find the newest successful run of the PROD Gate for one release, and say how it was found.

    A run counts when its passed job is named after the release, ``PROD Gate v<version>``, the job that needs
    every lane of the suite (D-027). The workflow it ran must be one to trust, the release's own, its head the
    tag's commit, or the default branch's.

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


    # a run on the tag's commit ran the workflow the release itself carries, a dispatch on the tag or on the
    # default branch while its head was the release. the name is asked of it all the same, a run for another
    # version on the same commit tested another tag
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
        workflow: The PROD Gate workflow file name

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
                f"There is no tag {tag} in {repo}, so no PROD Gate run can have tested it ({verdict}). "
                f"The release workflow creates the tag when VERSION lands on main."
            )
        try:
            found = successful_run(fetch, api_url, repo, workflow, sha, version)
        except ApiError as exc:
            if exc.status == 404:
                return (not gated), (
                    f"{repo} has no workflow {workflow}, so its releases carry no PROD Gate run ({verdict}). "
                    f"Every repo that deploys owns one, see kriegerdataforge-cicd/docs/guides/PROD_GATE.md."
                )
            raise
    except ApiError as exc:
        return False, (
            f"The PROD gate could not ask GitHub ({exc}). The token needs actions: read on {repo}, "
            f"the calling cd.yml grants it on its deploy job (denied, nothing is known)."
        )
    if found is None:
        return (not gated), (
            f"No successful PROD Gate run of {workflow} exists for {tag} (commit {sha[:12]}) in {repo} "
            f"({verdict}). Dispatch it for the release, Actions, PROD Gate, Run workflow, on the default branch, "
            f"version {version}, and deploy again once it is green. A run of the E2E workflow alone does not "
            f"count, nor does a PROD Gate dispatched on another branch, nor one a lane of which failed."
        )
    run, how = found
    when = run.get("updated_at") or run.get("created_at") or ""
    return True, (
        f"{tag} (commit {sha[:12]}) passed the PROD Gate in {repo}, run #{run.get('run_number')} of {workflow} "
        f"({how}), {when}, {run.get('html_url')}."
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
                summary.write(f"### PROD gate ({environment})\n\n{line}\n")
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
        description = "Verify the release being deployed has a successful PROD Gate run.",
        formatter_class = argparse.RawDescriptionHelpFormatter,
        epilog = EPILOG,
    )
    parser.add_argument("--repo", default = None, help = "owner/repo, e.g. Needless2Say/tiffanys-space")
    parser.add_argument("--version", default = None, help = "the release version being deployed, e.g. 0.3.7")
    parser.add_argument("--environment", default = None, help = "target environment, dev or prod")
    parser.add_argument("--workflow", default = None, help = "the PROD Gate workflow file name, default prod-gate.yml")
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
    workflow    = _resolve(args.workflow, "PROD_GATE_WORKFLOW") or DEFAULT_WORKFLOW
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
