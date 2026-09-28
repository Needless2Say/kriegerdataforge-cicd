"""
The test tooling the deploying repos share, held equal wherever their checkouts sit beside this one.

The mutation runners and the system harness are copies and not packages (D-027). The auth UI's runner is the Node
original, and the two tenant frontends hold it byte for byte with its own test. The two tenant backends hold one
Python runner, the hub's less the signing keypair the hub's unit suite needs, and one system harness. A fix made to one
copy and not the others leaves a release judged by a runner that behaves differently in the next repo, so the copies
are compared here, where the repos sit side by side. On a runner this repo is alone and every case reports itself
skipped.
"""

from __future__ import annotations

import ast
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
    "the Python mutation runner": ("mutation_tests/run.py", ("fitness-app-backend", "tiffanys-space-backend")),
    "the system harness": ("system_tests/harness.py", ("fitness-app-backend", "tiffanys-space-backend")),
    "the system fixtures": ("system_tests/conftest.py", ("fitness-app-backend", "tiffanys-space-backend")),
}

# what the tenants' Python runner holds as the hub's does, every rule of how a mutant is applied, run, read and restored
SAME_AS_THE_HUBS = (
    "MutantTableError",
    "Mutant",
    "parse_mutants",
    "load_table",
    "apply_mutant",
    "classify",
    "changed_paths",
    "_git",
    "prepare_worktree",
    "run_pytest",
    "_masked",
    "Result",
    "run_mutant",
    "summary",
    "exit_status",
)


def _text(repo: str, name: str) -> str:
    """
    One file of a sibling repo, its line ends the runner's, or a skip when the repo is not beside this one.
    """
    if not (WORKSPACE / repo).is_dir():
        pytest.skip(f"{repo} is not checked out beside this repo")
    path = WORKSPACE / repo / name
    assert path.is_file(), f"{repo} holds no {name}"
    return path.read_text(encoding = "utf-8").replace("\r\n", "\n")


def _definitions(source: str) -> dict[str, str]:
    """
    Each top level function and class of a module, by name, as written.
    """
    tree  = ast.parse(source)
    kinds = (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)
    return {node.name: ast.get_source_segment(source, node) or "" for node in tree.body if isinstance(node, kinds)}


@pytest.mark.parametrize("what", sorted(SHARED))
def test_every_copy_is_the_same_file(what):
    name, repos = SHARED[what]
    found  = {repo: _text(repo, name) for repo in repos}
    differ = sorted(repo for repo, text in found.items() if text != found[repos[0]])
    assert differ == [], f"{what}, {name}, differs from {repos[0]}'s in {differ}"


def test_the_tenants_python_runner_applies_runs_and_reads_a_mutant_as_the_hubs_does():
    """
    A fix to how a mutant is applied, restored or read as killed belongs in every runner, the class of bug is the
    same. The two may differ in the unit suite's settings, the keypair and the default worktree path alone.
    """
    hub    = _definitions(_text("kriegerdataforge", "mutation_tests/run.py"))
    tenant = _definitions(_text("fitness-app-backend", "mutation_tests/run.py"))
    differ = sorted(name for name in SAME_AS_THE_HUBS if hub.get(name) != tenant.get(name))
    assert differ == [], f"the tenants' runner differs from the hub's in {differ}"
    assert "throwaway_keypair" in hub and "throwaway_keypair" not in tenant, "the tenants sign no token"


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
