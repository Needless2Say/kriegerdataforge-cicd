"""
The PROD Gate of the six deploying repos, held to one shape wherever their checkouts sit beside this one.

A release is judged whole (D-024, D-026, D-027). A consumer's `prod-gate.yml`, dispatched with a version, calls its
own `ci.yml` on the release tag, the suites a release alone runs, and its E2E journey last, and one last job needs
every one of them, passes only when each passed and carries the release in its name, the mark the PROD deploy reads.
The hub and the auth UI pin their own workflows in their own suites. The four tenant repos hold no such suite, so
the shape is read here, from the owner's workspace, where the repos sit side by side. On a runner this repo is alone
and every case reports itself skipped, unless KDF_CONSUMERS_REQUIRED is set, which fails a missing repo instead, so a
run meant to read all six cannot pass on fewer.

Each job's role is read from its condition (D-075). A job a pull request alone is held to names the pull request
event. A repo wired for the docs only fast path joins every other job to the secret scan, a lane's caller on
always() passing the skip expression and a local job on always() and that expression's negation with a cancel guard
first. A repo is read before its change and after it, wired whole or not at all, and a release, which the scan never
answers, skips no lane.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

WORKSPACE = Path(__file__).resolve().parents[3]

# a deploying repo, the lanes its gate runs between ci and the journey, whether those lanes and ci are handed the
# secrets, and the secrets its journey is handed by name
CONSUMERS = {
    "kriegerdataforge": (("system-tests", "mutation-tests"), True, ("KDF_APP_ID", "KDF_APP_PRIVATE_KEY")),
    "kriegerdataforge-auth-ui": (("integration-tests", "mutation-tests"), False, ("KDF_APP_ID", "KDF_APP_PRIVATE_KEY")),
    "fitness-app-backend": (("system-tests", "mutation-tests"), True, ("KDF_APP_ID", "KDF_APP_PRIVATE_KEY")),
    "tiffanys-space-backend": (("system-tests", "mutation-tests"), True, ("KDF_APP_ID", "KDF_APP_PRIVATE_KEY")),
    "fitness-app-frontend": (
        ("integration-tests", "mutation-tests"),
        True,
        ("KDF_APP_ID", "KDF_APP_PRIVATE_KEY", "GH_NPM_TOKEN"),
    ),
    "tiffanys-space": (
        ("integration-tests", "mutation-tests"),
        True,
        ("KDF_APP_ID", "KDF_APP_PRIVATE_KEY", "GH_NPM_TOKEN"),
    ),
}

# the jobs of a ci.yml a pull request alone is held to, where the repo holds them. The version is compared with
# main's, the style check reads how the code is laid out, and no deploy runs the image (D-027)
PULL_REQUEST_ONLY = ("docker-build", "style", "version-check")

# the tenants call this repo's mutation lane and name their own tables, the hub and the auth UI run their own
TENANTS = ("fitness-app-backend", "fitness-app-frontend", "tiffanys-space", "tiffanys-space-backend")

CENTRAL  = "\n    uses: Needless2Say/kriegerdataforge-cicd/.github/workflows/"
CHECKOUT = re.compile(r"uses: actions/checkout@[0-9a-f]{40}[^\n]*\n((?: {8}[^\n]*\n)*)")
PINNED   = re.compile(r"actions/checkout@[0-9a-f]{40} # v[0-9.]+")

# every lane's result GitHub can write, and the one that passes
RESULTS = ("success", "failure", "cancelled", "skipped")

# the one skip expression, true only when the scan job itself succeeded and said every path is docs (D-075)
SKIP_EXPRESSION = "needs.secret-scan.result == 'success' && needs.secret-scan.outputs.docs_only == 'true'"
PULL_REQUEST    = "github.event_name == 'pull_request'"

# the conditions a job of ci.yml may hold, before its repo's change and after it, a lane's caller and a local job
CALLER_CONDITIONS = ("${{ always() }}", f"${{{{ always() && {PULL_REQUEST} }}}}")
LOCAL_CONDITIONS  = (
    f"${{{{ always() && !({SKIP_EXPRESSION}) }}}}",
    f"${{{{ always() && !({SKIP_EXPRESSION}) && {PULL_REQUEST} }}}}",
)
BEFORE_CONDITIONS = (PULL_REQUEST,)

# what the scan's last step runs on, in this repo's secret-scan.yml, so a release with a ref gets no answer
SCAN_ANSWERS = f"        if: ${{{{ success() && {PULL_REQUEST} && inputs.ref == '' }}}}\n"


def _missing(repo: str) -> None:
    """
    A sibling repo that is not beside this one, a skip, or a failure when the run must read every consumer.
    """
    if os.environ.get("KDF_CONSUMERS_REQUIRED"):
        pytest.fail(f"{repo} is not checked out beside this repo and KDF_CONSUMERS_REQUIRED is set")
    pytest.skip(f"{repo} is not checked out beside this repo")


def _workflow(repo: str, name: str) -> str:
    """
    One workflow of a sibling repo, its line ends the runner's, or a skip when the repo is not beside this one.
    """
    path = WORKSPACE / repo / ".github" / "workflows" / name
    if not path.is_file():
        _missing(repo)
    return path.read_text(encoding = "utf-8").replace("\r\n", "\n")


def _condition(job: str) -> str:
    """
    A job's own if, empty when it has none.
    """
    found = re.search(r"^    if: (.+)$", job, flags = re.MULTILINE)
    return found.group(1).strip() if found else ""


def _pull_request_only(job: str) -> bool:
    """
    Whether a job runs on a pull request alone, its condition naming the event.
    """
    return PULL_REQUEST in _condition(job)


def _joined(job: str) -> bool:
    """
    Whether a job waits for the secret scan, wired for the docs only fast path.
    """
    return re.search(r"^    needs: \[[^\]]*\bsecret-scan\b[^\]]*\]$", job, flags = re.MULTILINE) is not None


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


def _triggers(text: str) -> list[str]:
    """
    The events a workflow starts on, the keys under its `on`.
    """
    block = text[text.index("\non:\n") + len("\non:\n"):]
    block = block[:re.search(r"^[a-z]", block, flags = re.MULTILINE).start()]
    return re.findall(r"^  ([a-z_]+):", block, flags = re.MULTILINE)


def _verdict(repo: str) -> str:
    """
    The program the gate's last job runs, as the runner hands it to python3.
    """
    job   = _jobs(repo, "prod-gate.yml")["gate"]
    start = job.index("          python3 - <<'VERDICT'\n") + len("          python3 - <<'VERDICT'\n")
    block = job[start:job.index("          VERDICT\n", start)]
    return "".join(line[10:] if line.strip() else "\n" for line in block.splitlines(keepends = True))


def _judge(repo: str, lanes: object, tmp_path: Path) -> tuple[int, str, str]:
    """
    Run one repo's verdict on the lanes' results, as GitHub writes them, and answer its exit, output and summary.
    """
    summary = tmp_path / "summary.md"
    summary.write_text("", encoding = "utf-8")
    env  = {
        **os.environ,
        "VERSION": "0.3.7",
        "LANES": lanes if isinstance(lanes, str) else json.dumps(lanes, indent = 2),
        "GITHUB_STEP_SUMMARY": str(summary),
    }
    done = subprocess.run([sys.executable, "-"], input = _verdict(repo), env = env, capture_output = True, text = True)
    return done.returncode, done.stdout + done.stderr, summary.read_text(encoding = "utf-8")


def _lanes(repo: str, **changed: str) -> dict[str, dict[str, object]]:
    """
    Every lane of a repo's gate passed, but for the ones named.
    """
    keys = ("ci", *CONSUMERS[repo][0], "e2e")
    return {key: {"result": changed.get(key.replace("-", "_"), "success"), "outputs": {}} for key in keys}

# ======================================================================================================================
# The gate
# ======================================================================================================================

@pytest.mark.parametrize("repo", sorted(CONSUMERS))
def test_the_gate_is_dispatched_for_a_release_and_started_by_nothing_else(repo):
    """
    A pull request, a push or a timer that started the gate would run it with no release to judge.
    """
    text = _workflow(repo, "prod-gate.yml")
    assert text.startswith("name: PROD Gate\n")
    assert _triggers(text) == ["workflow_dispatch"]
    asked = text[text.index("\n      version:\n"):text.index("\npermissions:\n")]
    assert "\n        required: true\n" in asked and "default:" not in asked
    assert "\nconcurrency:\n  group: prod-gate-${{ inputs.version }}\n" in text


@pytest.mark.parametrize("repo", sorted(CONSUMERS))
def test_the_gate_runs_ci_and_every_suite_on_the_tag(repo):
    lanes = ("ci", *CONSUMERS[repo][0])
    jobs  = _jobs(repo, "prod-gate.yml")
    assert [key for key, job in jobs.items() if "\n    uses: " in job] == [*lanes, "e2e"]
    assert list(jobs) == [*lanes, "e2e", "gate"], "a job that is no lane and not the verdict"
    assert "\n    uses: ./.github/workflows/ci.yml\n" in jobs["ci"], "called, a copy of a job drifts from it"
    assert "\n    uses: ./.github/workflows/e2e.yml\n" in jobs["e2e"]
    for lane in lanes:
        assert "\n      ref: v${{ inputs.version }}\n" in jobs[lane], lane
        assert ("\n    secrets: inherit\n" in jobs[lane]) == CONSUMERS[repo][1], lane
    assert "\n      version: ${{ inputs.version }}\n" in jobs["e2e"]
    for lane in (*lanes, "e2e"):
        assert "\n    if: " not in jobs[lane], f"{lane} runs on every run of the gate"
        assert "continue-on-error" not in jobs[lane], lane


@pytest.mark.parametrize("repo", sorted(CONSUMERS))
def test_the_ci_lane_is_granted_what_ci_holds(repo):
    """
    A called workflow that asks for more than its caller grants stops the whole run before any job starts.
    """
    held = re.search(r"\npermissions:\n((?:  [a-z-]+: [a-z]+\n)+)", _workflow(repo, "ci.yml"))
    assert held is not None, "ci.yml names what it holds"
    granted = "    permissions:\n" + "".join(f"    {line}\n" for line in held.group(1).splitlines())
    assert granted in _jobs(repo, "prod-gate.yml")["ci"]


@pytest.mark.parametrize("repo", sorted(CONSUMERS))
def test_the_journey_waits_for_every_other_lane_and_is_handed_the_secrets_it_reads(repo):
    lanes   = ("ci", *CONSUMERS[repo][0])
    journey = _jobs(repo, "prod-gate.yml")["e2e"]
    assert f"\n    needs: [{', '.join(lanes)}]\n" in journey
    handed = "    secrets:\n" + "".join(f"      {name}: ${{{{ secrets.{name} }}}}\n" for name in CONSUMERS[repo][2])
    assert handed + "\n" in journey
    assert re.findall(r"secrets\.([A-Z_]+)", journey) == list(CONSUMERS[repo][2]), "these and no other"
    assert "secrets: inherit" not in journey

    called   = _workflow(repo, "e2e.yml")
    declared = called[called.index("\n    secrets:\n") + len("\n    secrets:\n"):called.index("\npermissions:\n")]
    assert re.findall(r"^      ([A-Z_]+):\n", declared, flags = re.MULTILINE) == list(CONSUMERS[repo][2])
    assert declared.count("        required: true\n") == len(CONSUMERS[repo][2])
    assert sorted(set(re.findall(r"secrets\.([A-Z_]+)", called))) == sorted(CONSUMERS[repo][2])


@pytest.mark.parametrize("repo", sorted(CONSUMERS))
def test_the_last_job_needs_every_lane_and_carries_the_release(repo):
    lanes = ("ci", *CONSUMERS[repo][0], "e2e")
    gate  = _jobs(repo, "prod-gate.yml")["gate"]
    assert gate.startswith("  gate:\n    name: PROD Gate v${{ inputs.version }}\n")
    assert f"\n    needs: [{', '.join(lanes)}]\n" in gate
    assert "\n    if: ${{ !cancelled() }}\n" in gate and "always()" not in gate
    assert "continue-on-error" not in gate
    steps = re.findall(r"^      - name: (.+)$", gate, flags = re.MULTILINE)
    assert steps == ["Every lane passed", "Read the commit the release names", "Record the release this run passed"]
    judged = gate[gate.index("      - name: Every lane passed\n"):gate.index("      - name: Read the commit")]
    assert "          LANES: ${{ toJSON(needs) }}\n" in judged
    assert "\n        if: " not in gate, "no step of the verdict is skipped"


@pytest.mark.parametrize("repo", sorted(CONSUMERS))
def test_the_verdict_passes_when_every_lane_passed(repo, tmp_path):
    code, said, summary = _judge(repo, _lanes(repo), tmp_path)
    assert code == 0, said
    assert summary == "", "the next step records the release once the tag is read"
    for lane in ("ci", *CONSUMERS[repo][0], "e2e"):
        assert f"{lane}, success" in said


@pytest.mark.parametrize("result", [result for result in RESULTS if result != "success"])
@pytest.mark.parametrize("lane", ["ci", "mutation_tests", "e2e"])
@pytest.mark.parametrize("repo", sorted(CONSUMERS))
def test_the_verdict_fails_on_any_lane_that_did_not_pass_and_names_it(repo, lane, result, tmp_path):
    """
    A lane skipped behind one that failed is not a lane that passed, and neither is one that was cancelled.
    """
    code, said, summary = _judge(repo, _lanes(repo, **{lane: result}), tmp_path)
    name = lane.replace("_", "-")
    assert code == 1, said
    assert f"::error::Release v0.3.7 did not pass the PROD Gate. Not passed, {name}" in said
    assert summary.startswith("### PROD Gate NOT passed for release v0.3.7\n\n")
    assert f"Not passed, {name}. The release may not deploy to PROD.\n" in summary


@pytest.mark.parametrize("lanes", [
    {},
    "",
    "not json",
    "[]",
    {"ci": {"outputs": {}}},
    {"ci": "success"},
    {"ci": {"result": "Success"}},
    {"ci": {"result": None}},
], ids = ["no-lane", "empty", "not-json", "a-list", "no-result", "a-string", "another-case", "null"])
@pytest.mark.parametrize("repo", sorted(CONSUMERS))
def test_the_verdict_fails_on_anything_it_cannot_read(repo, lanes, tmp_path):
    code, said, _ = _judge(repo, lanes, tmp_path)
    assert code != 0, said


def test_every_repos_verdict_is_the_same_job():
    """
    Six copies of one job, a change to one is a change to all or it is a lane one repo no longer waits on.
    """
    found = {}
    for repo in sorted(CONSUMERS):
        gate = _jobs(repo, "prod-gate.yml")["gate"]
        gate = re.sub(r"\n    needs: \[[^\]]+\]\n", "\n    needs: [...]\n", gate)
        found[repo] = PINNED.sub("actions/checkout@<pinned>", gate)
    assert len(set(found.values())) == 1, sorted(found)

# ======================================================================================================================
# The journey
# ======================================================================================================================

@pytest.mark.parametrize("repo", sorted(CONSUMERS))
def test_the_journeys_workflow_holds_the_journey_alone(repo):
    """
    Until D-027 a dispatch of e2e.yml with a version ran the lanes and was the mark. The journey is one lane now,
    its workflow runs nothing else and signs off nothing.
    """
    text = _workflow(repo, "e2e.yml")
    jobs = _jobs(repo, "e2e.yml")
    assert list(jobs) == ["e2e"]
    assert "\n    needs: " not in jobs["e2e"] and "needs." not in jobs["e2e"]
    assert "./.github/workflows/" not in text, "it calls no workflow of its own repo"
    assert "PROD deploy gate finds this run" not in text
    assert "\n  workflow_call:\n    inputs:\n      version:\n" in text
    for event in ("pull_request", "push", "schedule", "workflow_dispatch", "workflow_call"):
        assert event in _triggers(text), event
    asked = jobs["e2e"][jobs["e2e"].index("    if: |\n"):jobs["e2e"].index("    runs-on:")]
    assert asked.startswith("    if: |\n      github.event_name == 'workflow_dispatch' ||\n")
    assert "\n          ref: ${{ inputs.version && format('v{0}', inputs.version) || '' }}\n" in jobs["e2e"]
    group = "\nconcurrency:\n  group: e2e-${{ github.ref }}-${{ inputs.version || 'ref' }}\n"
    assert group in text

# ======================================================================================================================
# ci.yml
# ======================================================================================================================

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
def test_a_release_skips_the_jobs_a_pull_request_alone_is_held_to_and_no_other(repo):
    """
    The version is one above main's on a pull request, and a tag is not a change to main. The style check reads
    how the code is laid out, and no deploy runs the image. Every other job of ci.yml judges the release.
    """
    jobs    = _jobs(repo, "ci.yml")
    skipped = sorted(key for key, job in jobs.items() if _pull_request_only(job))
    assert skipped == sorted(key for key in PULL_REQUEST_ONLY if key in jobs)
    assert "version-check" in skipped
    allowed = (*BEFORE_CONDITIONS, *CALLER_CONDITIONS, *LOCAL_CONDITIONS)
    for key, job in jobs.items():
        assert _condition(job) in ("", *allowed), f"{key} holds a condition no role names, {_condition(job)}"
    assert sorted(key for key, job in jobs.items() if "github.event_name" in job) == skipped
    scan = "\n      fetch-depth: ${{ inputs.ref != '' && 1 || 0 }}\n"
    assert scan in jobs["secret-scan"], "a release scans the tree its tag names"


@pytest.mark.parametrize("repo", sorted(CONSUMERS))
def test_a_repo_is_wired_whole_or_not_at_all_and_a_release_never_skips_a_lane(repo):
    """
    D-075. Before its change no job waits for the scan and every job runs as it did. After it every other job does, a
    lane's caller on always() handing the lane the one skip expression, and a local job on always() and the
    expression's negation with a cancel guard as its first step, since a local job skipped on a cancelled run reports
    Success. The expression needs the scan to have said docs only, which its last step says only on a pull request with
    no ref, and a release hands the scan its tag, so a release dispatch skips no lane.
    """
    jobs   = _jobs(repo, "ci.yml")
    others = {key: job for key, job in jobs.items() if key != "secret-scan"}
    joined = {key for key, job in others.items() if _joined(job)}
    assert joined in (set(), set(others)), f"wired in part, {sorted(set(others) - joined)} wait for no scan"
    if not joined:
        assert not any("inputs.skip" in job or "\n      skip: " in job for job in jobs.values())
        return
    for key, job in others.items():
        if "\n    uses: " in job:
            assert _condition(job) in CALLER_CONDITIONS, f"{key} {_condition(job)}"
            assert f"\n      skip: ${{{{ {SKIP_EXPRESSION} }}}}\n" in job, key
        else:
            assert _condition(job) in LOCAL_CONDITIONS, f"{key} {_condition(job)}"
            first = job.split("    steps:\n", 1)[1].lstrip("\n")
            assert re.match(r"      - name: [^\n]+\n        if: \$\{\{ cancelled\(\) \}\}\n", first), key
    assert "\n      ref: ${{ inputs.ref }}\n" in jobs["secret-scan"], "a release hands the scan its tag"
    here = Path(__file__).resolve().parents[2] / ".github" / "workflows" / "secret-scan.yml"
    assert SCAN_ANSWERS in here.read_text(encoding = "utf-8").replace("\r\n", "\n")


@pytest.mark.parametrize("repo, held", [
    ("kriegerdataforge", ("lint", "type-check", "vercel-compactor-staleness", "backend-unit-tests",
                          "integration-tests", "security", "secret-scan")),
    ("fitness-app-backend", ("lint", "type-check", "vercel-compactor-staleness", "unit-tests",
                             "integration-tests", "security", "secret-scan")),
    ("tiffanys-space-backend", ("lint", "type-check", "vercel-compactor-staleness", "unit-tests",
                                "integration-tests", "security", "secret-scan")),
    ("kriegerdataforge-auth-ui", ("lint-and-typecheck", "build", "unit-tests", "npm-audit", "secret-scan")),
    ("fitness-app-frontend", ("lint-and-typecheck", "build", "unit-tests", "npm-audit", "secret-scan")),
    ("tiffanys-space", ("lint-and-typecheck", "build", "unit-tests", "npm-audit", "secret-scan")),
])
def test_the_checks_a_release_is_held_to_are_the_owners_list(repo, held):
    """
    The owner's list of 2026-09-27, one for the FastAPI repos and one for the Next.js repos. `security` is
    bandit and pip-audit, two jobs of one lane. A job a pull request alone is held to names the event, and every
    other job judges the release, a condition joining it to the scan or none.
    """
    jobs = _jobs(repo, "ci.yml")
    assert sorted(key for key, job in jobs.items() if not _pull_request_only(job)) == sorted(held)

# ======================================================================================================================
# The lanes of this repo
# ======================================================================================================================

@pytest.mark.parametrize("repo", sorted(CONSUMERS))
def test_every_lane_a_consumer_calls_is_a_lane_this_repo_holds(repo):
    """
    A consumer names this repo's lanes at `main`. One it does not hold stops the consumer's run at startup.
    """
    here = Path(__file__).resolve().parents[2] / ".github" / "workflows"
    for name in ("ci.yml", "e2e.yml", "prod-gate.yml"):
        for lane in re.findall(
            r"uses: Needless2Say/kriegerdataforge-cicd/\.github/workflows/([a-z0-9-]+\.yml)@main",
            _workflow(repo, name),
        ):
            assert (here / lane).is_file(), f"{repo} {name} calls {lane}"
            text = (here / lane).read_text(encoding = "utf-8")
            assert "      ref:\n" in text.replace("\r\n", "\n"), f"{lane} takes no ref, {repo} {name} hands it one"


@pytest.mark.parametrize("repo", TENANTS)
def test_a_tenants_gate_runs_every_mutant_table_the_repo_holds(repo):
    """
    The lane runs the tables its caller names. A table the gate does not name is a lane of mutants no release runs.
    """
    tables = WORKSPACE / repo / "mutation_tests"
    if not tables.is_dir():
        _missing(repo)
    held  = sorted(path.stem for path in tables.glob("*.json"))
    held  = held or sorted(path.stem for path in tables.glob("*.py") if path.stem not in ("__init__", "run"))
    job   = _jobs(repo, "prod-gate.yml")["mutation-tests"]
    named = re.search(r"\n      lanes: '(\[[^']+\])'\n", job)
    assert named is not None, "the lanes are named as a JSON list"
    assert sorted(json.loads(named.group(1))) == held and held
