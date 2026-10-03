"""
The test tooling the deploying repos share, held equal wherever their checkouts sit beside this one.

The Node mutation runner and the system harness are copies and not packages (D-027). The auth UI's runner is the Node
original, and the two tenant frontends hold it byte for byte with its own test. The two tenant backends hold one system
harness. The Python mutation runner is one engine, this repo's scripts/common/mutation_runner.py, vendored by the
scripts sync to every repo that runs Python mutants (D-040). A fix made to one copy and not the others leaves a release
judged by a runner that behaves differently in the next repo, so the copies are compared here, where the repos sit side
by side. On a runner this repo is alone and every case reports itself skipped.
"""

from __future__ import annotations

from pathlib import Path

import pytest

WORKSPACE = Path(__file__).resolve().parents[3]

# a file several repos hold, the repos that hold it, the first holds the original
SHARED = {
    "the Node mutation runner": (
        "mutation_tests/run.mjs",
        ("kriegerdataforge-auth-ui", "fitness-app-frontend", "tiffanys-space"),
    ),
    "the Node runner's own test": (
        "src/__tests__/mutation-runner.test.ts",
        ("kriegerdataforge-auth-ui", "fitness-app-frontend", "tiffanys-space"),
    ),
    "the system harness": ("system_tests/harness.py", ("fitness-app-backend", "tiffanys-space-backend")),
    "the system fixtures": ("system_tests/conftest.py", ("fitness-app-backend", "tiffanys-space-backend")),
}

# the repos that run Python mutants, where the scripts sync vendors the shared engine (D-040)
PYTHON_MUTANT_REPOS: tuple[str, ...] = (
    "kriegerdataforge",
    "kriegerdataforge-sdk",
    "fitness-app-backend",
    "tiffanys-space-backend",
)

# the engine as a repo holds it, and the runner of its own a repo held before it moved
VENDORED_ENGINE: str = "scripts/kdf_scripts/mutation_runner.py"
OWN_RUNNER:      str = "mutation_tests/run.py"


def _text(repo: str, name: str) -> str:
    """
    One file of a sibling repo, its line ends the runner's, or a skip when the repo is not beside this one.
    """
    if not (WORKSPACE / repo).is_dir():
        pytest.skip(f"{repo} is not checked out beside this repo")
    path = WORKSPACE / repo / name
    assert path.is_file(), f"{repo} holds no {name}"
    return path.read_text(encoding = "utf-8").replace("\r\n", "\n")


@pytest.mark.parametrize("what", sorted(SHARED))
def test_every_copy_is_the_same_file(what):
    name, repos = SHARED[what]
    found  = {repo: _text(repo, name) for repo in repos}
    differ = sorted(repo for repo, text in found.items() if text != found[repos[0]])
    assert differ == [], f"{what}, {name}, differs from {repos[0]}'s in {differ}"


def test_every_repo_that_moved_to_the_shared_engine_holds_the_same_engine():
    """
    A repo that moved deleted its own runner and runs the engine the scripts sync vendored, so every such repo holds
    one file. A repo that still holds a runner of its own has not moved, and the reusable lane runs its own until then.
    """
    present = [repo for repo in PYTHON_MUTANT_REPOS if (WORKSPACE / repo).is_dir()]
    if not present:
        pytest.skip("no repo that runs Python mutants is checked out beside this repo")
    moved  = [repo for repo in present if not (WORKSPACE / repo / OWN_RUNNER).is_file()]
    found  = {repo: _text(repo, VENDORED_ENGINE) for repo in moved}
    differ = sorted(repo for repo, text in found.items() if text != found[moved[0]])
    assert differ == [], f"the engine differs from {moved[0]}'s in {differ}, run the scripts sync"


def test_each_tenant_backend_says_what_it_alone_knows_in_a_file_of_its_own():
    """
    The harness is shared, so what one backend alone knows, its name, its prefix and its databases, is in its own
    `system_tests/tenant.py`, and two tenants never share a database name.
    """
    names = {}
    for repo in SHARED["the system harness"][1]:
        text = _text(repo, "system_tests/tenant.py")
        for constant in ("SERVICE", "PREFIX", "SHARED_DATABASES", "SETTINGS"):
            assert f"\n{constant}:" in text, f"{repo} names no {constant}"
        names[repo] = text
    assert len(set(names.values())) == len(names), "two tenants hold the same tenant file"
