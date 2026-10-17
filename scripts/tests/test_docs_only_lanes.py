"""
Contract tests for D-075, a docs only pull request runs the secret scan alone.

The scan's last step answers docs_only, its copy of `scripts/common/ci_paths.py` held to the script and run here on
fixture repos made through git's index, so a path no file system holds is still a path in git. Every billed lane takes
the skip input on every job, and each job the fetch renderer does not write reads it alone, so a cancelled run cancels
it. A caller waits for the scan on !cancelled(), and a local job on always() fails in its first step when the scan did
not finish, since a step's cancelled() reads false in a job always() keeps through a cancel, measured on this repo's
pull request #307. Text level, as the rest of this suite reads workflows, so a text that matches proves no behaviour.
The skipped check names and a cancelled run are proved on GitHub by this repo's own CI, the probe jobs of ci.yml.
"""

from __future__ import annotations

import os
import re
import stat
import subprocess
import sys
from pathlib import Path

import pytest
import render_ci_paths

WORKFLOWS = Path(__file__).resolve().parents[2] / ".github" / "workflows"
SCRIPTS   = Path(__file__).resolve().parents[1]

# the author and committer of a fixture repo's commits, so no machine's own git identity is needed
FIXTURE_GIT = {
    "GIT_AUTHOR_NAME": "KDF Fixture",
    "GIT_AUTHOR_EMAIL": "fixture@example.invalid",
    "GIT_COMMITTER_NAME": "KDF Fixture",
    "GIT_COMMITTER_EMAIL": "fixture@example.invalid",
}

# a fixture pull request's base, a doc, a README and code
FIXTURE_BASE = {"README.md": "# fixture\n", "docs/a.md": "a\n", "src/app.py": "print(1)\n"}

# every billed lane a caller's docs only answer skips, the eight the fetch renderer writes and five by hand
SKIP_LANES = (
    "ci-python-tests.yml",
    "ci-python-integration.yml",
    "ci-python-system.yml",
    "ci-python-mutation.yml",
    "ci-python-security.yml",
    "ci-python-lint.yml",
    "ci-python-typecheck.yml",
    "ci-python-kdf-fmt.yml",
    "ci-vercel-compactor.yml",
    "ci-nextjs-lint-typecheck.yml",
    "ci-nextjs-build.yml",
    "ci-nextjs-tests.yml",
    "ci-npm-audit.yml",
)

# each job the renderer does not write, by its lane, the one job lanes and the security lane's bandit job
HAND_WRITTEN = {
    "ci-python-security.yml": "bandit",
    "ci-vercel-compactor.yml": "vercel-compactor-staleness",
    "ci-nextjs-lint-typecheck.yml": "lint-and-typecheck",
    "ci-nextjs-build.yml": "build",
    "ci-nextjs-tests.yml": "unit-tests",
    "ci-npm-audit.yml": "npm-audit",
}

# the if of a job the renderer does not write, with no always(), so a cancelled run cancels it as any job
HAND_CONDITION = (
    "    # D-075. Only skip, the caller's docs only answer, skips this job. With no always() a cancelled run cancels "
    "it,\n"
    "    #   and a caller on !cancelled() is never entered after a cancel during the scan, its check left unreported\n"
    "    if: ${{ !inputs.skip }}\n"
)

# a local job's first step, which reads the scan's result, the signal a step does see after a cancel
LOCAL_GUARD_STEP = (
    "      - name: Fail when the scan did not finish\n"
    "        if: ${{ needs.secret-scan.result != 'success' && needs.secret-scan.result != 'failure' }}\n"
    "        env:\n"
    "          SCAN_RESULT: ${{ needs.secret-scan.result }}\n"
    "        run: |\n"
    '          echo "::error::the secret scan ended $SCAN_RESULT, so this job ends failed rather than skipped and '
    'checks nothing"\n'
    "          exit 1\n"
)

# the one skip expression a consumer's ci.yml hands its lanes, and the probes of this repo's own ci.yml with it
SKIP_EXPRESSION = "needs.secret-scan.result == 'success' && needs.secret-scan.outputs.docs_only == 'true'"

# each skip probe of ci.yml and the lane it calls with skip true
SKIP_PROBES = {
    "skip-probe": "ci-nextjs-tests.yml",
    "skip-probe-split": "ci-python-lint.yml",
    "skip-probe-security": "ci-python-security.yml",
}


def _lane(name: str) -> str:
    """
    One workflow's text, its line ends the runner's.
    """
    return (WORKFLOWS / name).read_text(encoding = "utf-8").replace("\r\n", "\n")


def _steps(text: str) -> list[str]:
    """
    The step names of a workflow, in order.
    """
    return re.findall(r"^\s+- name: (.+)$", text, flags = re.MULTILINE)


def _step(text: str, name: str) -> str:
    """
    One step's text, from its name to the next step's.
    """
    start = text.index(f"- name: {name}")
    rest  = text[start + 1:]
    end   = re.search(r"^\s+- name: ", rest, flags = re.MULTILINE)
    return text[start:start + 1 + (end.start() if end else len(rest))]


def _jobs(text: str) -> dict[str, str]:
    """
    A workflow's jobs, each by its id with its own text, the comment lines above a job left with the one before.
    """
    body  = text.split("\njobs:\n", 1)[1]
    parts = re.split(r"^  ([a-z0-9-]+):\n", body, flags = re.MULTILINE)
    return {parts[index]: parts[index + 1] for index in range(1, len(parts), 2)}

# ======================================================================================================================
# The scan's answer
# ======================================================================================================================

def test_the_scans_copy_of_ci_paths_is_the_script():
    """
    The scan's last step carries ci_paths.py's own text, written in by render_ci_paths.py, since a lane cannot be
    trusted to check this repo out at its own commit (D-035). A hand edit to the copy, or an edit to the script without
    a render, fails here.
    """
    assert render_ci_paths.main(["--check"]) == 0
    script = (SCRIPTS / "common" / "ci_paths.py").read_text(encoding = "utf-8").replace("\r\n", "\n")
    assert render_ci_paths.copy(_lane("secret-scan.yml")) == script
    assert "${{" not in script and f"\n{render_ci_paths.DELIMITER}\n" not in script


def test_the_docs_only_step_is_last_runs_on_a_pull_request_alone_and_never_fails_the_scan():
    """
    The answer runs after the scan passed, on a pull request with no release ref, and its own failure is the step's
    alone, continue-on-error, so the scan stays a check that means the scan. Every value reaches it through the
    environment and the script runs isolated with the runner's own python.
    """
    lane = _lane("secret-scan.yml")
    assert _steps(lane)[-1] == "Docs only"
    step = _step(lane, "Docs only")
    assert "        id: docs-only\n" in step
    assert "        if: ${{ success() && github.event_name == 'pull_request' && inputs.ref == '' }}\n" in step
    assert "        continue-on-error: true\n" in step
    assert (
        "        env:\n"
        "          EVENT_SHA: ${{ github.sha }}\n"
        "          BASE_SHA: ${{ github.event.pull_request.base.sha }}\n"
        "          HEAD_SHA: ${{ github.event.pull_request.head.sha }}\n"
        "          NOT_DOCS: ${{ inputs.not_docs }}\n"
        "        run: |\n"
    ) in step
    run = step.split("        run: |\n", 1)[1]
    assert "${{" not in run, "no expression is written into the shell"
    assert run.rstrip("\n").endswith('          /usr/bin/python3 -I "$RUNNER_TEMP/kdf-ci-paths/ci_paths.py" answer')


def test_the_answer_reaches_the_caller_as_the_workflows_output_and_not_docs_is_optional():
    lane = _lane("secret-scan.yml")
    assert "      not_docs:\n        description: " in lane
    not_docs = lane.split("      not_docs:\n", 1)[1].split("\n    outputs:\n", 1)[0]
    assert not_docs.endswith("        required: false\n        type: string\n        default: \"\"")
    assert "    outputs:\n      docs_only:\n        description: " in lane
    assert "        value: ${{ jobs.gitleaks.outputs.docs_only }}\n" in lane
    assert "    outputs:\n      docs_only: ${{ steps.docs-only.outputs.docs_only }}\n" in lane


def _fixture_git(repo: Path, *args: str, stdin: bytes | None = None) -> str:
    """
    One git call in a fixture repo, its output.
    """
    found = subprocess.run(
        ["git", "-C", str(repo), *args],
        input = stdin,
        capture_output = True,
        check = True,
        env = {**os.environ, **FIXTURE_GIT},
    )
    return found.stdout.decode("utf-8").strip()


def _fixture_commit(repo: Path, files: dict[str, str], parents: list[str]) -> str:
    """
    A commit of exactly these files on these parents, made through the index alone, so a path no file system holds,
    one with a newline, is still a path in git.
    """
    _fixture_git(repo, "read-tree", "--empty")
    entries = b""
    for path, text in files.items():
        blob = _fixture_git(repo, "hash-object", "-w", "--stdin", stdin = text.encode("utf-8"))
        entries += f"100644 {blob}\t{path}".encode("utf-8") + b"\0"
    _fixture_git(repo, "update-index", "-z", "--index-info", stdin = entries)
    tree    = _fixture_git(repo, "write-tree")
    parents = [flag for parent in parents for flag in ("-p", parent)]
    return _fixture_git(repo, "commit-tree", tree, *parents, "-m", "fixture")


def _fixture_head(repo: Path, commit: str) -> None:
    """
    HEAD and the index at a commit, as a checkout leaves them, the working tree left alone.
    """
    _fixture_git(repo, "update-ref", "--no-deref", "HEAD", commit)
    _fixture_git(repo, "read-tree", commit)


def _pull_request(tmp_path: Path, changes: dict[str, str | None]) -> tuple[Path, dict[str, str]]:
    """
    A fixture pull request, its base, its head with the changes, None deleting a path, and GitHub's merge of the two,
    the base its first parent and the head its second, checked out.
    """
    repo = tmp_path / "repo"
    subprocess.run(["git", "init", "-q", str(repo)], check = True)
    # on Windows git refuses a path with a newline or a colon unless told otherwise, and --index-info then skips it
    # with exit 0, so the fixture turns the check off and proves below that every path landed
    _fixture_git(repo, "config", "core.protectNTFS", "false")
    files = {**FIXTURE_BASE}
    for path, text in changes.items():
        if text is None:
            files.pop(path)
        else:
            files[path] = text
    base  = _fixture_commit(repo, FIXTURE_BASE, [])
    head  = _fixture_commit(repo, files, [base])
    merge = _fixture_commit(repo, files, [base, head])
    _fixture_head(repo, merge)
    listed = subprocess.run(
        ["git", "-C", str(repo), "ls-tree", "-r", "-z", "--name-only", head],
        capture_output = True,
        check = True,
    ).stdout
    assert sorted(listed.decode("utf-8").split("\0")[:-1]) == sorted(files), "every fixture path is in the head"
    return repo, {"EVENT_SHA": merge, "BASE_SHA": base, "HEAD_SHA": head}


def _answer(tmp_path: Path, repo: Path, shas: dict[str, str], not_docs: str = "") -> tuple[str, str, str]:
    """
    The scan's rendered copy of ci_paths.py run in a fixture repo as the step runs it, isolated, its exit status held
    to 0. Its stdout, the output file and the summary file.
    """
    script = tmp_path / "kdf-ci-paths" / "ci_paths.py"
    script.parent.mkdir(exist_ok = True)
    script.write_text(render_ci_paths.copy(_lane("secret-scan.yml")), encoding = "utf-8", newline = "\n")
    output  = tmp_path / "github_output"
    summary = tmp_path / "step_summary"
    output.write_text("", encoding = "utf-8")
    summary.write_text("", encoding = "utf-8")
    env = {
        **os.environ,
        **shas,
        "NOT_DOCS": not_docs,
        "GITHUB_OUTPUT": str(output),
        "GITHUB_STEP_SUMMARY": str(summary),
    }
    run = subprocess.run(
        [sys.executable, "-I", str(script), "answer"],
        cwd = repo,
        env = env,
        capture_output = True,
        text = True,
    )
    assert run.returncode == 0, run.stdout + run.stderr
    assert run.stderr == ""
    return run.stdout, output.read_text(encoding = "utf-8"), summary.read_text(encoding = "utf-8")


@pytest.mark.parametrize("changes", [
    {"docs/a.md": "b\n"},
    {"docs/a.md": "b\n", "README.md": "# changed\n", "docs/img/new.png": "png\n", "notes/NEW.md": "n\n"},
    {"docs/a.md": None},
], ids = ["one-doc", "docs-and-markdown", "a-deleted-doc"])
def test_only_a_proven_docs_only_merge_writes_the_answer(tmp_path, changes):
    repo, shas = _pull_request(tmp_path, changes)
    stdout, output, summary = _answer(tmp_path, repo, shas)
    assert output == "docs_only=true\n"
    assert stdout == f"docs only, {len(changes)} paths, every billed lane skips\n"
    assert f"Docs only, {len(changes)} paths, every billed lane skipped." in summary


@pytest.mark.parametrize("changes, not_docs, said", [
    ({"docs/a.md": "b\n", "src/app.py": "print(2)\n"}, "", "1 of 2 paths are not docs"),
    ({"src/app.py": None, "docs/app.md": "print(1)\n"}, "", "1 of 2 paths are not docs"),
    ({"docs/run.py": "print(3)\n"}, "", "1 of 1 paths are not docs"),
    ({"README.md": "# changed\n"}, "README.md", "1 of 1 paths are not docs"),
    ({"docs/a.md": "b\n"}, "../README.md", "a not_docs pattern is refused"),
    ({"docs/a.md": "b\n"}, "READNE.md", "matches no tracked file"),
    ({"docs/a.md": "b\n"}, "docs/*.md?", "a not_docs pattern is refused"),
], ids = ["mixed", "code-renamed-into-docs", "code-under-docs", "not-docs-match", "malformed-not-docs",
          "not-docs-matching-nothing", "a-question-mark"])
def test_a_change_that_is_not_docs_only_writes_nothing(tmp_path, changes, not_docs, said):
    """
    No answer, and the reason in the log as well as the summary, a refusal's fixed text and counts, never a path.
    """
    repo, shas = _pull_request(tmp_path, changes)
    stdout, output, summary = _answer(tmp_path, repo, shas, not_docs)
    assert output == ""
    assert stdout.count("\n") == 1 and stdout.startswith(("not docs only, ", "no answer, every lane runs, "))
    assert said in summary and said in stdout


def test_a_shallow_checkout_writes_nothing(tmp_path):
    """
    A depth of 1, PROD Gate's for the hub, holds no parents to prove the merge by.
    """
    repo, shas = _pull_request(tmp_path, {"docs/a.md": "b\n"})
    _fixture_git(repo, "update-ref", "refs/heads/pr", shas["EVENT_SHA"])
    shallow = tmp_path / "shallow"
    subprocess.run(
        ["git", "clone", "-q", "--depth", "1", "--branch", "pr", repo.as_uri(), str(shallow)],
        check = True,
        capture_output = True,
    )
    _stdout, output, summary = _answer(tmp_path, shallow, shas)
    assert output == ""
    assert "the checkout is shallow" in summary


def test_a_commit_that_is_not_the_proven_merge_writes_nothing(tmp_path):
    """
    A single parent HEAD, the parents reversed, a HEAD that is not the event's commit, and an id that is not a commit
    each give no answer.
    """
    repo, shas = _pull_request(tmp_path, {"docs/a.md": "b\n"})


    def refused(given: dict[str, str], said: str) -> None:
        _stdout, output, summary = _answer(tmp_path, repo, {**shas, **given})
        assert output == ""
        assert said in summary


    _fixture_head(repo, shas["HEAD_SHA"])
    refused({"EVENT_SHA": shas["HEAD_SHA"]}, "exactly two parents")
    flipped = _fixture_commit(repo, {**FIXTURE_BASE, "docs/a.md": "b\n"}, [shas["HEAD_SHA"], shas["BASE_SHA"]])
    _fixture_head(repo, flipped)
    refused({"EVENT_SHA": flipped}, "first parent is not")
    _fixture_head(repo, shas["EVENT_SHA"])
    refused({"EVENT_SHA": shas["BASE_SHA"]}, "not the event's commit")
    refused({"BASE_SHA": shas["HEAD_SHA"]}, "first parent is not")
    refused({"HEAD_SHA": shas["BASE_SHA"]}, "second parent is not")
    refused({"EVENT_SHA": "main"}, "is not a commit id")
    refused({"BASE_SHA": ""}, "is not a commit id")


def test_a_failing_diff_writes_nothing(tmp_path):
    """
    The diff's exit status is read. With the base's tree gone from the object store, git diff fails after the merge
    is proven, and the answer is none.
    """
    repo, shas = _pull_request(tmp_path, {"docs/a.md": "b\n"})
    tree  = _fixture_git(repo, "rev-parse", f"{shas['BASE_SHA']}^{{tree}}")
    loose = repo / ".git" / "objects" / tree[:2] / tree[2:]
    loose.chmod(stat.S_IWRITE | stat.S_IREAD)
    loose.unlink()
    _stdout, output, summary = _answer(tmp_path, repo, shas)
    assert output == ""
    assert "git diff exited" in summary


@pytest.mark.parametrize("path, answer", [
    ("docs/x\n::warning title=pwned::injected.md", "docs_only=true\n"),
    ("src/x\n::error title=pwned::injected.py", ""),
], ids = ["docs", "code"])
def test_a_path_holding_a_newline_and_a_workflow_command_reaches_no_log_and_no_output(tmp_path, path, answer):
    """
    A path is the pull request's own text. The step prints none, writes only docs_only=true to the output file, and
    escapes each path it lists in the summary, so no newline of a path starts a line there.
    """
    repo, shas = _pull_request(tmp_path, {path: "x\n"})
    stdout, output, summary = _answer(tmp_path, repo, shas)
    assert output == answer
    assert "::" not in stdout and "pwned" not in stdout
    assert "pwned" not in output
    assert "\n::" not in summary and "pwned" in summary
    assert '\\n::' in summary

# ======================================================================================================================
# The skip input and the cancel
# ======================================================================================================================

@pytest.mark.parametrize("name", SKIP_LANES)
def test_every_billed_lane_takes_skip_with_a_default_that_runs_it(name):
    """
    A caller passes its docs only answer as skip, and a caller that passes nothing, a push, a schedule, a release
    dispatch or a repo not yet wired, runs the lane as before, so the input is optional and false by default.
    """
    assert re.search(
        r"\n      skip:\n        description: [^\n]+\n        type: boolean\n        default: false\n",
        _lane(name),
    ), name


@pytest.mark.parametrize("name", SKIP_LANES)
def test_every_job_of_a_billed_lane_reads_skip(name):
    """
    The skip sits inside the lane, on every job, so each required check `<caller> / <called>` reports skipped, which a
    ruleset counts as passing. A skip on the caller's job would report the caller's name alone and leave it pending.
    """
    jobs = _jobs(_lane(name))
    assert jobs
    for job_id, job in jobs.items():
        conditions = re.findall(r"^    if: (.+)$", job.split("    steps:\n", 1)[0], flags = re.MULTILINE)
        assert len(conditions) == 1 and "!inputs.skip" in conditions[0], f"{name} {job_id}"


@pytest.mark.parametrize("name", sorted(HAND_WRITTEN))
def test_every_job_outside_the_renderer_reads_skip_alone_and_no_cancel(name):
    """
    GitHub keeps a job whose if holds always() running through a cancel, and a step's cancelled() reads false inside
    it, so a guard step there never fires and a superseded run bills the job in full (cicd #307's cancelled runs). Each
    job the renderer does not write reads the skip input alone, so a cancelled run cancels it as it did before D-075,
    and the caller's !cancelled() keeps a cancel during the scan from entering the lane at all.
    """
    job  = _jobs(_lane(name))[HAND_WRITTEN[name]]
    head = job.split("    steps:\n", 1)[0]
    assert HAND_CONDITION in head and head.count("    if: ") == 1
    conditions = re.findall(r"^\s+if: (.+)$", job, flags = re.MULTILINE)
    assert not [condition for condition in conditions if "always()" in condition or "cancelled()" in condition]


@pytest.mark.parametrize("name", ["secret-scan.yml", "ci-codeql.yml", "fetch-private-packages.yml"])
def test_the_scan_codeql_and_the_standalone_fetch_take_no_skip(name):
    """
    The scan is what answers, CodeQL stays outside the fast path, dormant behind its variable, and the standalone fetch
    serves a caller's own install job, so none of the three has the input.
    """
    assert "\n      skip:\n" not in _lane(name)
    assert "inputs.skip" not in _lane(name)

# ======================================================================================================================
# This repo's probes
# ======================================================================================================================

@pytest.mark.parametrize("probe", sorted(SKIP_PROBES))
def test_each_skip_probe_calls_its_lane_with_skip_and_no_secret(probe):
    """
    The probes show on GitHub what a skipped lane reports, each job "<probe> / <job>" skipped with no runner, a one job
    lane, a split lane with package access asked for and the security lane. They pass no secret and wait for nothing.
    """
    job = _jobs(_lane("ci.yml"))[probe]
    assert f"    uses: ./.github/workflows/{SKIP_PROBES[probe]}\n" in job
    assert "      skip: true\n" in job
    assert "secrets" not in job and "    needs:" not in job and "    if:" not in job
    assert ("      needs_sdk_auth: true\n" in job) == (probe == "skip-probe-split")


def test_the_nested_probe_runs_a_scan_beside_a_skipped_lane_three_levels_down():
    """
    The kdf-sdk's merge gate calls its own ci.yml, so its lanes sit a level deeper than any other repo's. The nested
    probe is called by ci.yml alone and runs the scan beside a lane called with skip true.
    """
    nested = _lane("probe-nested.yml")
    assert "\non:\n  workflow_call:\n\n" in nested
    jobs = _jobs(nested)
    assert list(jobs) == ["secret-scan", "unit-tests"]
    assert jobs["secret-scan"] == "    uses: ./.github/workflows/secret-scan.yml\n\n"
    assert jobs["unit-tests"] == "    uses: ./.github/workflows/ci-nextjs-tests.yml\n    with:\n      skip: true\n"
    assert "    uses: ./.github/workflows/probe-nested.yml\n" in _jobs(_lane("ci.yml"))["skip-probe-nested"]


def test_the_lane_cancel_probe_waits_for_the_scan_on_not_cancelled_with_the_one_skip_expression():
    """
    Wired as a consumer's lane caller is, it waits for the scan on !cancelled(), which a job's own if reads true after a
    cancel, so a cancel during the scan never enters the lane and its checks never report, and it hands its lane the
    skip expression. The security lane's cancel probe went with the hand written guard it proved.
    """
    jobs = _jobs(_lane("ci.yml"))
    job  = jobs["cancel-probe-lane"]
    assert job.startswith("    needs: [secret-scan]\n    if: ${{ !cancelled() }}\n    uses: ./.github/workflows/")
    assert f"      skip: ${{{{ {SKIP_EXPRESSION} }}}}\n" in job
    assert "secrets" not in job
    assert "cancel-probe-security" not in jobs


def test_the_local_cancel_probe_is_a_consumers_local_job_with_the_scan_result_guard_first():
    """
    A local job's check is its own name, so one skipped on a cancel would report Success. It runs on always() and its
    first step fails it when the scan ended neither success nor failure, the signal a step does read after a cancel.
    """
    job = _jobs(_lane("ci.yml"))["cancel-probe-local"]
    assert f"    needs: [secret-scan]\n    if: ${{{{ always() && !({SKIP_EXPRESSION}) }}}}\n" in job
    first = job.split("    steps:\n", 1)[1].split("\n\n", 1)[0] + "\n"
    assert first == LOCAL_GUARD_STEP
    assert "cancelled()" not in job
    assert '} >> "$GITHUB_STEP_SUMMARY"' in job, "the scan's answer reaches the run summary"
