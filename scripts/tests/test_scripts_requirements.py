"""
The scripts' runtime packages, scripts/requirements.txt, each pinned to one exact version, the transitive ones too, so
every ops workflow installs what was reviewed before the step that holds its tokens, and never a newer release.
"""

from __future__ import annotations

# standard imports
import re
from pathlib import Path


REQUIREMENTS = Path(__file__).resolve().parents[1] / "requirements.txt"
PIN          = re.compile(r"(?P<name>[A-Za-z0-9][A-Za-z0-9._-]*)==(?P<version>[0-9]+(\.[0-9]+)*)")
# requests and PyNaCl and every package they install, written out, so a package added or dropped is a reviewed change
PACKAGES = {"requests", "pynacl", "certifi", "charset-normalizer", "idna", "urllib3", "cffi", "pycparser"}


def requirement_lines() -> list[str]:
    """
    The file's requirement lines, comments and blank lines left out.

    Returns:
        list[str]: the lines
    """
    lines = REQUIREMENTS.read_text(encoding = "utf-8").splitlines()
    return [line.strip() for line in lines if line.strip() and not line.strip().startswith("#")]


def test_every_requirement_is_one_exact_version() -> None:
    for line in requirement_lines():
        assert PIN.fullmatch(line), f"{line!r} is no exact pin, name==X.Y.Z"


def test_the_pins_are_the_runtime_packages_and_their_own() -> None:
    names = [PIN.fullmatch(line).group("name").lower() for line in requirement_lines()]
    assert len(names) == len(set(names)) and set(names) == PACKAGES
