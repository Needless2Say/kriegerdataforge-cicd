"""
The tickets tool's command line, one positional command, no abbreviated options and no response files, --help
answering before anything else is read, and every usage refused with exit 3.
"""

from __future__ import annotations

# standard imports
import argparse
import os
import sys
from pathlib import Path
from typing import NoReturn

# third party imports
from kdf_tickets import check as checking
from kdf_tickets.common import CLEAN, FOUND, REFUSED, Refusal
from kdf_tickets.config import REGISTRY

# module constants
HELP = """\
Every command runs against one worktree of a repo, --root, and reads its docs/tickets/. A session runs it from the
cicd clone, or from a cicd worktree at a release, and works on a branch, never in a shared clone. Nothing in this
release writes an issue or a board.

Exit codes. 0 clean or in step, 1 problems or differences found, 2 a conflict (plan), 3 a run refused, a usage, a
config, a fence or a reviewer's call among them.
"""


class Parser(argparse.ArgumentParser):
    """
    An argument parser that ends a refused usage with the tool's refusal code rather than argparse's 2.
    """
    def error(self, message: str) -> NoReturn:
        """
        Print the usage and the message, and exit with the refusal code.

        Args:
            message: what argparse refused

        Returns:
            NoReturn: never, it exits
        """
        self.print_usage(sys.stderr)
        self.exit(REFUSED, f"{self.prog}: {message}\n")


def parser() -> Parser:
    """
    Build the parser, each command a subparser with its own options.

    Returns:
        Parser: the parser
    """
    top      = Parser(
        prog = "kdf-tickets.sh",
        description = "A repo's tickets as YAML files in docs/tickets/, kept in step with GitHub's issues.",
        epilog = HELP,
        formatter_class = argparse.RawDescriptionHelpFormatter,
        allow_abbrev = False,
    )
    commands = top.add_subparsers(dest = "command", required = True, metavar = "<command>")
    for name, summary in (
        ("check", "every file's form, fields, ids, parents, identity and the config, offline"),
        ("fmt", "rewrite the ticket files into the canonical form"),
    ):
        command = commands.add_parser(name, help = summary, description = summary, allow_abbrev = False)
        command.add_argument("--root", type = Path, required = True, help = "a worktree of the repo")
        command.add_argument("--registry", type = Path, default = REGISTRY, help = "the boards' registry, for tests")
    return top


def run(args: argparse.Namespace) -> int:
    """
    Run one command.

    Args:
        args: the parsed arguments

    Returns:
        int: the exit code

    Raises:
        Refusal: for a worktree with no tickets folder, or a refusal of the command
    """
    root = args.root.resolve()
    if not (root / "docs" / "tickets").is_dir():
        raise Refusal(f"{root} has no docs/tickets/. Name a worktree of a repo that keeps tickets")
    if args.command == "check":
        problems = checking.check(root, args.registry)
        for problem in problems:
            print(problem)
        print(f"check: {len(problems)} problems" if problems else "check: clean")
        return FOUND if problems else CLEAN
    written, problems = checking.fmt(root)
    for name in written:
        print(f"rewritten {name}")
    for problem in problems:
        print(problem)
    return FOUND if problems else CLEAN


def main(argv: list[str] | None = None) -> int:
    """
    Refuse a reviewer before anything, help included, then parse the arguments and run.

    Args:
        argv: the arguments, sys.argv's by default

    Returns:
        int: the exit code
    """
    if os.environ.get("KDF_ROLE") == "reviewer":
        print("kdf-tickets: a session in the reviewer role never runs the tickets tool", file = sys.stderr)
        return REFUSED
    args = parser().parse_args(argv)
    try:
        return run(args)
    except Refusal as refusal:
        print(f"kdf-tickets: {refusal}", file = sys.stderr)
        return refusal.code
