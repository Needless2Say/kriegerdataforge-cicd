"""
Write the fetch job into each reusable Python lane, and the standalone fetch workflow, from one template (D-035).

The lanes that install a caller's tree split in two when the caller asks for the owner's private packages. The fetch
job holds the token and runs only git and `fetch_private_packages.py`, the job that installs and tests names no secret.
A reusable workflow that calls another with a `./` path is not documented to resolve that path in its own repository
when a different repository calls it, so the fetch job is not a called workflow. It is written into every lane, its
script's text inline, and `fetch-private-packages.yml` carries the same job for a caller that runs its own install job,
the kdf-sdk canary. Each lane's install job takes its if and its first step from the same template, so a cancelled
run or a fetch that did not succeed ends it failed alike in every lane. The style lane takes the same fetch job and
the same if and first step for its check job (D-038), its fetch always runs, mirrors only the formatter the caller
pins and mints for it alone, so the template's @NAME@ fields are filled per copy. Every copy comes from
`fetch_private_job.template.yml`, and `test_secretless_lanes.py` fails when one differs.

Usage:
    python scripts/render_fetch_job.py           # write every copy
    python scripts/render_fetch_job.py --check   # exit 1 when a copy differs from the template

Standard library only.
"""

from __future__ import annotations

# standard imports
import argparse
import re
import sys
from pathlib import Path

# ======================================================================================================================
# Configuration
# ======================================================================================================================

ROOT      = Path(__file__).resolve().parents[1]
WORKFLOWS = ROOT / ".github" / "workflows"
SCRIPT    = ROOT / "scripts" / "fetch_private_packages.py"
TEMPLATE  = ROOT / "scripts" / "fetch_private_job.template.yml"

# the lanes whose install and test job runs the caller's tree, each split in two when it asks for package access
LANES = (
    "ci-python-tests.yml",
    "ci-python-integration.yml",
    "ci-python-system.yml",
    "ci-python-mutation.yml",
    "ci-python-security.yml",
    "ci-python-lint.yml",
    "ci-python-typecheck.yml",
)

STANDALONE = "fetch-private-packages.yml"

# the style lane, whose check job runs the caller's tree too, a module of it on the import path or its own command
# (D-038), so its fetch job always runs and its check job names no secret
STYLE_LANE = "ci-python-kdf-fmt.yml"

DELIMITER = "KDF_FETCH_PRIVATE_PACKAGES"

# the values of the template's @NAME@ fields, from the caller's inputs in the seven lanes and the standalone
LANE_FILLS = {
    "REQUIREMENT_FILES": "${{ inputs.requirement_files }}",
    "EXTRA_REPOS": "${{ inputs.extra_repos }}",
    "SCAN_FILES": "${{ inputs.scan_files }}",
    "TOKEN_REPOSITORIES": "${{ inputs.token_repositories }}",
    "NEEDS_SDK_AUTH": "inputs.needs_sdk_auth",
}

# and fixed in the style lane, no requirement file read, the pinned formatter its one mirror and its token's one repo
STYLE_FILLS = {
    "REQUIREMENT_FILES": '""',
    "EXTRA_REPOS": "kriegerdataforge-fmt@${{ inputs.kdf_fmt_ref }}",
    "SCAN_FILES": '""',
    "TOKEN_REPOSITORIES": "kriegerdataforge-fmt",
    "NEEDS_SDK_AUTH": "true",
}

# the fetch job's if in a lane, where it runs only when the caller asks for package access
LANE_CONDITION = "    if: ${{ inputs.needs_sdk_auth }}\n"

# where a lane's fetch job ends, the next job's id line that is not the fetch job's own
NEXT_JOB = r"(?=^  [a-z0-9-]+:\n(?!    name: Fetch private packages))"

# the install job's if with the comment above it, and its first step up to the blank line after it
INSTALL_GUARD   = re.compile(r"^    # D-035\. FAIL CLOSED\.[^\n]*\n(?:    #[^\n]*\n)*    if: [^\n]*\n", re.MULTILINE)
INSTALL_REQUIRE = re.compile(r"^      - name: Require the private packages\n(?:[^\n]+\n)*", re.MULTILINE)

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


def sections() -> dict[str, str]:
    """
    The template's sections, each by the name on its `#@ <name>` line.

    Returns:
        dict[str, str]: each section's text, LF line ends
    """
    found: dict[str, str] = {}
    name = ""
    for line in _read(TEMPLATE).replace("\r\n", "\n").splitlines(keepends = True):
        marker = re.fullmatch(r"#@ (\S+)\n", line)
        if marker:
            name = marker.group(1)
            found[name] = ""
        elif name:
            found[name] += line
    return found


def fill(text: str, fills: dict[str, str]) -> str:
    """
    A section with its @NAME@ fields filled.

    Args:
        text: the section's text
        fills: each field's value by its name

    Returns:
        str: the text with every field filled

    Raises:
        SystemExit: when a field is left that no value fills
    """
    for name, value in fills.items():
        text = text.replace(f"@{name}@", value)
    # the script, its heredoc's end and the inputs section are written in by the functions that place them
    left = [field for field in re.findall(r"@[A-Z_]+@", text) if field not in ("@SCRIPT@", "@DELIMITER@", "@INPUTS@")]
    if left:
        raise SystemExit(f"the template holds a field no value fills, {', '.join(sorted(set(left)))}")
    return text


def section(name: str, fills: dict[str, str]) -> str:
    """
    One section of the template, its fields filled.

    Args:
        name: the section's name
        fills: each field's value by its name

    Returns:
        str: the section's text, LF line ends
    """
    return fill(sections()[name], fills)


def job(condition: str, fills: dict[str, str]) -> str:
    """
    The fetch job, the script's own text inline.

    Args:
        condition: the job's if line, empty where it always runs
        fills: the values of the template's fields for this copy

    Returns:
        str: the job's text, LF line ends

    Raises:
        SystemExit: when the script holds an expression or a line that would end the heredoc
    """
    script = _read(SCRIPT).replace("\r\n", "\n")
    if "${{" in script or f"\n{DELIMITER}\n" in f"\n{script}\n":
        raise SystemExit("fetch_private_packages.py must hold no ${{ and no line that ends the heredoc")
    indented = "\n".join(f"          {line}" if line else "" for line in script.rstrip("\n").split("\n"))
    body     = section("job-body", fills).replace("@SCRIPT@", indented).replace("@DELIMITER@", DELIMITER)
    return sections()["job-head"] + condition + body


def render_install(plain: str, fills: dict[str, str]) -> str:
    """
    A lane with its install job's if and first step replaced by the template's, so a cancelled run or a fetch that
    did not succeed ends the job failed in every lane alike.

    Args:
        plain: the lane's text, LF line ends
        fills: the values of the template's fields for this copy

    Returns:
        str: the lane's text with both written from the template

    Raises:
        SystemExit: when the lane does not hold exactly one of each
    """
    for pattern, name in ((INSTALL_GUARD, "install-guard"), (INSTALL_REQUIRE, "install-require")):
        plain, count = pattern.subn(lambda _match, text = section(name, fills): text, plain)
        if count != 1:
            raise SystemExit(f"a lane holds {count} of the install job's {name}, not one")
    return plain


def render_lane(text: str, fills: dict[str, str] = LANE_FILLS, condition: str = LANE_CONDITION) -> str:
    """
    A lane with its fetch job replaced, or written first under `jobs:` when it has none, and its install job's if
    and first step written from the template.

    Args:
        text: the lane's text
        fills: the values of the template's fields for this lane
        condition: the fetch job's if line, empty in the style lane, whose fetch always runs

    Returns:
        str: the lane's new text, in the lane's own line endings

    Raises:
        SystemExit: when the lane has no jobs: line, or not one install job if and first step
    """
    crlf  = "\r\n" in text
    plain = text.replace("\r\n", "\n")
    block = job(condition, fills) + "\n"
    found = re.search(r"^  # D-035\. The one job.*?" + NEXT_JOB, plain, flags = re.MULTILINE | re.DOTALL)
    if found:
        plain = plain[:found.start()] + block + plain[found.end():]
    else:
        head, marker, rest = plain.partition("\njobs:\n")
        if not marker:
            raise SystemExit("a lane without a jobs: line")
        plain = head + marker + block + rest.lstrip("\n")
    plain = render_install(plain, fills)
    return plain.replace("\n", "\r\n") if crlf else plain


def render_standalone() -> str:
    """
    The standalone fetch workflow, its inputs the lanes' own.

    Returns:
        str: the workflow's text, LF line ends
    """
    parts = sections()
    return parts["standalone-head"].replace("@INPUTS@\n", parts["inputs"]) + job("", LANE_FILLS)

# ======================================================================================================================
# CLI
# ======================================================================================================================

def main(argv: list[str] | None = None) -> int:
    """
    Write every copy, or with --check report the ones that differ.

    Args:
        argv: the arguments, sys.argv when None

    Returns:
        int: 1 when --check finds a copy that differs, else 0
    """
    parser = argparse.ArgumentParser(description = "Write the fetch job into every lane from its one template.")
    parser.add_argument("--check", action = "store_true", help = "exit 1 when a copy differs, write nothing")
    args = parser.parse_args(argv)
    stale: list[str] = []
    targets = {name: render_lane(_read(WORKFLOWS / name)) for name in LANES}
    targets[STYLE_LANE] = render_lane(_read(WORKFLOWS / STYLE_LANE), STYLE_FILLS, "")
    targets[STANDALONE] = render_standalone()
    for name, wanted in targets.items():
        path    = WORKFLOWS / name
        current = _read(path) if path.exists() else None
        # a checkout on Windows holds the files with CRLF ends, a copy is judged and written in the file's own
        if current is not None and "\r\n" in current and "\r\n" not in wanted:
            wanted = wanted.replace("\n", "\r\n")
        if current == wanted:
            continue
        stale.append(name)
        if not args.check:
            path.write_text(wanted, encoding = "utf-8", newline = "")
    for name in stale:
        print(f"{'differs' if args.check else 'written'}: {name}")
    return 1 if args.check and stale else 0


if __name__ == "__main__":
    sys.exit(main())
