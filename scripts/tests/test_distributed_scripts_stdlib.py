"""
Guard for the stdlib-only invariant of the vendored version scripts (ADR D-013).

bump_version.py states "Stdlib-only" in its own docstring, and that promise is the
whole reason the vendored copies work out of the gate: a tenant repo runs them from a
bare `python -m venv` with nothing installed. Nothing enforced it, so a single
`import requests` in scripts/common/ would ship to every repo in the registry and only
surface the next time someone ran `make bump-patch` — in 17 repos at once.

The check is deliberately AST-based rather than a regex: it sees imports nested inside
functions and inside the try/except ImportError blocks the scripts use to support both
the `common.` package path and the flat vendored path.
"""

from __future__ import annotations

import ast
import sys
from collections.abc import Iterator

import distribute_scripts as ds
import pytest

# Modules that resolve INSIDE the vendor directory rather than to a distribution.
# version_targets is a sibling script shipped alongside; `common` is the cicd-side
# package the same file is imported through before it is vendored, which is why the
# scripts carry `try: from common import version_targets / except ImportError:`.
VENDOR_SIBLINGS = frozenset({"version_targets", "common"})

# Read once at collection so a broken registry fails loudly here rather than in a loop.
DISTRIBUTED_SRCS = [entry["src"] for entry in ds._load_registry().get("files", [])]


def _imported_roots(source: str) -> Iterator[str]:
    """
    Yield the top-level module name of every import in a source file.

    Walks the whole tree, so imports inside functions and except-handlers count.
    Relative imports are skipped: they resolve within the vendor directory and can
    never reach a third-party distribution.

    Args:
        source: the Python source to inspect

    Returns:
        Iterator[str]: the first dotted segment of each imported module
    """
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            for alias in node.names:
                yield alias.name.split(".")[0]
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                continue
            if node.module:
                yield node.module.split(".")[0]


def test_registry_lists_scripts_to_check() -> None:
    """
    A registry that lists nothing would make every check below vacuously pass.
    """
    assert DISTRIBUTED_SRCS, "scripts_registry.json files[] is empty -- nothing is being guarded"


@pytest.mark.parametrize("src", DISTRIBUTED_SRCS)
def test_distributed_script_is_stdlib_only(src: str) -> None:
    """
    Every import in a distributed script must resolve to the stdlib or a vendor sibling.

    Args:
        src: repo-relative path of a canonical script from the registry
    """
    source    = (ds.REPO_ROOT / src).read_text(encoding = "utf-8")
    offenders = sorted(
        {
            root
            for root in _imported_roots(source)
            if root not in sys.stdlib_module_names and root not in VENDOR_SIBLINGS
        }
    )
    assert not offenders, (
        f"{src} imports non-stdlib module(s): {', '.join(offenders)}.\n"
        "The vendored scripts run in a bare venv in every tenant repo, so they must "
        "stay dependency-free. Either drop the import or move that work into cicd, "
        "which is not vendored."
    )
