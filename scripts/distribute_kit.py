"""
Check and distribute the agentic-workflow kit (skills.md, WORKFLOW.md, docs/agent/*) from the
canonical source in kriegerdataforge-cicd/kit/common/ to every consumer repo in
scripts/kit_registry.json.

The kit is language-agnostic Markdown vendored byte-identical across the ecosystem. This script is
the propagation engine (see ADR D-001 / kriegerdataforge/docs/epics/agent-kit-distribution.md):
ONE source of truth (kit/common), ONE registry (kit_registry.json), owner-gated PRs.

Modes:
  check       Read-only. For each repo + kit file, fetch the repo's copy via the GitHub Contents
              API and compare it to kit/common/. Also reports gaps in the repo's own files, the role
              pointer in AGENTS.md and the env standard (ADR D-030). Prints a drift report and exits
              non-zero if any repo is out of sync. Used by the scheduled drift-alarm workflow; it OPENS NOTHING.
              A repo's AGENTS.md without the ecosystem context line (ADR D-046) counts as drift.
  distribute  For each repo that has drifted, create a branch, commit the updated kit files, and
              OPEN a pull request titled "chore(kit): sync agentic-workflow kit <KIT_VERSION>".
              The same pull request inserts the ecosystem context line into the repo's own AGENTS.md
              when it is absent, and changes nothing else in that page. It also sets
              open-pull-requests-limit 0 on every updates entry of the repo's .github/dependabot.yml,
              when the repo has one, so Dependabot raises alerts and opens no version update PR (D-047).
              Every file it changes is a kit copy or config no CI job reads, so each commit carries
              [skip ci] and the PR starts no workflow (D-047).
              It NEVER auto-merges — the owner reviews and merges. Requires a write-scoped token.

IMPORTANT — version-check: kit-sync PRs are docs-only. Each consumer's version-check workflow must
`paths-ignore` the kit paths (ADR D-001, option B) BEFORE running distribute, or the sync PRs will
fail that gate. distribute opens PRs; it does not bump VERSION.

Requirements:
    pip install requests

Environment variables:
  GH_TOKEN    GitHub token with contents:read (check) or contents + pull-requests:write
              (distribute) on all target repos. Use the CICD_PAT value.

Usage:
    GH_TOKEN=... python distribute_kit.py check
    GH_TOKEN=... python distribute_kit.py check --only skills.md
    GH_TOKEN=... python distribute_kit.py distribute --only skills.md
    # Target a subset of repos (comma-separated exact names); blank = all:
    GH_TOKEN=... python distribute_kit.py distribute --repos kriegerdataforge-sdk,fitness-app-backend
    GH_TOKEN=... python distribute_kit.py check --repos tiffanys-space,tiffanys-space-backend
"""

from __future__ import annotations

# standard imports
import argparse
import fnmatch
import json
import os
import re
import sys
from pathlib import Path

# third party imports
# local imports — the shared sync engine (transport + retry session live there; see
# common/repo_sync.py). Imported INTO this module's namespace on purpose: the
# check/distribute loops below call these module-level names, which keeps them
# patchable as `dk._get_remote_file` etc. in the white-box test suite.
from common.repo_sync import (  # noqa: F401  (re-exported for tests/callers)
    _SESSION,
    _create_branch,
    _create_pr,
    _get_branch_sha,
    _get_remote_file,
    _github_headers,
    _normalize,
    _open_pr_url,
    _put_file,
    _select_repos,
    ci_note,
    skip_ci_eligible,
    with_skip_ci,
)

# ======================================================================================================================
# Configuration
# ======================================================================================================================

SCRIPTS_DIR           = Path(__file__).parent
REPO_ROOT             = SCRIPTS_DIR.parent
REGISTRY_FILE         = SCRIPTS_DIR / "kit_registry.json"
KIT_DIR               = REPO_ROOT / "kit" / "common"
KIT_VERSION_FILE      = REPO_ROOT / "kit" / "KIT_VERSION"
VENDORED_VERSION_FILE = KIT_DIR / "docs" / "agent" / "KIT_VERSION"

# The one line the sync writes into a repo's own AGENTS.md, a pointer to the owner's private context repo beside it
# (cicd D-046). It names a path only, since this repo is public. Its presence is judged by the path.
AGENTS_FILE     = "AGENTS.md"
ROLE_POINTER    = "docs/agent/AGENT_ROLES.md"
ECOSYSTEM_PATH  = "../kriegerdataforge-context/AGENTS.md"
ECOSYSTEM_LINES = (
    "**Ecosystem context.** Before anything else, read `../kriegerdataforge-context/AGENTS.md`. That private repo",
    "beside this one holds where KDF is headed, the map of its repos and how sessions work. When it is not checked out",
    "there, carry on with this page.",
)
ECOSYSTEM_LABEL = "AGENTS.md (the ecosystem context line)"

# Dependabot raises alerts and opens no version update pull request (D-047). Its pull requests cannot install the
# private packages and ran every repo's CI on each rebase, about 800 billed minutes a week in four repos. A limit of 0
# stops version updates only. Security updates are a repo setting the owner switches, and alerts stay on. No CI job of
# any repo reads this file, so the sync may change it without running CI.
DEPENDABOT_FILE  = ".github/dependabot.yml"
DEPENDABOT_KEY   = "open-pull-requests-limit"
DEPENDABOT_LABEL = ".github/dependabot.yml (open-pull-requests-limit 0)"
_UPDATES_RE      = re.compile(r"^updates:\s*(#.*)?$")
_LIMIT_RE        = re.compile(rf"^(\s*(?:-\s+)?{DEPENDABOT_KEY}:\s*)([^#\s][^#]*?)?(\s*(?:#.*)?)$")
DEPENDABOT_NOTE  = (
    "**Dependabot.** Every `updates:` entry of `.github/dependabot.yml` gets `open-pull-requests-limit: 0`, so "
    "Dependabot keeps raising alerts and opens no version update pull request (cicd D-047). Security update pull "
    "requests are a repo setting the owner turns off, and alerts stay on either way."
)

# ======================================================================================================================
# Helpers
# ======================================================================================================================

def _load_registry() -> dict:
    if not REGISTRY_FILE.is_file():
        sys.exit(f"Error: registry file not found: {REGISTRY_FILE}")
    return json.loads(REGISTRY_FILE.read_text(encoding = "utf-8"))


def _kit_version() -> str:
    if KIT_VERSION_FILE.is_file():
        return KIT_VERSION_FILE.read_text(encoding = "utf-8").strip()
    return "unknown"


def _assert_version_consistency() -> None:
    """
    The vendored marker (``docs/agent/KIT_VERSION``, synced into every repo) must match the
    canonical ``kit/KIT_VERSION`` — bump both together. Guards against shipping a wrong version.
    """
    if not VENDORED_VERSION_FILE.is_file():
        return
    canonical = _kit_version()
    vendored  = VENDORED_VERSION_FILE.read_text(encoding = "utf-8").strip()
    if vendored != canonical:
        sys.exit(
            f"Error: kit version mismatch — kit/KIT_VERSION={canonical!r} but "
            f"docs/agent/KIT_VERSION={vendored!r}. Bump both together."
        )


def _read_local(rel_path: str) -> str:
    return (KIT_DIR / rel_path).read_text(encoding = "utf-8")


def _select_files(registry: dict, only: str | None) -> list[str]:
    files: list[str] = registry.get("files", [])
    if only:
        files = [f for f in files if only in f]
        if not files:
            sys.exit(f"Error: --only '{only}' matched no files in the registry.")
    return files


def compute_drift(token: str, owner_repo: str, branch: str, files: list[str]) -> list[str]:
    """
    Return the kit files whose repo copy differs from kit/common (or is missing).
    """
    drifted: list[str] = []
    for rel in files:
        local = _normalize(_read_local(rel))
        remote, _sha = _get_remote_file(token, owner_repo, branch, rel)
        if remote is None or _normalize(remote) != local:
            drifted.append(rel)
    return drifted


def insert_ecosystem_line(text: str) -> str:
    """
    Return a repo's AGENTS.md with the ecosystem context line, placed after the role pointer blockquote at the top, or
    after the first heading when the page has no such blockquote, or at the top when it has neither. A page that already
    names the context repo comes back unchanged, so a second run writes nothing. No other line is touched, and the
    inserted lines end the way the page's lines do.

    Args:
        text: The repo's AGENTS.md

    Returns:
        The page with the line, or the page itself when it already has it
    """
    if ECOSYSTEM_PATH in text:
        return text
    newline       = "\r\n" if "\r\n" in text else "\n"
    lines         = text.splitlines(keepends = True)
    bare          = [line.rstrip("\r\n") for line in lines]
    first_section = next((i for i, line in enumerate(bare) if line.startswith("## ")), len(lines))
    insert_at: int | None = None
    i = 0
    while i < first_section:
        if not bare[i].startswith(">"):
            i += 1
            continue
        end = i
        while end < len(lines) and bare[end].startswith(">"):
            end += 1
        if any(ROLE_POINTER in line for line in bare[i:end]):
            insert_at = end
            break
        i = end
    if insert_at is None:
        insert_at = next((i + 1 for i, line in enumerate(bare) if line.startswith("# ")), 0)
    if insert_at > 0 and not lines[insert_at - 1].endswith("\n"):
        lines[insert_at - 1] += newline
    block = [line + newline for line in ECOSYSTEM_LINES]
    if insert_at > 0:
        block.insert(0, newline)
    if insert_at < len(lines) and bare[insert_at].strip():
        block.append(newline)
    return "".join(lines[:insert_at] + block + lines[insert_at:])


def _updates_entries(bare: list[str]) -> list[tuple[int, int, int]]:
    """
    The entries of a dependabot.yml's `updates:` list, read line by line so comments and order survive.

    Args:
        bare: the page's lines without their line endings

    Returns:
        One (first line, end line exclusive, key indent) per entry, empty when the page has no block list there
    """
    start = next((i for i, line in enumerate(bare) if _UPDATES_RE.match(line)), None)
    if start is None:
        return []
    item_indent: int | None = None
    firsts:      list[int] = []
    end = len(bare)
    for i in range(start + 1, len(bare)):
        stripped = bare[i].strip()
        if not stripped or stripped.startswith("#"):
            continue
        indent  = len(bare[i]) - len(bare[i].lstrip(" "))
        is_item = stripped == "-" or stripped.startswith("- ")
        if item_indent is None:
            if not is_item:
                return []
            item_indent = indent
        if indent < item_indent or (indent == item_indent and not is_item):
            end = i
            break
        if indent == item_indent:
            firsts.append(i)
    entries: list[tuple[int, int, int]] = []
    for n, first in enumerate(firsts):
        last       = firsts[n + 1] if n + 1 < len(firsts) else end
        after      = bare[first][(item_indent or 0) + 1:]
        key_indent = (item_indent or 0) + 1 + len(after) - len(after.lstrip(" "))
        if not after.strip():  # a bare `-`, the keys start on the next content line
            nxt        = next((j for j in range(first + 1, last) if bare[j].strip()), None)
            key_indent = len(bare[nxt]) - len(bare[nxt].lstrip(" ")) if nxt is not None else key_indent + 1
        entries.append((first, last, key_indent))
    return entries


def limit_dependabot_prs(text: str) -> str:
    """
    Return a repo's dependabot.yml with `open-pull-requests-limit: 0` on every entry of its `updates:` list (D-047). A
    different limit is replaced, a missing one is added after the entry's last line, and comments, order and line
    endings are kept. A page already at 0 everywhere, or one without an `updates:` block list, comes back unchanged.

    Args:
        text: The repo's .github/dependabot.yml

    Returns:
        The page with every entry's limit at 0
    """
    newline = "\r\n" if "\r\n" in text else "\n"
    lines   = text.splitlines(keepends = True)
    bare    = [line.rstrip("\r\n") for line in lines]
    inserts: list[tuple[int, str]] = []
    for first, last, key_indent in _updates_entries(bare):
        found = False
        for j in range(first, last):
            indent = len(bare[j]) - len(bare[j].lstrip(" "))
            on_key = (j == first and bare[j].lstrip(" -").startswith(f"{DEPENDABOT_KEY}:")) or (
                j > first and indent == key_indent and bare[j].strip().startswith(f"{DEPENDABOT_KEY}:")
            )
            if not on_key:
                continue
            found = True
            match = _LIMIT_RE.match(bare[j])
            if match and match.group(2) != "0":
                ending = lines[j][len(bare[j]):]
                prefix = match.group(1) if match.group(1).endswith((" ", "\t")) else f"{match.group(1)} "
                lines[j] = f"{prefix}0{match.group(3)}{ending}"
        if not found:
            content = [j for j in range(first, last) if bare[j].strip() and not bare[j].strip().startswith("#")]
            inserts.append((content[-1] + 1, f"{' ' * key_indent}{DEPENDABOT_KEY}: 0{newline}"))
    for position, line in reversed(inserts):
        if position > 0 and not lines[position - 1].endswith("\n"):
            lines[position - 1] += newline
        lines.insert(position, line)
    return "".join(lines)


def dependabot_due(token: str, owner_repo: str, branch: str) -> bool:
    """
    Whether a repo's dependabot.yml still lets Dependabot open version update pull requests. A repo without the file
    gets none written.

    Args:
        token: A GitHub token that reads the repo
        owner_repo: The repo, as owner/name
        branch: The branch to read

    Returns:
        True when the sync should write the limits
    """
    page, _sha = _get_remote_file(token, owner_repo, branch, DEPENDABOT_FILE)
    return page is not None and limit_dependabot_prs(page) != page


def pretested_paths(files: list[str]) -> set[str]:
    """
    The exact paths a kit sync may change without running the repo's CI (D-047). The kit's own copies, tested by cicd's
    contract tests, plus the two lines the sync writes into config no CI job reads, the AGENTS.md pointer and the
    Dependabot limits.

    Args:
        files: the kit files of this run

    Returns:
        The allowlist
    """
    return {*files, AGENTS_FILE, DEPENDABOT_FILE}


def agents_line_missing(token: str, owner_repo: str, branch: str) -> bool:
    """
    Whether a repo's AGENTS.md lacks the ecosystem context line. A repo with no AGENTS.md gets none written, the role
    pointer gap reports it.

    Args:
        token: A GitHub token that reads the repo
        owner_repo: The repo, as owner/name
        branch: The branch to read

    Returns:
        True when the sync should write the line
    """
    agents, _sha = _get_remote_file(token, owner_repo, branch, AGENTS_FILE)
    return agents is not None and ECOSYSTEM_PATH not in agents


def _ignores(gitignore: str, name: str) -> bool:
    """
    Whether a root .gitignore ignores a file of this name at the repo root, the last matching line winning as in git.
    Directory rules are skipped, the env files live at the root.

    Args:
        gitignore: The text of the repo's root .gitignore
        name: A file name at the repo root, such as .env.kdf

    Returns:
        True when git would ignore the file
    """
    ignored = False
    for raw in gitignore.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        negate  = line.startswith("!")
        pattern = (line[1:] if negate else line).lstrip("/")
        if pattern.startswith("**/"):
            pattern = pattern[3:]
        if pattern.endswith("/"):
            continue
        if fnmatch.fnmatchcase(name, pattern):
            ignored = not negate
    return ignored


def compute_gaps(token: str, owner_repo: str, branch: str) -> list[str]:
    """
    Return what a repo's own files still lack of the ecosystem standard. The role pointer in AGENTS.md, and the env
    standard of ADR D-030, a tracked .env.kdf.example and a .gitignore that keeps .env.kdf out of git. These files are
    the repo's own, so check reports a gap and distribute never opens a pull request for one.

    Args:
        token: A GitHub token that reads the repo
        owner_repo: The repo, as owner/name
        branch: The branch to read

    Returns:
        One line per gap, empty when the repo meets the standard
    """
    gaps: list[str] = []
    agents, _sha = _get_remote_file(token, owner_repo, branch, "AGENTS.md")
    if agents is None or "docs/agent/AGENT_ROLES.md" not in agents:
        gaps.append("AGENTS.md lacks the role pointer to docs/agent/AGENT_ROLES.md")
    example, _sha = _get_remote_file(token, owner_repo, branch, ".env.kdf.example")
    if example is None:
        gaps.append("no .env.kdf.example, the env standard of ADR D-030")
    gitignore, _sha = _get_remote_file(token, owner_repo, branch, ".gitignore")
    if gitignore is None or not _ignores(gitignore, ".env.kdf"):
        gaps.append(".gitignore does not ignore .env.kdf")
    return gaps

# ======================================================================================================================
# Modes
# ======================================================================================================================

def cmd_check(registry: dict, token: str, only: str | None, repos_arg: str | None = None) -> int:
    """
    Read-only drift report. Exit 1 if any repo is out of sync or errored.
    """
    files = _select_files(registry, only)
    repos: list[dict] = _select_repos(registry, repos_arg)
    version = _kit_version()
    print(f"Checking agentic-workflow kit {version} across {len(repos)} repo(s), {len(files)} file(s):")

    any_drift = False
    any_gap   = False
    errors: list[str] = []
    for entry in repos:
        repo, branch = entry["repo"], entry.get("branch", "main")
        try:
            drift = compute_drift(token, repo, branch, files)
            if agents_line_missing(token, repo, branch):
                drift.append(ECOSYSTEM_LABEL)
            if dependabot_due(token, repo, branch):
                drift.append(DEPENDABOT_LABEL)
            gaps = compute_gaps(token, repo, branch)
        except Exception as exc:  # noqa: BLE001
            print(f"  {repo}: ERROR — {exc}")
            errors.append(f"{repo}: {exc}")
            continue
        if drift:
            any_drift = True
            print(f"  {repo}: DRIFT ({len(drift)}): {', '.join(drift)}")
        if gaps:
            any_gap = True
            print(f"  {repo}: GAPS ({len(gaps)}): {'; '.join(gaps)}")
        if not drift and not gaps:
            print(f"  {repo}: in sync")

    print()
    if errors:
        print(f"{len(errors)} repo(s) errored.")
        return 1
    if any_drift or any_gap:
        if any_drift:
            print("Drift detected. Run 'distribute' to open sync PRs.")
        if any_gap:
            print("Gaps in the repos' own files. Each is fixed in that repo's own pull request, distribute opens none.")
        return 1
    print("All repos in sync.")
    return 0


def cmd_distribute(registry: dict, token: str, only: str | None, repos_arg: str | None = None) -> int:
    """
    Open one sync PR per drifted repo. Never auto-merges.
    """
    files = _select_files(registry, only)
    repos: list[dict] = _select_repos(registry, repos_arg)
    version     = _kit_version()
    sync_branch = f"chore/kit-sync-{version}"
    title       = f"chore(kit): sync agentic-workflow kit {version}"

    opened:  list[str]  = []
    already: list[str] = []
    errors:  list[str]  = []
    print(f"Distributing kit {version} ({len(files)} file(s)) to {len(repos)} repo(s):")
    for entry in repos:
        repo, branch = entry["repo"], entry.get("branch", "main")
        try:
            drift      = compute_drift(token, repo, branch, files)
            context    = agents_line_missing(token, repo, branch)
            dependabot = dependabot_due(token, repo, branch)
            if not drift and not context and not dependabot:
                print(f"  {repo}: in sync — no PR")
                continue
            changed  = [*drift, *([AGENTS_FILE] if context else []), *([DEPENDABOT_FILE] if dependabot else [])]
            allow    = pretested_paths(files)
            skip     = skip_ci_eligible(changed, allow)
            base_sha = _get_branch_sha(token, repo, branch)
            _create_branch(token, repo, sync_branch, base_sha)
            for rel in drift:
                remote, blob_sha = _get_remote_file(token, repo, sync_branch, rel)
                content = _read_local(rel)
                if remote is not None and _normalize(remote) == _normalize(content):
                    continue  # the sync branch already carries it, a re-run
                _put_file(
                    token,
                    repo,
                    sync_branch,
                    rel,
                    content,
                    blob_sha,
                    with_skip_ci(f"chore(kit): sync {rel} to {version}", skip),
                )
            if context:
                # the repo's own page, read from the sync branch so a re-run that already wrote the line writes nothing
                agents, blob_sha = _get_remote_file(token, repo, sync_branch, AGENTS_FILE)
                if agents is not None and insert_ecosystem_line(agents) != agents:
                    _put_file(
                        token,
                        repo,
                        sync_branch,
                        AGENTS_FILE,
                        insert_ecosystem_line(agents),
                        blob_sha,
                        with_skip_ci(f"chore(kit): name the ecosystem context in AGENTS.md ({version})", skip),
                    )
                drift = [*drift, ECOSYSTEM_LABEL]
            if dependabot:
                # read from the sync branch too, so a re-run that already set the limits writes nothing
                page, blob_sha = _get_remote_file(token, repo, sync_branch, DEPENDABOT_FILE)
                if page is not None and limit_dependabot_prs(page) != page:
                    _put_file(
                        token,
                        repo,
                        sync_branch,
                        DEPENDABOT_FILE,
                        limit_dependabot_prs(page),
                        blob_sha,
                        with_skip_ci(f"chore(kit): Dependabot raises alerts and opens no PR ({version})", skip),
                    )
                drift = [*drift, DEPENDABOT_LABEL]
            existing = _open_pr_url(token, repo, sync_branch, branch)
            if existing:
                print(f"  {repo}: PR already open — {existing}")
                already.append(existing)
                continue
            body = (
                f"Automated sync of the agentic-workflow kit to **{version}** from "
                f"`kriegerdataforge-cicd/kit/common/`.\n\n"
                f"Files updated: {', '.join(drift)}\n\n"
                f"Docs-only. See ADR D-001 / the kit-distribution epic. Please review and merge.\n\n"
                f"{ci_note(skip, changed, allow)}"
            )
            if dependabot:
                body += f"\n\n{DEPENDABOT_NOTE}"
            url = _create_pr(token, repo, sync_branch, branch, title, body)
            print(f"  {repo}: PR opened — {url}")
            opened.append(url)
        except Exception as exc:  # noqa: BLE001
            print(f"  {repo}: FAILED — {exc}")
            errors.append(f"{repo}: {exc}")

    print()
    print(f"Opened {len(opened)} PR(s).")
    if already:
        print(f"{len(already)} PR(s) were already open, their branches are up to date.")
    if errors:
        print(f"{len(errors)} repo(s) failed:")
        for e in errors:
            print(f"  - {e}")
        return 1
    return 0

# ======================================================================================================================
# CLI
# ======================================================================================================================

def parse_cli_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description = "Check or distribute the agentic-workflow kit across the ecosystem.",
        formatter_class = argparse.RawDescriptionHelpFormatter,
        epilog = (
            "Examples:\n" "  # Read-only drift report across all repos (scheduled drift alarm)\n" "  GH_TOKEN=... python distribute_kit.py check\n\n" "  # Open sync PRs for skills.md only (v1 scope)\n" "  GH_TOKEN=... python distribute_kit.py distribute --only skills.md\n\n" "  # Target a subset of repos (comma-separated EXACT names, not substrings); blank = all\n" "  GH_TOKEN=... python distribute_kit.py distribute --repos kriegerdataforge-sdk,fitness-app-backend"
        ),
    )
    parser.add_argument(
        "mode",
        choices = ["check", "distribute"],
        help = "'check' reports drift (opens nothing). 'distribute' opens one PR per drifted repo.",
    )
    parser.add_argument(
        "--only",
        default = None,
        help = "Only operate on kit files whose path contains this substring (e.g. 'skills.md').",
    )
    parser.add_argument(
        "--repos",
        default = None,
        help = (
            "Only operate on these repos (comma-separated EXACT names, e.g. " "'kriegerdataforge-sdk,fitness-app-backend'). Matches the full owner/repo or the short " "name exactly (not a substring). Blank = all repos in the registry."
        ),
    )
    return parser.parse_args()


def main() -> None:
    args     = parse_cli_args()
    registry = _load_registry()
    _assert_version_consistency()
    token = os.environ.get("GH_TOKEN", "").strip()
    if not token:
        sys.exit("Error: GH_TOKEN environment variable not set.")

    if args.mode == "check":
        sys.exit(cmd_check(registry, token, args.only, args.repos))
    else:
        sys.exit(cmd_distribute(registry, token, args.only, args.repos))


if __name__ == "__main__":
    main()
