"""
Tests for D-054, kdf-fmt declared once, at main in each repo's requirements-dev.in.

The fetch lets the formatter's repo alone be named at a branch in a requirement file, resolved once to its commit.
Both style lanes read the formatter's ref from the caller's requirements-dev.in with one text, the URL fixed, and fail
by name when the line is missing or names another URL. The watch reads a ci.yml override of main as tracking main.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
import textwrap
from pathlib import Path

import ecosystem_watch as ew
import fetch_private_packages as fpp
import pytest

ROOT      = Path(__file__).resolve().parents[2]
WORKFLOWS = ROOT / ".github" / "workflows"
FMT_URL   = "git+https://github.com/Needless2Say/kriegerdataforge-fmt.git"
LANES     = ("ci-python-kdf-fmt.yml", "ci-kdf-fmt-public.yml")


class FakeGit:
    """
    Records every git call, answers ls-remote from a table, and fails no fetch.
    """
    def __init__(self, remotes: dict[str, str]):
        self.remotes = remotes
        self.calls: list[list[str]] = []


    def __call__(self, args: list[str]) -> str:
        self.calls.append(args)
        if args[0] == "ls-remote":
            return self.remotes[args[-1].rsplit("/", 1)[1].removesuffix(".git")]
        if args[0] == "init":
            Path(args[-1]).mkdir(parents = True)
        return ""


def _text(name: str) -> str:
    return (WORKFLOWS / name).read_bytes().decode("utf-8").replace("\r\n", "\n")


def _formatter_reader(name: str) -> str:
    """
    The Python a style lane runs to read the formatter's ref, taken out of its heredoc.
    """
    body = _text(name).split("          python -I - <<'KDF_FORMATTER_REF'\n", 1)[1]
    return textwrap.dedent(body.split("          KDF_FORMATTER_REF\n", 1)[0])


def _pins(repo: str, ref: str, source: str) -> dict:
    return {
        "caller_private": True,
        "repositories": [repo],
        "extras": [],
        "scan": [],
        "pins": [{"repo": repo, "ref": ref, "sources": [source]}],
    }

# ======================================================================================================================
# the fetch
# ======================================================================================================================

def test_the_formatter_at_a_branch_in_requirements_dev_in_is_fetched_at_one_commit(tmp_path: Path) -> None:
    """
    Every repo declares kdf-fmt at main in requirements-dev.in, with no lock beside it. The fetch resolves the branch
    once and sets the mirror's branch to that commit, so a move of the branch afterward changes nothing.
    """
    head    = "5" * 40
    git     = FakeGit({"kriegerdataforge-fmt": f"{head}\trefs/heads/main\n{'6' * 40}\trefs/tags/v1.3.0"})
    entries = fpp.fetch(_pins("kriegerdataforge-fmt", "main", "requirements-dev.in"), tmp_path, git)
    assert [(entry["ref"], entry["kind"], entry["sha"]) for entry in entries] == [("main", "branch", head)]
    fetch = next(call for call in git.calls if "fetch" in call)
    assert f"{head}:refs/heads/main" in fetch, "the mirror's main is the commit resolved once"
    assert not [part for part in fetch if part.endswith("refs/heads/main") and not part.startswith(head)], \
        "the live branch is never fetched by name"
    assert sum(1 for call in git.calls if call[0] == "ls-remote") == 1, "the branch is read once"


@pytest.mark.parametrize("repo", ["kriegerdataforge-sdk", "kriegerdataforge-reports-sdk"])
def test_any_other_repo_at_a_branch_in_requirements_dev_in_is_still_refused(tmp_path: Path, repo: str) -> None:
    git = FakeGit({repo: f"{'1' * 40}\trefs/heads/main"})
    with pytest.raises(fpp.FetchError, match = f"requirements-dev.in: {repo}@main is a branch"):
        fpp.fetch(_pins(repo, "main", "requirements-dev.in"), tmp_path, git)
    assert not any("fetch" in call for call in git.calls)

# ======================================================================================================================
# the style lanes
# ======================================================================================================================

def test_both_style_lanes_read_the_formatters_ref_with_one_text_and_install_that_ref() -> None:
    assert _formatter_reader(LANES[0]) == _formatter_reader(LANES[1])
    for name in LANES:
        text = _text(name)
        # the input's whole block, every line indented below its name, so a key added anywhere in it is seen
        given = re.search(r"^      kdf_fmt_ref:\n((?:        .*\n)+)", text, re.MULTILINE).group(1)
        assert "        type: string\n        default: \"\"\n" in given, name
        assert "required" not in given, f"{name} keeps kdf_fmt_ref an override, never required"
        assert "        id: formatter\n" in text
        assert "          KDF_FMT_REF: ${{ steps.formatter.outputs.ref }}\n" in text, f"{name} installs the ref it read"
        assert text.count("${{ inputs.kdf_fmt_ref }}") == 1, f"{name} reads the input in the step that reads the ref"


@pytest.mark.parametrize("override, dev_in, ref, says", [
    ("", f"pytest>=8\nkdf-fmt @ {FMT_URL}@main\n", "main", None),
    ("", f"kdf-fmt @ {FMT_URL}@v1.3.0  # the formatter\r\n", "v1.3.0", None),
    ("", f"# kdf-fmt @ {FMT_URL}@v1.1.0\nkdf-fmt @ {FMT_URL}@main\n", "main", None),
    ("v1.3.0", f"kdf-fmt @ {FMT_URL}@main\n", "v1.3.0", None),
    ("v1.3.0", None, "v1.3.0", None),
    ("", None, None, "requirements-dev.in is missing"),
    ("", "pytest>=8\n", None, "names kdf-fmt once"),
    ("", "kdf-fmt @ git+https://github.com/someone/kriegerdataforge-fmt.git@main\n", None, "names kdf-fmt once"),
    ("", f"kdf-fmt @ {FMT_URL}@main\nkdf_fmt==1.3.0\n", None, "names kdf-fmt once"),
    ("", f"kdf-fmt @ {FMT_URL}@main\nkdf--fmt @ git+https://x.org/y.git@main\n", None, "names kdf-fmt once"),
    ("", f"KDF__FMT==1.0\nkdf-fmt @ {FMT_URL}@main\n", None, "names kdf-fmt once"),
    ("", f"kdf-fmt @ {FMT_URL}@main;rm\n", None, "names kdf-fmt once"),
    ("main; rm -rf /", None, None, "not a git ref"),
])
def test_the_style_lanes_read_the_formatters_ref_or_fail_by_name(
    tmp_path: Path,
    override: str,
    dev_in: str | None,
    ref: str | None,
    says: str | None,
) -> None:
    """
    The ref comes from the caller's requirements-dev.in, the URL never does, and a file or a line that is missing,
    names kdf-fmt twice or names another URL fails the job by name, before anything is installed.
    """
    if dev_in is not None:
        (tmp_path / "requirements-dev.in").write_text(dev_in, encoding = "utf-8", newline = "")
    output = tmp_path / "github_output"
    output.write_text("", encoding = "utf-8")
    done = subprocess.run(
        [sys.executable, "-I", "-"],
        input = _formatter_reader(LANES[0]),
        cwd = tmp_path,
        capture_output = True,
        text = True,
        env = {**os.environ, "KDF_FMT_REF": override, "GITHUB_OUTPUT": str(output)},
    )
    if says is None:
        assert done.returncode == 0, done.stderr
        assert output.read_text(encoding = "utf-8") == f"ref={ref}\n"
    else:
        assert done.returncode == 1 and says in done.stderr, done.stderr
        assert output.read_text(encoding = "utf-8") == "", "nothing is handed on to the install"

# ======================================================================================================================
# this repo's own check
# ======================================================================================================================

@pytest.mark.parametrize("target", ["style", "ci-style"])
def test_this_repos_style_recipes_refresh_the_formatter_before_every_check(target: str) -> None:
    """
    An import that succeeds proves only that some formatter is installed, so the recipe never skips the install on it.
    It reinstalls from ci.yml's kdf_fmt_ref each time, which moves a branch to its newest commit, and stops when no
    ref is found or the install fails.
    """
    makefile = (ROOT / "Makefile").read_text(encoding = "utf-8").replace("\r\n", "\n")
    recipe   = makefile.split(f"\n{target}: ", 1)[1].split("\n\n", 1)[0]
    assert "import kdf_fmt" not in recipe, f"{target} never skips the install when an older formatter is there"
    assert '\n\t@[ -n "$(KDF_FMT_VERSION)" ] || ' in recipe, f"{target} stops when ci.yml names no ref"
    assert f'\n\t@$(PIP_GIT_AUTH) $(PYTHON) -m pip install --quiet \\\n\t\t"kdf-fmt @ {FMT_URL}@$(KDF_FMT_VERSION)"' \
        in recipe
    assert not re.search(r"^\t@?-", recipe, re.MULTILINE), f"{target} ignores no failure, a failed install stops it"
    assert "grep -oE 'v[0-9.]+'" not in makefile, "the ref is read whatever it is, main included"

# ======================================================================================================================
# the watch
# ======================================================================================================================

def test_the_watch_reads_an_override_of_main_and_no_pin_where_there_is_none() -> None:
    override = "jobs:\n  style:\n    with:\n      kdf_fmt_ref: main\n"
    assert [pin["ref"] for pin in ew.find_pins(".github/workflows/ci.yml", override)] == ["main"]
    assert ew.find_pins(".github/workflows/ci.yml", "jobs:\n  style:\n    secrets: inherit\n") == [], \
        "a style lane with no override names no pin, requirements-dev.in does"
    assert ew.judge("main", ew.Release("v1.3.0", "1" * 40, {}))["note"] == "tracks main"
