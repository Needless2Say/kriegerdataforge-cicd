"""
The release workflows of the six deploying repos, held to one shape wherever their checkouts sit beside this one.

A release is judged whole (D-024, D-026). A consumer's `e2e.yml`, dispatched with a version, calls its own `ci.yml`
on the release tag, every check a pull request is held to, and the lanes a release alone runs, and the job the PROD
deploy gate reads needs every one of them. The hub and the auth UI pin their own workflows in their own suites. The
four tenant repos hold no such suite, so the shape is read here, from the owner's workspace, where the repos sit side
by side. On a runner this repo is alone and every case reports itself skipped.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

WORKSPACE = Path(__file__).resolve().parents[3]

# a deploying repo, the lanes its release runs beside ci, and whether its lanes are handed the secrets
CONSUMERS = {
    "kriegerdataforge": (("system-tests", "mutation-tests"), True),
    "kriegerdataforge-auth-ui": (("mutation-tests",), False),
    "fitness-app-backend": ((), True),
    "tiffanys-space-backend": ((), True),
    "fitness-app-frontend": (("integration-tests",), True),
    "tiffanys-space": (("integration-tests",), True),
}

# the one job of a ci.yml a release skips, it compares the version with main's
PULL_REQUEST_ONLY = "version-check"

CENTRAL  = "\n    uses: Needless2Say/kriegerdataforge-cicd/.github/workflows/"
CHECKOUT = re.compile(r"uses: actions/checkout@[0-9a-f]{40}[^\n]*\n((?: {8}[^\n]*\n)*)")


def _workflow(repo: str, name: str) -> str:
    """
    One workflow of a sibling repo, its line ends the runner's, or a skip when the repo is not beside this one.
    """
    path = WORKSPACE / repo / ".github" / "workflows" / name
    if not path.is_file():
        pytest.skip(f"{repo} is not checked out beside this repo")
    return path.read_text(encoding = "utf-8").replace("\r\n", "\n")


def _jobs(repo: str, name: str) -> dict[str, str]:
    """
    The jobs of one workflow, each job's text from its key to the next job's.
    """
    text  = _workflow(repo, name)
    body  = text[text.index("\njobs:\n") + len("\njobs:\n"):]
    keys  = list(re.finditer(r"^  ([A-Za-z0-9_-]+):\n", body, flags = re.MULTILINE))
    found = {}
    for index, key in enumerate(keys):
        end = keys[index + 1].start() if index + 1 < len(keys) else len(body)
        found[key.group(1)] = body[key.start():end]
    return found


@pytest.mark.parametrize("repo", sorted(CONSUMERS))
def test_a_release_runs_ci_whole_and_its_own_lanes_on_the_tag(repo):
    lanes = ("ci", *CONSUMERS[repo][0])
    jobs  = _jobs(repo, "e2e.yml")
    assert [key for key, job in jobs.items() if "\n    uses: " in job] == list(lanes)
    assert "\n    uses: ./.github/workflows/ci.yml\n" in jobs["ci"], "called, a copy of a job drifts from it"
    for lane in lanes:
        assert "\n    if: inputs.version != ''\n" in jobs[lane], lane
        assert "\n      ref: v${{ inputs.version }}\n" in jobs[lane], lane
        assert ("\n    secrets: inherit\n" in jobs[lane]) == CONSUMERS[repo][1], lane


@pytest.mark.parametrize("repo", sorted(CONSUMERS))
def test_the_ci_lane_is_granted_what_ci_holds(repo):
    """
    A called workflow that asks for more than its caller grants stops the whole run before any job starts.
    """
    held = re.search(r"\npermissions:\n((?:  [a-z-]+: [a-z]+\n)+)", _workflow(repo, "ci.yml"))
    assert held is not None, "ci.yml names what it holds"
    granted = "    permissions:\n" + "".join(f"    {line}\n" for line in held.group(1).splitlines())
    assert granted in _jobs(repo, "e2e.yml")["ci"]


@pytest.mark.parametrize("repo", sorted(CONSUMERS))
def test_the_job_the_gate_reads_needs_every_lane(repo):
    lanes   = ("ci", *CONSUMERS[repo][0])
    journey = _jobs(repo, "e2e.yml")["e2e"]
    asked   = journey[journey.index("    if: |\n"):journey.index("    runs-on:")]
    assert f"\n    needs: [{', '.join(lanes)}]\n" in journey
    assert asked.startswith("    if: |\n      !cancelled() &&\n") and "always()" not in asked
    for lane in lanes:
        assert f"(needs.{lane}.result == 'success' || needs.{lane}.result == 'skipped') &&\n" in asked, lane
    assert "\n    name: ${{ inputs.version && format('E2E v{0}', inputs.version) || 'E2E' }}\n" in journey
    group = "\nconcurrency:\n  group: e2e-${{ github.ref }}-${{ inputs.version || 'ref' }}\n"
    assert group in _workflow(repo, "e2e.yml")


@pytest.mark.parametrize("repo", sorted(CONSUMERS))
def test_ci_called_on_a_ref_judges_that_ref_in_every_job(repo):
    text = _workflow(repo, "ci.yml")
    jobs = _jobs(repo, "ci.yml")
    assert "\n  workflow_call:\n    inputs:\n      ref:\n" in text
    assert "\n  pull_request:\n" in text, "and is still a pull request's workflow"
    group = "\nconcurrency:\n  group: ci-${{ github.workflow }}-${{ github.ref }}-${{ inputs.ref }}\n"
    assert group in text
    lanes = {key: job for key, job in jobs.items() if CENTRAL in job}
    assert len(lanes) >= 5
    assert sorted(key for key, job in lanes.items() if "\n      ref: ${{ inputs.ref }}\n" not in job) == []
    for key, job in jobs.items():
        for given in CHECKOUT.findall(job):
            # a checkout of another repo names it, this repo in the version check
            if "repository: " not in given:
                assert given.startswith("        with:\n          ref: ${{ inputs.ref }}\n"), key


@pytest.mark.parametrize("repo", sorted(CONSUMERS))
def test_a_release_skips_the_version_check_and_nothing_else(repo):
    """
    The version is one above main's on a pull request. A release is a tag, and a tag is not a change to main.
    """
    jobs = _jobs(repo, "ci.yml")
    assert sorted(key for key, job in jobs.items() if "\n    if: " in job) == [PULL_REQUEST_ONLY]
    assert "\n    if: github.event_name == 'pull_request'\n" in jobs[PULL_REQUEST_ONLY]
    scan = "\n      fetch-depth: ${{ inputs.ref != '' && 1 || 0 }}\n"
    assert scan in jobs["secret-scan"], "a release scans the tree its tag names"


@pytest.mark.parametrize("repo", sorted(CONSUMERS))
def test_every_lane_a_consumer_calls_is_a_lane_this_repo_holds(repo):
    """
    A consumer names this repo's lanes at `main`. One it does not hold stops the consumer's run at startup.
    """
    here = Path(__file__).resolve().parents[2] / ".github" / "workflows"
    for name in ("ci.yml", "e2e.yml"):
        for lane in re.findall(
            r"uses: Needless2Say/kriegerdataforge-cicd/\.github/workflows/([a-z0-9-]+\.yml)@main",
            _workflow(repo, name),
        ):
            assert (here / lane).is_file(), f"{repo} {name} calls {lane}"
            text = (here / lane).read_text(encoding = "utf-8")
            assert "      ref:\n" in text.replace("\r\n", "\n"), f"{lane} takes no ref, {repo} {name} hands it one"
