"""
cicd's own workflows hardened for the local code scan (D-085, design 5.7, plan step 9). No single value input reaches a
run's shell by template expansion, each now read from the step's environment. A caller's command input, run as the
caller's command by design, is accepted on its own `run:` line with the reason. Every App token names its
repositories. The steps that took a value are run here on a value made to break out, and it arrives as one value.
"""
from __future__ import annotations

# standard imports
import os
import re
import shutil
import subprocess
from pathlib import Path

# third party imports
import pytest

# local imports
import common.kdf_scan as SCAN

# ======================================================================================================================
# Configuration
# ======================================================================================================================

ROOT      = Path(__file__).resolve().parents[2]
WORKFLOWS = ROOT / ".github" / "workflows"

EXPANSION  = re.compile(r"\$\{\{\s*inputs\.([A-Za-z0-9_]+)\s*\}\}")
RUN_KEY    = re.compile(r"^(?P<indent>\s*)(?:- )?run:\s?(?P<value>.*)$")
ACCEPTANCE = re.compile(r"^\s*run: \$\{\{ inputs\.[a-z_]+_command \}\}  # zizmor: ignore\[template-injection\] (?P<why>.+)$")
# a value made to break out of a shell, a space, both quotes, a semicolon and a command substitution
HOSTILE = "1.0 \" ' ; touch pwned ; $(touch pwned)"

# ======================================================================================================================
# Helpers
# ======================================================================================================================

def workflow_files() -> list[Path]:
    return sorted(WORKFLOWS.glob("*.yml"))


def runs(text: str) -> list[tuple[int, str, list[str]]]:
    """
    Every `run:` in a workflow, its line number, its own line and the lines of its script.
    """
    lines  = text.splitlines()
    found  = []
    index  = 0
    while index < len(lines):
        match = RUN_KEY.match(lines[index])
        if not match:
            index += 1
            continue
        value  = match["value"].split("  #", 1)[0].strip()
        script = [value]
        if value in ("|", ">", "|-", ">-"):
            depth  = len(match["indent"]) + (2 if lines[index].lstrip().startswith("- ") else 0)
            script = []
            for line in lines[index + 1:]:
                if line.strip() and len(line) - len(line.lstrip(" ")) <= depth:
                    break
                script.append(line)
        found.append((index + 1, lines[index], script))
        index += 1
    return found


def step_run(path: Path, name: str) -> str:
    """
    One named step's run script, a block's lines with their indent taken off or a one line value.
    """
    lines = path.read_text(encoding = "utf-8").splitlines()
    start = next(index for index, line in enumerate(lines) if line.strip() == f"- name: {name}")
    depth = len(lines[start]) - len(lines[start].lstrip(" "))
    for index in range(start + 1, len(lines)):
        line = lines[index]
        if line.strip() and len(line) - len(line.lstrip(" ")) <= depth:
            break
        match = RUN_KEY.match(line)
        if match and not line.lstrip().startswith("- "):
            value = match["value"].strip()
            if value not in ("|", ">"):
                return value + "\n"
            inner = len(match["indent"])
            body  = []
            for more in lines[index + 1:]:
                if more.strip() and len(more) - len(more.lstrip(" ")) <= inner:
                    break
                body.append(more)
            width = min(len(more) - len(more.lstrip(" ")) for more in body if more.strip())
            return "\n".join(more[width:] for more in body) + "\n"
    raise AssertionError(f"{path.name} has no run in its step {name}")


def bash() -> str | None:
    """
    A bash that runs a step's shell here. Git's on Windows, since System32's is WSL and may hold no distribution.
    """
    git_bash = Path("C:/Program Files/Git/bin/bash.exe")
    if git_bash.exists():
        return str(git_bash)
    return None if os.name == "nt" else shutil.which("bash")


def run_step(tmp_path: Path, script: str, env: dict[str, str], tool: str) -> list[str]:
    """
    A step's shell run in a fresh folder with a stand in for the tool it calls, which prints each argument on a line of
    its own. Returns those arguments, and fails the test when the step ran anything the value held.
    """
    shell = bash()
    if shell is None:
        pytest.skip("no bash to run the step's shell")
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(parents = True)
    stand_in = bin_dir / tool
    stand_in.write_text("#!/usr/bin/env bash\nprintf '%s\\n' \"$@\" > \"$KDF_ARGS\"\n", encoding = "utf-8", newline = "\n")
    stand_in.chmod(0o755)
    (tmp_path / "step.sh").write_text(script, encoding = "utf-8", newline = "\n")
    args = tmp_path / "args.txt"
    # Git Bash turns a Windows PATH into its own at start, so the stand in leads the search on either system
    environment = {**os.environ, **env, "PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}", "KDF_ARGS": str(args)}
    subprocess.run([shell, "step.sh"], cwd = tmp_path, env = environment, capture_output = True, check = False)
    assert not (tmp_path / "pwned").exists(), "the step ran a command the value held"
    return args.read_text(encoding = "utf-8").splitlines() if args.exists() else []

# ======================================================================================================================
# No single value input expanded in a shell
# ======================================================================================================================

@pytest.mark.parametrize("path", workflow_files(), ids = lambda path: path.name)
def test_no_single_value_input_is_expanded_in_a_run(path: Path) -> None:
    for number, line, script in runs(path.read_text(encoding = "utf-8")):
        for name in EXPANSION.findall("\n".join(script)):
            assert name.endswith("_command"), f"{path.name}:{number} expands inputs.{name} in a shell"
            assert ACCEPTANCE.match(line), f"{path.name}:{number} runs inputs.{name} with no acceptance on its line"


@pytest.mark.parametrize("path", workflow_files(), ids = lambda path: path.name)
def test_each_command_input_is_accepted_on_its_run_line_with_a_reason_the_wrapper_takes(path: Path) -> None:
    for number, line, _script in runs(path.read_text(encoding = "utf-8")):
        match = ACCEPTANCE.match(line)
        if match:
            assert SCAN.good_reason(match["why"]) == "", f"{path.name}:{number} {SCAN.good_reason(match['why'])}"

# ======================================================================================================================
# Every App token names its repositories
# ======================================================================================================================

@pytest.mark.parametrize("path", workflow_files(), ids = lambda path: path.name)
def test_every_app_token_names_its_repositories(path: Path) -> None:
    lines = path.read_text(encoding = "utf-8").splitlines()
    for index, line in enumerate(lines):
        if "uses: actions/create-github-app-token@" not in line:
            continue
        depth = len(line) - len(line.lstrip(" "))
        step  = []
        for more in lines[index + 1:]:
            if more.strip() and len(more) - len(more.lstrip(" ")) <= depth - 2:
                break
            step.append(more)
        assert any(more.strip().startswith("repositories:") for more in step), f"{path.name}:{index + 1}"

# ======================================================================================================================
# The changed steps, run on a value made to break out
# ======================================================================================================================

@pytest.mark.parametrize(
    ("step", "variable", "tool", "expected"),
    [
        ("Install bandit", "BANDIT_VERSION", "pip", f"bandit[toml]=={HOSTILE}"),
        ("Install pip-audit", "PIP_AUDIT_VERSION", "pip", f"pip-audit=={HOSTILE}"),
    ],
)
def test_a_pinned_tools_version_arrives_as_one_value(
    tmp_path: Path,
    step: str,
    variable: str,
    tool: str,
    expected: str,
) -> None:
    script = step_run(WORKFLOWS / "ci-python-security.yml", step)
    assert "${{" not in script
    assert run_step(tmp_path, script, {variable: HOSTILE}, tool) == ["install", expected]


def test_bandit_paths_split_into_its_paths_and_a_hostile_path_stays_one(tmp_path: Path) -> None:
    script = step_run(WORKFLOWS / "ci-python-security.yml", "Run bandit")
    assert "${{" not in script
    args = run_step(tmp_path / "two", script, {"BANDIT_PATHS": "api/ scripts/"}, "python")
    assert args == ["-m", "bandit", "-r", "api/", "scripts/", "-ll", "--format", "txt"]
    # one path, no space since the list splits on spaces by design, a substitution any evaluation would run
    hostile = "$(touch${IFS}pwned);touch\"pwned'*"
    args    = run_step(tmp_path / "one", script, {"BANDIT_PATHS": hostile}, "python")
    assert args == ["-m", "bandit", "-r", hostile, "-ll", "--format", "txt"]


@pytest.mark.parametrize("workflow", ["cd-nextjs-vercel.yml", "cd-python-vercel.yml"])
def test_the_vercel_binding_check_prints_the_environment_as_one_value(tmp_path: Path, workflow: str) -> None:
    script = step_run(WORKFLOWS / workflow, "Validate Vercel project binding")
    assert "${{" not in script
    shell = bash()
    if shell is None:
        pytest.skip("no bash to run the step's shell")
    (tmp_path / "step.sh").write_text(script, encoding = "utf-8", newline = "\n")
    environment = {**os.environ, "DEPLOY_ENVIRONMENT": HOSTILE, "VERCEL_PROJECT_ID": ""}
    done = subprocess.run(
        [shell, "step.sh"],
        cwd = tmp_path,
        env = environment,
        capture_output = True,
        text = True,
        encoding = "utf-8",
        check = False,
    )
    assert done.returncode == 1 and f"'{HOSTILE}' environment" in done.stdout, done.stdout
    assert not (tmp_path / "pwned").exists()
