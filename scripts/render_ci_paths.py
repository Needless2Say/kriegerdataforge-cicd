"""
Write `ci_paths.py` into the secret scan's last step, the one list of what counts as docs (D-075).

A reusable workflow cannot be trusted to check out this repo at its own commit when another repo calls it, D-035's
reason for writing the fetch job into each lane. So the scan's `Docs only` step carries `scripts/common/ci_paths.py`'s
own text in a heredoc, written there by this script, and `test_workflow_contracts.py` fails when the copy differs. The
script's text holds no expression and no line that would end the heredoc, both refused here, so every value reaches it
through the step's environment.

Usage:
    python scripts/render_ci_paths.py           # write the copy
    python scripts/render_ci_paths.py --check   # exit 1 when the copy differs from the script

Standard library only.
"""

from __future__ import annotations

# standard imports
import argparse
import sys
from pathlib import Path

# ======================================================================================================================
# Configuration
# ======================================================================================================================

ROOT     = Path(__file__).resolve().parents[1]
SCRIPT   = ROOT / "scripts" / "common" / "ci_paths.py"
WORKFLOW = ROOT / ".github" / "workflows" / "secret-scan.yml"

DELIMITER = "KDF_CI_PATHS"
INDENT    = " " * 10

# the heredoc's first line, and its last, between which the copy sits
OPENER = f"<<'{DELIMITER}'\n"
CLOSER = f"{INDENT}{DELIMITER}\n"

# ======================================================================================================================
# Rendering
# ======================================================================================================================

def _read(path: Path) -> str:
    """
    A file's text with its own line endings, which read_text would turn into LF.

    Args:
        path: the file

    Returns:
        str: its text
    """
    return path.read_bytes().decode("utf-8")


def body() -> str:
    """
    The script's text indented for the step's run block, ready to sit between the heredoc's ends.

    Returns:
        str: the indented text, LF line ends

    Raises:
        SystemExit: when the script holds an expression or a line that would end the heredoc
    """
    script = _read(SCRIPT).replace("\r\n", "\n")
    if "${{" in script or f"\n{DELIMITER}\n" in f"\n{script}\n":
        raise SystemExit("ci_paths.py must hold no ${{ and no line that ends the heredoc")
    return "".join(f"{INDENT}{line}\n" if line else "\n" for line in script.rstrip("\n").split("\n"))


def render(text: str) -> str:
    """
    The workflow with the script's text written between the heredoc's ends.

    Args:
        text: the workflow's text

    Returns:
        str: the workflow's new text, in its own line endings

    Raises:
        SystemExit: when the workflow does not hold the heredoc's two ends exactly once
    """
    crlf  = "\r\n" in text
    plain = text.replace("\r\n", "\n")
    if plain.count(OPENER) != 1 or plain.count(CLOSER) != 1:
        raise SystemExit(f"secret-scan.yml must hold the heredoc {DELIMITER} exactly once")
    head, rest = plain.split(OPENER, 1)
    _old, tail = rest.split(CLOSER, 1)
    plain = head + OPENER + body() + CLOSER + tail
    return plain.replace("\n", "\r\n") if crlf else plain


def copy(text: str) -> str:
    """
    The script's text as the workflow holds it, dedented, for the test that holds it equal to the script.

    Args:
        text: the workflow's text

    Returns:
        str: the copy, LF line ends
    """
    rest  = text.replace("\r\n", "\n").split(OPENER, 1)[1].split(CLOSER, 1)[0]
    lines = rest.rstrip("\n").split("\n")
    return "".join(f"{line[len(INDENT):]}\n" for line in lines)

# ======================================================================================================================
# CLI
# ======================================================================================================================

def main(argv: list[str] | None = None) -> int:
    """
    Write the copy, or with --check report that it differs.

    Args:
        argv: the arguments, sys.argv when None

    Returns:
        int: 1 when --check finds the copy differs, else 0
    """
    parser = argparse.ArgumentParser(description = "Write ci_paths.py into the secret scan's last step.")
    parser.add_argument("--check", action = "store_true", help = "exit 1 when the copy differs, write nothing")
    args    = parser.parse_args(argv)
    current = _read(WORKFLOW)
    wanted  = render(current)
    if current == wanted:
        return 0
    print(f"{'differs' if args.check else 'written'}: {WORKFLOW.name}")
    if args.check:
        return 1
    WORKFLOW.write_text(wanted, encoding = "utf-8", newline = "")
    return 0


if __name__ == "__main__":
    sys.exit(main())
