"""
Suppressions, design 5.9's second part, on real findings. Opengrep runs with --disable-nosem and zizmor with
--no-ignores, so the wrapper alone binds each marker, at the end of a finding's first line, alone on the line straight
above it, or on a run block's line for a finding inside the block. A finding's first line is the line its rule
reports, so a rule that focuses on one argument, as subprocess-shell-true focuses on shell=True, reports that
argument's line, and a marker on the call's first line is stale, the build's dry run of 2026-10-22. Each bad form of
section 4 fails, a marker in an excluded file, a stale one and an ambiguous id among them, and kdf_zizmor.yml stays in
force under --no-ignores, the King's F4 and F5.
"""

from __future__ import annotations

import pytest
from scanfix import installed, lines, make_repo, scan

SHELL      = "subprocess.run(command, shell=True)"
RULE       = "subprocess-shell-true"
REASON     = "the command is a constant"
SHELL_FILE = "import subprocess\n\n\ndef run(command):\n{line}\n"
JWT_LINE   = '  return jwt.sign(claims, "a-fixture-secret");'
HMAC_LINE  = '  return crypto.createHmac("sha256", "a-fixture-key").update(body).digest("hex");'
# each file, its text, whether it must accept its finding, and the words its bad marker must carry, None for a file
# whose marker text is no marker at all
OPENGREP  = {
    "src/end_of_line.py": (SHELL_FILE.format(line = f"    return {SHELL}  # nosemgrep: {RULE} {REASON}"), True, None),
    "src/line_above.py": (
        SHELL_FILE.format(line = f"    # nosemgrep: {RULE} {REASON}\n    return {SHELL}"),
        True,
        None,
    ),
    "src/multi_line.py": (
        lines(
            "import yaml",
            "",
            "",
            "def load(text):",
            "    return yaml.unsafe_load(  # nosemgrep: avoid-pyyaml-load the text is a fixture constant",
            "        text,",
            "    )",
        ),
        True,
        None,
    ),
    "src/focused.py": (
        lines(
            "import subprocess",
            "",
            "",
            "def run(command):",
            f"    return subprocess.run(  # nosemgrep: {RULE} {REASON}",
            "        command,",
            "        shell=True,",
            "    )",
        ),
        False,
        "stale",
    ),
    "src/bare.py": (SHELL_FILE.format(line = f"    return {SHELL}  # nosemgrep"), False, "a bare nosemgrep"),
    "src/nosem.py": (SHELL_FILE.format(line = f"    return {SHELL}  # nosem: {RULE} {REASON}"), False, "never nosem"),
    "src/noopengrep.py": (
        SHELL_FILE.format(line = f"    return {SHELL}  # noopengrep: {RULE} {REASON}"),
        False,
        "never noopengrep",
    ),
    "src/short_reason.py": (
        SHELL_FILE.format(line = f"    return {SHELL}  # nosemgrep: {RULE} fixed"),
        False,
        "fewer than three",
    ),
    "src/comma_reason.py": (
        SHELL_FILE.format(line = f"    return {SHELL}  # nosemgrep: {RULE} fixed here, by hand today"),
        False,
        "holds a comma",
    ),
    "src/two_rules.py": (
        SHELL_FILE.format(line = f"    return {SHELL}  # nosemgrep: {RULE},avoid-pyyaml-load {REASON}"),
        False,
        "two rules in one comment",
    ),
    "src/stale.py": (
        lines("def add(a, b):", "    return a + b  # nosemgrep: avoid-pyyaml-load nothing of that kind sits here"),
        False,
        "stale",
    ),
    "src/ambiguous.js": (
        lines(
            'const jwt = require("jsonwebtoken");',
            "",
            "function issue(claims) {",
            f"{JWT_LINE}  // nosemgrep: hardcoded-jwt-secret the key signs nothing",
            "}",
            "",
            "module.exports = { issue };",
        ),
        False,
        "ambiguous",
    ),
    "src/accepted.js": (
        lines(
            'const crypto = require("crypto");',
            "",
            "function sign(body) {",
            "  // nosemgrep: hardcoded-hmac-key the key signs fixture data alone",
            HMAC_LINE,
            "}",
            "",
            "module.exports = { sign };",
        ),
        True,
        None,
    ),
    # marker text inside a regular expression after a control header, no comment at all, Codex's read of fd624a6
    "src/regex_after_if.js": (
        lines(
            'const crypto = require("crypto");',
            "",
            "function sign(body) {",
            f'{HMAC_LINE} if (true) /[ // nosemgrep: hardcoded-hmac-key the key signs fixture data]/.test("x");',
            "}",
            "",
            "module.exports = { sign };",
        ),
        False,
        None,
    ),
    "vendor/copied.py": (
        SHELL_FILE.format(line = f"    return {SHELL}  # nosemgrep: {RULE} {REASON}"),
        False,
        "a marker in a file the scan does not read",
    ),
}
EXCLUDE   = "SCAN_EXCLUDE += vendor  # a vendored copy this repo never edits"
HEAD      = ("on: push", "permissions: {}", "jobs:", "  build:", "    runs-on: ubuntu-latest", "    steps:")
CHECKOUT  = "      - uses: actions/checkout@v4"
WORKFLOWS = {
    ".github/workflows/line.yml": lines(
        "name: line",
        *HEAD,
        f"{CHECKOUT}  # zizmor: ignore[unpinned-uses] the fixture runs nothing it checks out",
    ),
    ".github/workflows/file.yml": lines(
        "# zizmor: ignore[unpinned-uses] a marker for the whole file",
        "name: file",
        *HEAD,
        CHECKOUT,
    ),
    ".github/workflows/job.yml": lines(
        "name: job",
        *HEAD[:3],
        "  # zizmor: ignore[unpinned-uses] a marker for the whole job",
        *HEAD[3:],
        CHECKOUT,
    ),
    ".github/workflows/step.yml": lines(
        "name: step",
        *HEAD,
        "      # zizmor: ignore[unpinned-uses] a marker for the whole step",
        "      - name: check out",
        "        uses: actions/checkout@v4",
    ),
    ".github/workflows/two.yml": lines(
        "name: two",
        *HEAD,
        f"{CHECKOUT}  # zizmor: ignore[unpinned-uses,template-injection] both are fixtures here",
    ),
    ".github/workflows/run_block.yml": lines(
        "name: run block",
        "on:",
        "  issues:",
        "    types: [opened]",
        "permissions: {}",
        "jobs:",
        "  greet:",
        "    runs-on: ubuntu-latest",
        "    steps:",
        "      - name: greet",
        "        run: |  # zizmor: ignore[template-injection] the title is echoed to a log alone",
        '          echo "${{ github.event.issue.title }}"',
    ),
    ".github/workflows/reuse.yml": lines(
        "name: reuse",
        "on: push",
        "permissions: {}",
        "jobs:",
        "  call:",
        "    uses: an-owner/a-repo/.github/workflows/build.yml@" + "9" * 40,
        "    secrets: inherit",
    ),
    ".github/workflows/clean.yml": lines(
        "name: clean",
        *HEAD,
        "      - uses: actions/checkout@" + "8" * 40,
        "        with:",
        "          persist-credentials: false",
    ),
}


@pytest.fixture(scope = "module")
def marked(tmp_path_factory: pytest.TempPathFactory) -> tuple:
    files = {path: text for path, (text, _accepts, _bad) in OPENGREP.items()} | WORKFLOWS
    repo  = make_repo(tmp_path_factory.mktemp("markers") / "repo", files, own = (EXCLUDE,))
    return scan(installed(), repo), repo


@pytest.mark.parametrize("path", sorted(OPENGREP))
def test_each_opengrep_marker_binds_only_in_its_one_good_form(marked: tuple, path: str) -> None:
    result, _repo = marked
    _text, accepts, bad = OPENGREP[path]
    accepted = {rule for where, rule in result.accepted() if where == path}
    flagged  = [why for where, why in result.bad() if where == path]
    if accepts:
        assert accepted and not flagged, (path, result.text)
        assert not {rule for where, rule in result.fails() if where == path}, result.text
    elif bad is None:
        # text that is no marker at all, so nothing is accepted, nothing flagged, and the finding fails
        assert not accepted and not flagged, (path, result.text)
        assert {rule for where, rule in result.fails() if where == path}, (path, result.text)
    else:
        assert not accepted, (path, result.text)
        assert any(bad in why for why in flagged), (path, flagged, result.text)


def test_a_finding_whose_marker_is_bad_still_fails(marked: tuple) -> None:
    result, _repo = marked
    for path in ("src/bare.py", "src/nosem.py", "src/short_reason.py", "src/comma_reason.py", "src/two_rules.py"):
        assert (path, RULE) in result.fails(), (path, result.text)


def test_a_zizmor_marker_binds_on_its_line_and_on_a_run_blocks_line_alone(marked: tuple) -> None:
    result, _repo = marked
    assert (".github/workflows/line.yml", "unpinned-uses") in result.accepted(), result.text
    assert (".github/workflows/run_block.yml", "template-injection") in result.accepted(), result.text
    for name in ("file", "job", "step"):
        path = f".github/workflows/{name}.yml"
        assert (path, "unpinned-uses") in result.fails(), (path, result.text)
        assert any(where == path and "stale" in why for where, why in result.bad()), (path, result.text)


def test_two_audits_in_one_zizmor_marker_are_refused(marked: tuple) -> None:
    result, _repo = marked
    path = ".github/workflows/two.yml"
    assert any(where == path and "two audits" in why for where, why in result.bad()), result.text
    assert (path, "unpinned-uses") in result.fails(), result.text


def test_kdf_zizmor_yml_stays_in_force_under_no_ignores(marked: tuple) -> None:
    result, _repo = marked
    for path in (".github/workflows/reuse.yml", ".github/workflows/clean.yml"):
        assert not {rule for where, rule in result.fails() if where == path}, (path, result.text)
