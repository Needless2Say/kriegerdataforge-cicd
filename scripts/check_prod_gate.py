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

The evidence is bound to the commit the deploy checks out. The deploy's release job resolves the tag once and
passes its commit as the expected commit, and a tag that names another commit now moved since, which denies on
prod. A gate is a dispatch whose head is its dispatch ref while its jobs check out the tag, so a run found by its
head proves no more than one found by its job's name, and the name carries the version and no commit. So once a
repo's tag ruleset, which blocks a `v*` tag's update and deletion, was read back, its date in
`tag_ruleset_dates.json`, a run counts by either lookup only when it began after that date. A repo with no date
keeps the rule above, and its guarantee and no stronger.

Inputs (CLI flags take precedence over environment variables):
  --repo             / DEPLOY_REPO        / GITHUB_REPOSITORY        e.g. "Needless2Say/fitness-app-frontend"
  --version          / DEPLOY_VERSION                                e.g. "1.2.0", the tag is v1.2.0
  --environment      / DEPLOY_ENVIRONMENT                            "dev" or "prod"
  --workflow         / PROD_GATE_WORKFLOW                            the workflow file, default prod-gate.yml
  --expected-commit  / EXPECTED_COMMIT                               the commit the release job resolved
  --gate-run         / GATE_RUN_ID                                   the gate run the deploy names, judged alone
  GH_TOKEN / GITHUB_TOKEN                                            a token with actions: read on the repo

With a named gate run the checker judges that run alone by the same rules, since two gates for one release can hold
two plans and today's pick returns the first passing run on the tag's commit. Without one, today's lookup stands.
When the deploy may proceed on a run, the step's outputs name it, gate_run_id, gate_run_attempt and gate_commit.
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
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable
from datetime import datetime
from pathlib import Path

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

# each repo's date its tag ruleset was read back, recorded by the fence, beside this script in the sparse checkout
RULESET_DATES_FILE: Path = Path(__file__).with_name("tag_ruleset_dates.json")

# a full commit SHA as git and the release job write it
COMMIT: re.Pattern[str] = re.compile(r"[0-9a-f]{40}")

# a workflow run's id, digits alone, so a named run can never reshape the URL it is read from
RUN_ID: re.Pattern[str] = re.compile(r"[1-9][0-9]{0,19}")

# the CLI's help tail, the variables each flag falls back to
EPILOG: str = "\n".join((
    "Values fall back to environment variables when flags are omitted:",
    "  --repo             <- DEPLOY_REPO / GITHUB_REPOSITORY",
    "  --version          <- DEPLOY_VERSION",
    "  --environment      <- DEPLOY_ENVIRONMENT",
    "  --workflow         <- PROD_GATE_WORKFLOW (default prod-gate.yml)",
    "  --expected-commit  <- EXPECTED_COMMIT",
    "  --gate-run         <- GATE_RUN_ID",
))

# ======================================================================================================================
# The ruleset dates
# ======================================================================================================================

def parse_time(value: object) -> datetime | None:
    """
    Read one of GitHub's ISO 8601 times, its Z included, as an aware time.

    Args:
        value: The time as GitHub or the dates file writes it

    Returns:
        The time, or None when the value is no aware time
    """
    if not isinstance(value, str) or not value:
        return None
    try:
        when = datetime.fromisoformat(value)
    except ValueError:
        return None
    return when if when.tzinfo is not None else None


def load_ruleset_dates(path: Path | None = None) -> dict[str, str]:
    """
    Read each repo's tag ruleset date.

    Args:
        path: The file, the shipped one when None

    Returns:
        owner/name to the date its tag ruleset was read back

    Raises:
        ValueError: When the file is not the shape it should be, or a date is no aware time
        OSError: When the file cannot be read
    """
    data  = json.loads((path or RULESET_DATES_FILE).read_text(encoding = "utf-8"))
    dates = data.get("dates") if isinstance(data, dict) else None
    if not isinstance(dates, dict):
        raise ValueError("the file holds no dates object")
    for repo, when in dates.items():
        if not isinstance(repo, str) or parse_time(when) is None:
            raise ValueError(f"the date of {repo!r} is no aware ISO 8601 time")
    return dates

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
    since: datetime | None = None,
) -> tuple[dict, str] | None:
    """
    Find the newest successful run of the PROD Gate for one release, and say how it was found.

    A run counts when its passed job is named after the release, ``PROD Gate v<version>``, the job that needs
    every lane of the suite (D-027). The workflow it ran must be one to trust, the release's own, its head the
    tag's commit, or the default branch's. With ``since``, a run counts by either lookup only when it was created
    after it, the date the repo's tag ruleset was read back, whatever attempt it is on.

    Args:
        fetch: The API reader
        api_url: The API base
        repo: owner/name
        workflow: The workflow file name
        sha: The tag's commit
        version: The release version, without the v
        since: The repo's tag ruleset date, None for a repo with none

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
            True when the job ran and passed, and the run began after ``since`` when there is one
        """
        if since is not None:
            # the run's own creation, never its latest attempt's start, since a rerun of the verdict job alone keeps
            # the lanes' results from its first attempt
            began = parse_time(run.get("created_at"))
            if began is None or began <= since:
                return False
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


def named_run(
    fetch: Fetch,
    api_url: str,
    repo: str,
    workflow: str,
    sha: str,
    version: str,
    run_id: str,
    since: datetime | None = None,
) -> tuple[dict | None, str]:
    """
    Judge one named PROD Gate run alone, by the rules ``successful_run`` holds a found run to.

    Two gates for one release can hold two plans, and today's pick returns the first passing run on the tag's commit,
    hiding a later gate of the same release, so a deploy names the run whose plan the owner read (terraform in
    Actions, design 5.7, Round Table 81, L6). The run must be the gate's workflow, began after ``since`` when there is
    one, ran on the tag's commit or was dispatched on the default branch, succeeded, and passed its job named after
    the release.

    Args:
        fetch: The API reader
        api_url: The API base
        repo: owner/name
        workflow: The workflow file name
        sha: The tag's commit
        version: The release version, without the v
        run_id: The named run's id, digits alone
        since: The repo's tag ruleset date, None for a repo with none

    Returns:
        ``(run, how)`` when the run counts, ``(None, why)`` when it does not

    Raises:
        ApiError: For a fault other than GitHub knowing no such run
    """
    try:
        run = fetch(f"{api_url}/repos/{repo}/actions/runs/{run_id}")
    except ApiError as exc:
        if exc.status == 404:
            return None, f"GitHub knows no run {run_id} in {repo}"
        raise
    wanted = RELEASE_JOB_NAME.format(version = version)
    # a reusable call's path carries @ and its ref, the gate is a repo's own workflow file
    path = (run.get("path") or "").split("@", 1)[0]
    if path != f".github/workflows/{workflow}":
        return None, f"run {run_id} ran {path or 'no workflow'}, not {workflow}"
    if since is not None:
        began = parse_time(run.get("created_at"))
        if began is None or began <= since:
            return None, f"run {run_id} began before its tag ruleset was read back"
    how = "named, on its commit"
    if run.get("head_sha") != sha:
        trusted = default_branch(fetch, api_url, repo)
        if not trusted or run.get("head_branch") != trusted or run.get("event") != "workflow_dispatch":
            return None, (
                f"run {run_id} ran on {run.get('head_branch')!r} with a head other than the tag's commit, and only a "
                f"dispatch on the default branch counts, another branch's workflow is anyone's to write"
            )
        how = f"named, dispatched for the release on {trusted}"
    if run.get("conclusion") != "success":
        return None, f"run {run_id} did not succeed"
    if not any(job.get("name") == wanted for job in _passed_jobs(fetch, api_url, repo, run)):
        return None, f"run {run_id}'s job {wanted} did not pass"
    return run, f"{how}, its job named {wanted}"


def decide(
    fetch: Fetch,
    *,
    api_url: str,
    repo: str,
    version: str,
    environment: str,
    workflow: str,
    expected_commit: str | None = None,
    ruleset_date: str | None = None,
) -> tuple[bool, str]:
    """
    Decide whether the deploy may proceed, and say why in one sentence, ``decide_run`` with no named run.

    Args:
        fetch: The API reader, ``github_fetch`` in the job and a map in the tests
        api_url: The API base, GitHub's own or the enterprise one the runner names
        repo: owner/name of the repo being deployed
        version: The release version, without the v
        environment: The target, dev or prod
        workflow: The PROD Gate workflow file name
        expected_commit: The commit the release job resolved, None for a caller that passes none
        ruleset_date: The repo's tag ruleset date, binding only with an expected commit

    Returns:
        ``(allowed, reason)``
    """
    allowed, reason, _ = decide_run(
        fetch,
        api_url = api_url,
        repo = repo,
        version = version,
        environment = environment,
        workflow = workflow,
        expected_commit = expected_commit,
        ruleset_date = ruleset_date,
    )
    return allowed, reason


def decide_run(
    fetch: Fetch,
    *,
    api_url: str,
    repo: str,
    version: str,
    environment: str,
    workflow: str,
    expected_commit: str | None = None,
    ruleset_date: str | None = None,
    gate_run: str | None = None,
) -> tuple[bool, str, dict[str, str] | None]:
    """
    Decide whether the deploy may proceed, say why in one sentence, and describe the run it rests on.

    Fails closed on PROD. On DEV the lookup's result is reported and the deploy is allowed, unless GitHub could
    not be asked at all, or an input is malformed, which denies everywhere since nothing is known. With a named
    run the checker judges that run alone (``named_run``), today's lookup kept when none is named.

    Args:
        fetch: The API reader, ``github_fetch`` in the job and a map in the tests
        api_url: The API base, GitHub's own or the enterprise one the runner names
        repo: owner/name of the repo being deployed
        version: The release version, without the v
        environment: The target, dev or prod
        workflow: The PROD Gate workflow file name
        expected_commit: The commit the release job resolved, None for a caller that passes none
        ruleset_date: The repo's tag ruleset date, binding only with an expected commit
        gate_run: The named gate run's id, None for today's lookup

    Returns:
        ``(allowed, reason, run)``, ``run`` the run's id, attempt and the tag's commit when a run counted, else None
    """
    tag     = f"v{version}"
    gated   = environment.strip().lower() == ENVIRONMENT_PROD
    verdict = "denied" if gated else "noted, the gate applies to prod"
    since   = None
    if gate_run is not None and not RUN_ID.fullmatch(gate_run):
        return False, f"The gate run {gate_run!r} is no run id (denied, nothing is known).", None
    if expected_commit is not None:
        if not COMMIT.fullmatch(expected_commit):
            return False, (
                f"The expected commit {expected_commit!r} is no full commit SHA (denied, nothing is known)."
            ), None
        if ruleset_date is not None:
            since = parse_time(ruleset_date)
            if since is None:
                return False, (
                    f"The tag ruleset date {ruleset_date!r} of {repo} is no time (denied, nothing is known)."
                ), None
    try:
        sha = tag_commit(fetch, api_url, repo, tag)
        if sha is None:
            return (not gated), (
                f"There is no tag {tag} in {repo}, so no PROD Gate run can have tested it ({verdict}). "
                f"The release workflow creates the tag when VERSION lands on main."
            ), None
        if expected_commit is not None and sha != expected_commit:
            return (not gated), (
                f"{tag} names commit {sha[:12]} in {repo}, but the release job resolved it to {expected_commit[:12]}, "
                f"so the tag moved since ({verdict})."
            ), None
        if gate_run is not None:
            run, how = named_run(fetch, api_url, repo, workflow, sha, version, gate_run, since)
            if run is None:
                return (not gated), (
                    f"The named PROD Gate run {gate_run} does not count for {tag} (commit {sha[:12]}) in {repo}, "
                    f"{how} ({verdict})."
                ), None
            found = (run, how)
        else:
            try:
                found = successful_run(fetch, api_url, repo, workflow, sha, version, since)
            except ApiError as exc:
                if exc.status == 404:
                    return (not gated), (
                        f"{repo} has no workflow {workflow}, so its releases carry no PROD Gate run ({verdict}). "
                        f"Every repo that deploys owns one, see kriegerdataforge-cicd/docs/guides/PROD_GATE.md."
                    ), None
                raise
    except ApiError as exc:
        return False, (
            f"The PROD gate could not ask GitHub ({exc}). The token needs actions: read on {repo}, "
            f"the calling cd.yml grants it on its deploy job (denied, nothing is known)."
        ), None
    if found is None:
        bound = f", begun after its tag ruleset was read back at {ruleset_date}," if since is not None else ""
        return (not gated), (
            f"No successful PROD Gate run of {workflow}{bound} exists for {tag} (commit {sha[:12]}) in {repo} "
            f"({verdict}). Dispatch it for the release, Actions, PROD Gate, Run workflow, on the default branch, "
            f"version {version}, and deploy again once it is green. A run of the E2E workflow alone does not "
            f"count, nor does a PROD Gate dispatched on another branch, nor one a lane of which failed."
        ), None
    run, how = found
    when      = run.get("updated_at") or run.get("created_at") or ""
    described = {"run_id": str(run.get("id")), "run_attempt": str(run.get("run_attempt") or 1), "commit": sha}
    return True, (
        f"{tag} (commit {sha[:12]}) passed the PROD Gate in {repo}, run #{run.get('run_number')} of {workflow} "
        f"({how}), {when}, {run.get('html_url')}."
    ), described

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
    parser.add_argument("--expected-commit", default = None, help = "the commit the deploy's release job resolved")
    parser.add_argument("--gate-run", default = None, help = "the PROD Gate run the deploy names, judged alone")
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
    expected    = _resolve(args.expected_commit, "EXPECTED_COMMIT").strip() or None
    gate_run    = _resolve(args.gate_run, "GATE_RUN_ID").strip() or None
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

    try:
        ruleset_date = load_ruleset_dates().get(repo)
    except (OSError, ValueError) as exc:
        _emit(f"the tag ruleset dates cannot be read, {exc} (denied)", ok = False, environment = environment)
        return 1
    allowed, reason, run = decide_run(
        github_fetch,
        api_url = api_url,
        repo = repo,
        version = version,
        environment = environment,
        workflow = workflow,
        expected_commit = expected,
        ruleset_date = ruleset_date,
        gate_run = gate_run,
    )
    _emit(reason, ok = allowed, environment = environment)
    if allowed and run is not None:
        _write_outputs(run)
    return 0 if allowed else 1


def _write_outputs(run: dict[str, str]) -> None:
    """
    Write the run the deploy may proceed on to the step's outputs, an additive structured answer beside the prose.

    Args:
        run: The run's id, its attempt and the tag's commit, each digits or hex alone
    """
    output_path = os.environ.get("GITHUB_OUTPUT")
    if not output_path:
        return
    with open(output_path, "a", encoding = "utf-8") as output:
        output.write(f"gate_run_id={run['run_id']}\n")
        output.write(f"gate_run_attempt={run['run_attempt']}\n")
        output.write(f"gate_commit={run['commit']}\n")


if __name__ == "__main__":
    sys.exit(main())
