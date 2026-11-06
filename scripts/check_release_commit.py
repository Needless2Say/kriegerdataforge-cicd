"""
The release check for the KriegerDataForge CD workflows, a release deploys only a commit that is on `main`.

A deploy names a version, and its tag `v<version>` is a ref anyone with push rights could have made on any commit. A
branch rule on the environment binds the run's ref, never the code the run checks out. So before any job that names
an environment, the release job of `cd-python-vercel.yml` and `cd-nextjs-vercel.yml` checks out the caller with its
whole history and its tags and runs this. It resolves the tag to a commit, an annotated tag peeled to the commit it
names, refuses unless that commit is reachable from `origin/main`, whose every commit the owner merged, and prints the
commit. Every later job checks out that commit by its SHA and compares its checkout with it, never the tag, so a tag
moved after this check changes nothing they deploy.

Decision:
  - a version that is not MAJOR.MINOR.PATCH                      -> REFUSE (exit 1), git is never asked
  - a shallow history, or no origin/main                         -> REFUSE (exit 1), the answer is unknowable
  - no tag v<version>                                            -> REFUSE (exit 1)
  - the tag's commit not reachable from origin/main              -> REFUSE (exit 1)
  - the tag's commit on origin/main                              -> ALLOW  (exit 0), `sha=<commit>` to GITHUB_OUTPUT

Inputs (CLI flags take precedence over environment variables):
  --version   / DEPLOY_VERSION   e.g. "1.2.0", the tag is v1.2.0
  --repo-dir                     the caller's checkout, default the current folder
  --main-ref                     default origin/main

Requirements: standard library and git only.
"""

from __future__ import annotations

# standard imports
import argparse
import os
import re
import subprocess
import sys
from pathlib import Path

# ======================================================================================================================
# Configuration
# ======================================================================================================================

DEFAULT_MAIN_REF: str = "origin/main"

# MAJOR.MINOR.PATCH alone, so the tag name read from it can never be an option or a revision expression
VERSION: re.Pattern[str] = re.compile(r"[0-9]+\.[0-9]+\.[0-9]+")

# git's answers to merge-base --is-ancestor, any other status being a failure to ask
ANCESTOR:     int = 0
NOT_ANCESTOR: int = 1

# ======================================================================================================================
# The check
# ======================================================================================================================

def _git(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    """
    Run one git command in the caller's checkout, never raising on its status.

    Args:
        repo: The checkout
        args: The git arguments

    Returns:
        The finished process, its status and its output
    """
    return subprocess.run(["git", *args], cwd = repo, capture_output = True, text = True, check = False)


def _commit_of(repo: Path, ref: str) -> str | None:
    """
    Resolve a ref to the commit it names, peeling an annotated tag.

    Args:
        repo: The checkout
        ref: The full ref, refs/tags/v1.2.0 or refs/remotes/origin/main

    Returns:
        The commit's SHA, or None when the ref names no commit
    """
    answer = _git(repo, "rev-parse", "--verify", "--quiet", "--end-of-options", f"{ref}^{{commit}}")
    sha    = answer.stdout.strip()
    return sha if answer.returncode == 0 and sha else None


def check(repo: Path, version: str, main_ref: str = DEFAULT_MAIN_REF) -> tuple[bool, str, str | None]:
    """
    Decide whether the release's tag names a commit on main, and say why in one sentence.

    Args:
        repo: The caller's checkout, with its whole history and its tags
        version: The release version, with or without its v
        main_ref: The branch the commit must be reachable from, a remote tracking name

    Returns:
        ``(allowed, reason, sha)``, the SHA the tag's commit when allowed and None otherwise
    """
    number = version[1:] if version.startswith("v") else version
    if not VERSION.fullmatch(number):
        return False, f"{version!r} is not a release version, MAJOR.MINOR.PATCH (refused).", None
    tag = f"v{number}"

    shallow = _git(repo, "rev-parse", "--is-shallow-repository")
    if shallow.returncode != 0 or shallow.stdout.strip() != "false":
        return False, (
            f"The checkout's history is shallow or unreadable, so whether {tag} is on {main_ref} cannot be known "
            f"(refused). The release job checks out with fetch-depth 0."
        ), None
    main = _commit_of(repo, f"refs/remotes/{main_ref}")
    if main is None:
        return False, f"The checkout has no {main_ref}, so its history cannot judge {tag} (refused).", None

    sha = _commit_of(repo, f"refs/tags/{tag}")
    if sha is None:
        return False, (
            f"There is no tag {tag} in the checkout (refused). The release workflow creates the tag when VERSION "
            f"lands on main, and the release job fetches the tags."
        ), None

    ancestor = _git(repo, "merge-base", "--is-ancestor", sha, main)
    if ancestor.returncode == NOT_ANCESTOR:
        return False, (
            f"{tag} names commit {sha[:12]}, which is not on {main_ref} (refused). A release deploys only a commit "
            f"the owner merged to main."
        ), None
    if ancestor.returncode != ANCESTOR:
        return False, f"git could not say whether {tag} is on {main_ref}, {ancestor.stderr.strip()} (refused).", None
    return True, f"{tag} names commit {sha}, on {main_ref}, the commit every later job checks out.", sha

# ======================================================================================================================
# Output helpers
# ======================================================================================================================

def _append(path_name: str, text: str) -> None:
    """
    Append to a file the runner names in an environment variable, when it names one.

    Args:
        path_name: The environment variable, GITHUB_OUTPUT or GITHUB_STEP_SUMMARY
        text: What to append
    """
    path = os.environ.get(path_name)
    if path:
        with open(path, "a", encoding = "utf-8") as target:
            target.write(text)

# ======================================================================================================================
# CLI
# ======================================================================================================================

def parse_cli_args(argv: list[str] | None = None) -> argparse.Namespace:
    """
    Parse the flags, each optional since the environment stands in for the version in the job.

    Args:
        argv: The CLI arguments, None for the process's own

    Returns:
        The parsed namespace
    """
    parser = argparse.ArgumentParser(description = "Resolve a release's tag to a commit and refuse one off main.")
    parser.add_argument("--version", default = None, help = "the release version, e.g. 1.2.0, else DEPLOY_VERSION")
    parser.add_argument("--repo-dir", default = ".", help = "the caller's checkout, default the current folder")
    parser.add_argument("--main-ref", default = DEFAULT_MAIN_REF, help = "the branch to be on, default origin/main")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    """
    Read the inputs, check the release, print the verdict and write the commit for the later jobs.

    Args:
        argv: The CLI arguments, None for the process's own

    Returns:
        0 when the release's commit is on main, 1 when it is not or cannot be known
    """
    args    = parse_cli_args(argv)
    version = (args.version or os.environ.get("DEPLOY_VERSION", "")).strip()
    ok, reason, sha = check(Path(args.repo_dir), version, args.main_ref)
    line = f"{'OK' if ok else 'REFUSED'}: {reason}"
    print(line)
    _append("GITHUB_STEP_SUMMARY", f"### Release check\n\n{line}\n")
    if not ok:
        return 1
    _append("GITHUB_OUTPUT", f"sha={sha}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
